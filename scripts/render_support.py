"""Shared Cycles device and daylight setup, run inside Blender's Python."""
import math
import os

import bpy


def configure_cycles(scene):
    """Use an available GPU backend, or CPU when none is found."""
    scene.render.engine = "CYCLES"
    requested = os.environ.get("PHOTOREAL_CYCLES_DEVICE", "AUTO").upper()
    backends = ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI")
    if requested not in ("AUTO", "CPU", *backends):
        raise ValueError(f"Unknown PHOTOREAL_CYCLES_DEVICE: {requested}")
    selected = "CPU"
    if requested != "CPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in backends if requested == "AUTO" else (requested,):
            try:
                prefs.compute_device_type = backend
                prefs.refresh_devices()
            except (TypeError, ValueError, RuntimeError):
                continue  # Backend unsupported by this Blender build or host.
            devices = [d for d in prefs.devices if d.type == backend]
            if devices:
                for device in prefs.devices:
                    device.use = device.type == backend
                selected = backend
                break
        if selected == "CPU" and requested != "AUTO":
            raise RuntimeError(f"No {requested} Cycles device available; use AUTO or CPU")
    scene.cycles.device = "CPU" if selected == "CPU" else "GPU"
    scene.cycles.use_denoising = True
    # OpenImageDenoise works without an NVIDIA GPU.
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    print(f"[harness] Cycles device: {selected}")


def daylight_world(name, hdri="", strength=1.0, rotation_deg=0.0):
    """Create an HDRI world, or a procedural sky when no image is configured."""
    world = bpy.data.worlds.new(name)
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    if hdri:
        if not os.path.isfile(hdri):
            raise FileNotFoundError(f"HDRI not found: {hdri}. Set hdri to an existing file or an empty string.")
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri)
        mapping = nt.nodes.new("ShaderNodeMapping")
        coords = nt.nodes.new("ShaderNodeTexCoord")
        mapping.inputs["Rotation"].default_value[2] = math.radians(rotation_deg)
        nt.links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    else:
        env = nt.nodes.new("ShaderNodeTexSky")
        # Blender renamed its physical sky models; select from this build's API.
        sky_types = env.bl_rna.properties["sky_type"].enum_items.keys()
        env.sky_type = "NISHITA" if "NISHITA" in sky_types else "MULTIPLE_SCATTERING"
        env.sun_elevation = math.radians(35)
        env.sun_rotation = math.radians(rotation_deg)
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return world
