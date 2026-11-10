"""Blender side of game_check.py (run through it, not directly): measure the LODs, the collision mesh and the
high-poly mesh, dump each LOD's UV triangles, and render the LOD turntable frames.

    blender --background --factory-startup --python game_check_bl.py -- --blend asset.blend --name Barrel
        --out DIR --hdri sky.hdr [--size 512] [--samples 32] [--no-render]
"""
import argparse
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from bpy_extras import mesh_utils
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_support import configure_cycles, daylight_world  # noqa: E402

GODOT_COL = ("-convcolonly", "-colonly", "-convcol", "-col")
ANGLES = (45, 135, 225, 315)


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--hdri", default="")
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--no-render", action="store_true")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def topology(ob):
    """Tri/n-gon/manifold/winding counts of the evaluated mesh, in object space."""
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    r = dict(tris=sum(len(f.verts) - 2 for f in bm.faces), faces=len(bm.faces), verts=len(bm.verts),
             ngons=sum(1 for f in bm.faces if len(f.verts) > 4),
             boundary_edges=sum(1 for e in bm.edges if e.is_boundary),
             multi_face_edges=sum(1 for e in bm.edges if len(e.link_faces) > 2),
             wire_edges=sum(1 for e in bm.edges if e.is_wire),
             # two faces walking a shared edge the same way = one of them is flipped
             inconsistent_edges=sum(1 for e in bm.edges if len(e.link_loops) == 2
                                    and e.link_loops[0].vert == e.link_loops[1].vert))
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    r["signed_volume"] = sum(f.verts[0].co.dot(f.verts[1].co.cross(f.verts[2].co)) for f in bm.faces) / 6
    co = np.array([v.co[:] for v in bm.verts]) if bm.verts else np.zeros((1, 3))
    r["bbox_lo"], r["bbox_hi"] = co.min(0).tolist(), co.max(0).tolist()
    if ob.name.endswith(GODOT_COL):  # convex: no vertex in front of any face plane
        bm.normal_update()
        eps = 1e-3 * float(np.linalg.norm(co.max(0) - co.min(0)))  # 1 mm per metre: slightly warped quads
        worst = max((max((v.co - f.calc_center_median()).dot(f.normal) for v in bm.verts) for f in bm.faces), default=0)
        r["convex"], r["convex_excess"] = bool(worst <= eps), float(worst)
    bm.free()
    ev.to_mesh_clear()
    return r


def uv_dump(ob, path):
    """UV triangles (T,3,2), their UV island ids and world-space areas, for game_check.py's UV checks."""
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    if not me.uv_layers:
        ev.to_mesh_clear()
        return None
    island_of = {}
    for i, polys in enumerate(mesh_utils.mesh_linked_uv_islands(me)):
        for pi in polys:
            island_of[pi] = i
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    mw = ob.matrix_world
    uv = np.array([[uvl[li].uv[:] for li in lt.loops] for lt in me.loop_triangles], np.float32).reshape(-1, 3, 2)
    pts = [[mw @ me.vertices[vi].co for vi in lt.vertices] for lt in me.loop_triangles]
    area = np.array([((b - a).cross(c - a)).length / 2 for a, b, c in pts], np.float32)
    island = np.array([island_of.get(lt.polygon_index, -1) for lt in me.loop_triangles], np.int32)
    np.savez_compressed(path, uv=uv, island=island, area=area)
    ev.to_mesh_clear()
    return dict(uv_layers=[u.name for u in ob.data.uv_layers], islands=int(island.max() + 1) if len(island) else 0)


def images_of(ob):
    out = []
    for slot in ob.material_slots:
        if slot.material and slot.material.node_tree:
            for n in slot.material.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    out.append(dict(image=n.image.name, size=list(n.image.size), packed=bool(n.image.packed_file)))
    return out


def render_turntable(lods, out, hdri, size, samples):
    s = bpy.data.scenes.new("GC_Turntable")
    bpy.context.window.scene = s
    for ob in lods:
        s.collection.objects.link(ob)
    configure_cycles(s)
    s.cycles.samples = samples
    s.render.resolution_x = s.render.resolution_y = size
    s.view_settings.view_transform = "AgX"
    s.world = daylight_world("GC_World", hdri)
    corners = np.array([np.array(lods[0].matrix_world @ Vector(c)) for c in lods[0].bound_box])
    lo, hi = Vector(corners.min(0)), Vector(corners.max(0))
    centre, radius = (lo + hi) / 2, (hi - lo).length / 2
    bpy.ops.mesh.primitive_plane_add(size=radius * 12, location=(centre.x, centre.y, lo.z))
    floor = bpy.context.active_object
    fm = bpy.data.materials.new("GC_Floor")
    fm.use_nodes = True
    fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.18, 0.18, 1)
    fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(fm)
    cam = bpy.data.objects.new("GC_Cam", bpy.data.cameras.new("GC_Cam"))
    s.collection.objects.link(cam)
    cam.data.lens, cam.data.sensor_width = 50, 36
    s.camera = cam
    dist = radius / math.tan(math.atan(18 / 50)) * 1.15
    frames = {}
    for i, ob in enumerate(lods):
        for other in lods:
            other.hide_render = other is not ob
        for a in ANGLES:
            az, el = math.radians(a), math.radians(20)
            cam.location = centre + Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))) * dist
            cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
            s.render.filepath = os.path.join(out, f"tt_LOD{i}_{a:03d}.png")
            bpy.ops.render.render(write_still=True)
            frames.setdefault(f"LOD{i}", []).append(s.render.filepath)
    return frames


def main():
    a = args()
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(a.blend))
    os.makedirs(a.out, exist_ok=True)
    obs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}
    data = dict(name=a.name, objects=sorted(obs), lods={}, collision=None, high=None)
    lods = []
    for i in range(4):
        ob = obs.get(f"{a.name}_LOD{i}")
        if not ob:
            continue
        lods.append(ob)
        d = topology(ob)
        d.update(location=list(ob.location), rotation=list(ob.rotation_euler), scale=list(ob.scale),
                 rotation_mode=ob.rotation_mode, materials=[s.material.name for s in ob.material_slots if s.material],
                 images=images_of(ob), uv=uv_dump(ob, os.path.join(a.out, f"uv_LOD{i}.npz")))
        data["lods"][f"LOD{i}"] = d
    col = [n for n in obs if n.startswith(a.name) and n.endswith(GODOT_COL)]
    if col:
        data["collision"] = dict(object=col[0], **topology(obs[col[0]]))
    high = obs.get(f"{a.name}_high")
    if high:
        data["high"] = dict(object=high.name, tris=topology(high)["tris"])
    if lods and not a.no_render:
        data["turntable"] = render_turntable(lods, a.out, a.hdri, a.size, a.samples)
    with open(os.path.join(a.out, "game_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print(f"[game_check] measured {len(lods)} LODs, collision {bool(col)}, high-poly {bool(high)}")


main()
