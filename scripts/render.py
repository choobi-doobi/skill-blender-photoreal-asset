"""Locked evaluation scene, configured by the project's asset.json. Agents may NOT edit this file.

Run through run.py (queues on the GPU, builds a contact sheet), or directly:
    blender --background --factory-startup --python render.py -- --asset asset.json --parts a.blend [b.blend ...]
        --out DIR [--preview] [--cams hero,ui] [--custom "fx,fy,fz:tx,ty,tz:lens"] [--save]

Every top-level collection whose name starts with the asset's collection_prefix is appended from each part file.
Nothing else from the part file (world, cameras, render settings) is used. Images in part files must be packed.
"""
import argparse
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assetcfg  # noqa: E402
from render_support import configure_cycles, daylight_world  # noqa: E402


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--asset", required=True)
    p.add_argument("--parts", nargs="*", default=[])
    p.add_argument("--out", required=True)
    p.add_argument("--preview", action="store_true")
    p.add_argument("--cams", default="")
    p.add_argument("--custom", action="append", default=[], help='"fx,fy,fz:tx,ty,tz:lens" (repeatable)')
    p.add_argument("--save", action="store_true", help="also save the assembled scene.blend")
    return p.parse_args(argv)


def setup_render(cfg, preview):
    s = bpy.context.scene
    q = cfg["preview"] if preview else cfg["final"]
    configure_cycles(s)
    s.cycles.samples = q["samples"]
    s.cycles.use_adaptive_sampling = True
    s.cycles.adaptive_threshold = 0.01
    s.cycles.use_denoising = True
    s.cycles.max_bounces = 12
    s.cycles.glossy_bounces = 6
    s.cycles.transmission_bounces = 8
    s.cycles.caustics_reflective = False
    s.cycles.caustics_refractive = False
    s.render.resolution_x, s.render.resolution_y = q["res"]
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_depth = "8"
    s.view_settings.view_transform = "AgX"
    s.view_settings.look = "None"
    s.view_settings.exposure = 0.0
    s.render.film_transparent = False


def setup_world(cfg):
    bpy.context.scene.world = daylight_world("Harness_World", cfg["hdri"],
                                             cfg["hdri_strength"], cfg["hdri_rotation_deg"])


def setup_ground(cfg):
    """Plain worn asphalt to the horizon at ground_z (default 1 cm below z = 0). ground = "none" skips it."""
    if cfg["ground"] == "none":
        return
    bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, cfg["ground_z"]))
    g = bpy.context.active_object
    g.name = "Harness_Asphalt"
    m = bpy.data.materials.new("Harness_Asphalt")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 180.0
    n1.inputs["Detail"].default_value = 12.0
    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = 0.6
    n2.inputs["Detail"].default_value = 4.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.035, 0.035, 0.036, 1)
    ramp.color_ramp.elements[1].color = (0.11, 0.105, 0.10, 1)
    mix = nt.nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.5
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.78
    rough.inputs["To Max"].default_value = 0.95
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.002
    nt.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    nt.links.new(n1.outputs["Fac"], mix.inputs[0])
    nt.links.new(n2.outputs["Fac"], mix.inputs[2])
    nt.links.new(mix.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(n1.outputs["Fac"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    nt.links.new(n1.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    g.data.materials.append(m)


def add_camera(name, loc, target, lens):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.sensor_width = 36.0
    cam.clip_start = 0.02
    cam.clip_end = 1000.0
    ob = bpy.data.objects.new("Cam_" + name, cam)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def append_parts(cfg, paths):
    scene_coll = bpy.context.scene.collection
    prefix = cfg["collection_prefix"]
    for path in paths:
        path = os.path.abspath(path)
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.collections = [c for c in src.collections if c.startswith(prefix)]
        got = [c for c in dst.collections if c is not None]
        children = {ch.name for c in got for ch in c.children_recursive}
        for c in got:
            if c.name not in children:
                scene_coll.children.link(c)
        print(f"[harness] {os.path.basename(path)}: {[c.name for c in got if c.name not in children]}")
    missing = [i.name for i in bpy.data.images if i.source == "FILE" and not i.packed_file
               and i.name != os.path.basename(cfg["hdri"]) and not os.path.exists(bpy.path.abspath(i.filepath))]
    if missing:
        print(f"[harness] WARNING missing (unpacked) images render pink: {missing}")


def main():
    a = args()
    cfg = assetcfg.load(a.asset)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render(cfg, a.preview)
    setup_world(cfg)
    setup_ground(cfg)
    append_parts(cfg, a.parts)
    os.makedirs(a.out, exist_ok=True)
    names = [n for n in a.cams.split(",") if n] or list(cfg["cameras"])
    shots = {n: cfg["cameras"][n] for n in names}
    for i, spec in enumerate(a.custom):
        f, t, lens = spec.split(":")
        shots[f"custom{i}"] = (tuple(map(float, f.split(","))), tuple(map(float, t.split(","))), float(lens))
    s = bpy.context.scene
    for name, (loc, target, lens) in shots.items():
        s.camera = add_camera(name, loc, target, lens)
        s.render.filepath = os.path.join(os.path.abspath(a.out), name + ".png")
        bpy.ops.render.render(write_still=True)
        print(f"[harness] wrote {s.render.filepath}")
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.abspath(a.out), "scene.blend"))


main()
