"""Load a project's asset.json, the one config the photoreal-asset scripts share (harness, photo check, sheets).

Paths in asset.json are relative to its own folder (the project root). Pure json: works in Blender's Python too.
"""
import json
import os

# Empty means the harness supplies a procedural daylight sky.
DEFAULT_HDRI = ""
DEFAULTS = dict(
    collection_prefix="AS_", hdri=DEFAULT_HDRI, hdri_strength=1.0, hdri_rotation_deg=0.0,
    ground="asphalt", ground_z=-0.01,
    final=dict(res=[1920, 1280], samples=256), preview=dict(res=[960, 640], samples=64),
    layout="research/layout.py", ref_dir="ref", owner_refs={}, overall_refs=[], skip_zone_regex="",
    subject="a real-world object", render_as="a photograph", photo_kind="real photographs of the same kind of object",
    design_note="", scope_note="", critic_goal="",
    critic=dict(runner="subagent", model="inherit", effort="low", max_refs=6, chunk=7, parallel=4),
)


def load(path):
    path = os.path.abspath(path)
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    cfg = {**DEFAULTS, **raw}
    cfg["critic"] = {**DEFAULTS["critic"], **raw.get("critic", {})}
    cfg["root"], cfg["path"] = os.path.dirname(path), path
    for k in ("layout", "ref_dir", "hdri"):
        if cfg.get(k) and not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(cfg["root"], cfg[k])
    # name: (camera location, look-at target, focal length mm); sensor width 36 mm, horizontal fit
    cfg["cameras"] = {n: (tuple(v[0]), tuple(v[1]), float(v[2])) for n, v in raw["cameras"].items()}
    return cfg
