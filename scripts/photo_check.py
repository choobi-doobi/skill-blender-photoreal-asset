"""Rule 11 inspection: prove the scene against the photos. Agents may NOT edit this file.

Host-native subagent workflow (default, critic.runner = "subagent"):
  1. Prepare renders, zone crops, and critic job prompts:
     python photo_check.py --asset asset.json --parts final\\asset.blend --out renders\\check_v1
  2. For each job in <out>\\critic_jobs.json, invoke a fresh read-only critic with the prompt in
     `prompt_file` and save its JSON array reply to `response_file` (<out>\\critic_logs\\<name>.json).
  3. Merge the critic replies into <out>\\critique.md and <out>\\critique.json:
     python photo_check.py --asset asset.json --out renders\\check_v1 --merge-critic

Severity: 3 = gives the render away at the full judged frame, 2 = noticeable on a close look at the judged frame,
1 = only visible in the enlarged crop.

Options:
  --from DIR        reuse existing <cam>.png files instead of rendering
  --no-critic       stop after writing crops (do not prepare or run critic jobs)
  --prepare-critic  stop after writing crops and <out>\\critic_jobs.json + critic_prompts\\*.md
  --merge-critic    merge <out>\\critic_logs\\*.json from prepared jobs into critique.md / critique.json
  --groups LIST     comma list of owner collections and/or "overall"
  --runner MODE     override critic.runner ("subagent" or "claude")
"""
import argparse
import concurrent.futures as cf
import glob
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assetcfg  # noqa: E402

PROMPT = """{goal} You did not \
make the render and have no stake in it.

Use `{read_tool}` to open and inspect every image listed below. Then compare each numbered render crop with the \
reference photos, which are {photo_kind}.

Render crops. In each crop image the left half is the render at the judged exposure. When there is a right \
half, it is the same crop brightened for inspection only.
{crops}

Reference photos:
{refs}

For each crop, list up to 3 differences between the render and how the same kind of object looks in the \
photos, worst first. Judge shape and proportion; how parts sit, hang and rest on each other; edge rounding and \
wall thickness; surface and material response; wear and dirt; scale. Judge brightness from the left half only. \
Use the brightened half to see shape and detail.
{notes}
Severity: 3 = gives the render away at the full judged frame; 2 = noticeable on a close look at the judged \
frame; 1 = only visible in the enlarged crop. If a crop already matches the photos, give no items for it.

Answer with a JSON array only, no other text (use `[]` if every crop matches):
[{{"zone": "{example}", "severity": 3, "difference": "...", "photo_shows": "... (refNN)", "render_shows": "..."}}]
"""


def load_layout(cfg):
    spec = importlib.util.spec_from_file_location("layout", cfg["layout"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bounds(it):
    """Axis-aligned bounds of a layout item: box(lo, hi) | cyl(c, r, z0, z1) | disc(c, r, depth, axis) |
    hoop(x0, x1, y, z0, z1, r) | tube(pts, r)."""
    k = it.get("kind", "box")
    if k == "box":
        return it["lo"], it["hi"]
    if k == "cyl":
        (x, y), r = it["c"], it["r"]
        return (x - r, y - r, it["z0"]), (x + r, y + r, it["z1"])
    if k == "disc":
        x, y, z = it["c"]
        r, d = it["r"], it["depth"] / 2
        ext = {"x": (d, r, r), "y": (r, d, r), "z": (r, r, d)}[it["axis"]]
        return (x - ext[0], y - ext[1], z - ext[2]), (x + ext[0], y + ext[1], z + ext[2])
    if k == "hoop":
        r = it["r"]
        return (it["x0"] - r, it["y"] - r, it["z0"]), (it["x1"] + r, it["y"] + r, it["z1"])
    if k == "tube":
        xs, ys, zs = zip(*it["pts"])
        r = it["r"]
        return (min(xs) - r, min(ys) - r, min(zs) - r), (max(xs) + r, max(ys) + r, max(zs) + r)
    raise ValueError(k)


def item_bounds(layout, it):
    return layout.bounds(it) if hasattr(layout, "bounds") else bounds(it)


def frame_size(cfg):
    return tuple(cfg["final"]["res"])


def cam_basis(loc, target):
    loc, target = np.array(loc, float), np.array(target, float)
    d = target - loc
    d /= np.linalg.norm(d)
    right = np.cross(d, (0, 0, 1))
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    return loc, right, up, d


def project(cfg, pts, cam):
    W, H = frame_size(cfg)
    loc, target, lens = cfg["cameras"][cam]
    o, r, u, d = cam_basis(loc, target)
    k = lens / 36.0 * W
    out = []
    for p in pts:
        v = np.array(p, float) - o
        z = v @ d
        if z < 0.05:
            return None  # part of the zone is behind the camera
        out.append((W / 2 + k * (v @ r) / z, H / 2 - k * (v @ u) / z))
    return out


def best_view(cfg, lo, hi):
    """(camera, clipped pixel box) of the camera that sees a 3D box biggest and most whole, or None."""
    W, H = frame_size(cfg)
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    best = None
    for cam in cfg["cameras"]:
        pts = project(cfg, corners, cam)
        if pts is None:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if cx1 - cx0 < 1 or cy1 - cy0 < 1:
            continue
        inside = (cx1 - cx0) * (cy1 - cy0) / max((x1 - x0) * (y1 - y0), 1)
        short = min(cx1 - cx0, cy1 - cy0)
        score = short * (1.0 if inside >= 0.5 else 0.3)
        if short >= 14 and (best is None or score > best[0]):
            best = (score, cam, (cx0, cy0, cx1, cy1))
    return best[1:] if best else None


def zones(cfg, layout):
    skip = re.compile(cfg["skip_zone_regex"]) if cfg["skip_zone_regex"] else None
    keep = []
    for it in layout.ITEMS:
        note = it.get("note", "")
        if re.match(r"^(See|As) [A-Z]\d\d", note) or it.get("inspect") is False or (skip and skip.search(it["id"])):
            continue  # identical copies of a zone already inspected
        view = best_view(cfg, *item_bounds(layout, it))
        if view:
            keep.append(dict(id=it["id"], owner=it["owner"], name=it["name"],
                             note=note, cam=view[0], box=list(view[1])))
    return keep


def to_lin(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def to_srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def crop_sheet(cfg, z, frames, out_dir, font):
    W, H = frame_size(cfg)
    x0, y0, x1, y1 = z["box"]
    pad_x, pad_y = (x1 - x0) * 0.3 + 24, (y1 - y0) * 0.3 + 24
    x0, y0, x1, y1 = max(0, x0 - pad_x), max(0, y0 - pad_y), min(W, x1 + pad_x), min(H, y1 + pad_y)
    if x1 - x0 < 200:
        c = (x0 + x1) / 2
        x0, x1 = max(0, c - 100), min(W, c + 100)
    if y1 - y0 < 200:
        c = (y0 + y1) / 2
        y0, y1 = max(0, c - 100), min(H, c + 100)
    im = frames[z["cam"]].crop((int(x0), int(y0), int(x1), int(y1)))
    a = np.asarray(im).astype(np.float32) / 255
    lin = to_lin(a)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    gain = float(np.clip(0.18 / max(np.median(lum), 1e-4), 1.0, 8.0))
    panels = [im]
    if gain >= 1.4:
        panels.append(Image.fromarray((to_srgb(lin * gain) * 255 + 0.5).astype(np.uint8)))
    scale = min(1100 / max(im.size), 3.0) if max(im.size) < 1100 else 1100 / max(im.size)
    panels = [p.resize((max(1, round(p.width * scale)), max(1, round(p.height * scale))), Image.LANCZOS) for p in panels]
    pw, ph = panels[0].size
    sheet = Image.new("RGB", (pw * len(panels) + 8 * (len(panels) - 1), ph + 30), (20, 20, 20))
    for i, p in enumerate(panels):
        sheet.paste(p, (i * (pw + 8), 30))
    label = f"{z['id']} {z['name']} | {z['cam']} camera | left: as rendered"
    if len(panels) > 1:
        label += f" | right: inspection +{math.log2(gain):.1f} stops"
    ImageDraw.Draw(sheet).text((6, 7), label, fill=(255, 220, 80), font=font)
    path = os.path.join(out_dir, f"{z['id']}.jpg")
    sheet.save(path, quality=88)
    z["crop"] = path
    z["stops"] = round(math.log2(gain), 1) if len(panels) > 1 else 0.0


def ref_paths(cfg, ids):
    out = []
    for rid in ids:
        hits = sorted(h for ext in ("jpg", "jpeg", "png")
                      for h in glob.glob(os.path.join(cfg["ref_dir"], f"{rid}_*.{ext}")))
        if hits and hits[0] not in out:
            out.append(hits[0])
    return out[:cfg["critic"]["max_refs"]]


def critic_jobs(cfg, zs, frames_dir):
    jobs = []
    chunk_n = cfg["critic"]["chunk"]
    owners = list(cfg["owner_refs"]) + sorted({z["owner"] for z in zs} - set(cfg["owner_refs"]))
    for owner in owners:
        group = [z for z in zs if z["owner"] == owner]
        for i in range(0, len(group), chunk_n):
            chunk = group[i:i + chunk_n]
            note_refs = [r for z in chunk for r in re.findall(r"ref\d\d", z["note"])]
            jobs.append((owner, f"{owner}-{i // chunk_n + 1}", chunk,
                         ref_paths(cfg, note_refs + cfg["owner_refs"].get(owner, []))))
    overall = [dict(id=f"ALL-{c}", name=f"whole {c} frame (lighting, scale, the scene as a whole)", note="",
                    cam=c, crop=os.path.join(frames_dir, c + ".png")) for c in cfg["cameras"]]
    overall_refs = cfg["overall_refs"] or [r for refs in cfg["owner_refs"].values() for r in refs[:1]]
    jobs.append(("overall", "overall", overall, ref_paths(cfg, overall_refs)))
    return jobs


def format_prompt(cfg, job, read_tool="image/file reading tools"):
    _, _, chunk, refs = job
    crops = "\n".join(f"{i + 1}. {z['id']} {z['name']} ({z['cam']} camera). Brief: \"{z['note'][:260]}\". "
                      f"File: {z['crop']}" for i, z in enumerate(chunk))
    notes = "".join(f"\n{n}\n" for n in (cfg["design_note"], cfg["scope_note"]) if n)
    goal = cfg["critic_goal"] or (f"You are a photo-realism checker. A 3D render of {cfg['subject']} has to pass "
                                  "as a photograph.")
    return PROMPT.format(goal=goal, read_tool=read_tool, photo_kind=cfg["photo_kind"],
                         example=chunk[0]["id"], crops=crops, notes=notes,
                         refs="\n".join(f"- {r}" for r in refs) or "- (none)")


def parse_critic_items(raw_text):
    text = raw_text.strip()
    if not text:
        raise ValueError("empty critic response")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("result"), str):
            text = parsed["result"]
    except json.JSONDecodeError:
        pass
    start = text.index("[")
    end = text.rindex("]") + 1
    items = json.loads(text[start:end])
    if not isinstance(items, list):
        raise ValueError("parsed JSON is not a list")
    return items


def prepare_subagent_jobs(cfg, jobs, out):
    prompts_dir = os.path.join(out, "critic_prompts")
    logs_dir = os.path.join(out, "critic_logs")
    os.makedirs(prompts_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    manifest = []
    for job in jobs:
        owner, name, chunk, refs = job
        prompt_path = os.path.join(prompts_dir, f"{name}.md")
        resp_path = os.path.join(logs_dir, f"{name}.json")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(format_prompt(cfg, job))
        manifest.append(dict(
            owner=owner,
            name=name,
            prompt_file=prompt_path,
            response_file=resp_path,
            zones=[z["id"] for z in chunk],
            crops=[z["crop"] for z in chunk],
            refs=refs,
        ))
    manifest_path = os.path.join(out, "critic_jobs.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[photo_check] prepared {len(manifest)} critic job(s) -> {manifest_path}")
    for m in manifest:
        print(f"  - {m['name']}: prompt={m['prompt_file']} -> save JSON reply to {m['response_file']}")
    print("[photo_check] NEXT: invoke one fresh read-only critic per job (passing its prompt_file "
          "contents), write each JSON array reply to its response_file, then run:")
    print(f'  python "{os.path.abspath(__file__)}" --asset "{cfg["path"]}" --out "{out}" --merge-critic')
    return 0


def merge_subagent_jobs(cfg, out, groups_filter):
    zones_path = os.path.join(out, "zones.json")
    manifest_path = os.path.join(out, "critic_jobs.json")
    if not os.path.exists(zones_path) or not os.path.exists(manifest_path):
        print(f"[photo_check] missing {zones_path} or {manifest_path}; run without --merge-critic first")
        return 1
    with open(zones_path, encoding="utf-8") as f:
        zs = json.load(f)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if groups_filter:
        allow = set(groups_filter.split(","))
        manifest = [m for m in manifest if m["owner"] in allow or m["name"] in allow]
    results, errors = [], []
    for m in manifest:
        name = m["name"]
        resp_path = m["response_file"]
        if not os.path.exists(resp_path):
            err = f"critic missing response for {name} ({resp_path})"
            errors.append(err)
            results.append((name, []))
            print(f"[photo_check] {err}")
            continue
        with open(resp_path, encoding="utf-8") as f:
            raw = f.read()
        try:
            items = parse_critic_items(raw)
            results.append((name, items))
            print(f"[photo_check] critic {name}: {len(items)} items")
        except Exception as e:  # noqa: BLE001
            err = f"critic parse failed for {name} ({type(e).__name__}: {e})"
            errors.append(err)
            results.append((name, []))
            print(f"[photo_check] {err}")
    desc = (f"Critic: independent read-only subagents ({cfg['critic'].get('model', 'inherit')}), "
            f"fresh session per group, image/file reading only; {len(zs)} zone crops + {len(cfg['cameras'])} full frames.")
    counts = write_report(cfg, out, zs, results, errors, None, critic_desc=desc)
    print(f"[photo_check] severity 3: {counts[3]}, 2: {counts[2]}, 1: {counts[1]} -> {os.path.join(out, 'critique.md')}")
    return 1 if errors else 0


def run_claude_critic(cfg, job, work_dir, log_dir, out):
    _, name, _, _ = job
    prompt = format_prompt(cfg, job, read_tool="Read")
    c = cfg["critic"]
    cmd = ["claude", "-p", "--effort", c.get("effort", "low"), "--tools", "Read",
           "--allowedTools", "Read", "--add-dir", cfg["root"], "--add-dir", out, "--output-format", "json"]
    if c.get("model") not in ("inherit", "", None):
        cmd += ["--model", c["model"]]
    env = dict(os.environ, CLAUDE_CODE_DISABLE_TERMINAL_TITLE="1")
    err = "timeout"
    for attempt in (1, 2):
        t = time.time()
        try:
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=work_dir,
                               env=env, timeout=900, shell=(os.name == "nt"))
        except subprocess.TimeoutExpired:
            continue
        with open(os.path.join(log_dir, f"{name}.attempt{attempt}.json"), "w", encoding="utf-8") as f:
            f.write(p.stdout or p.stderr)
        try:
            res = json.loads(p.stdout)
            items = parse_critic_items(res.get("result", ""))
            return name, items, res.get("usage", {}), time.time() - t, None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    return name, [], {}, 0, f"critic failed for {name} ({err})"


def write_report(cfg, out, zs, results, errors, secs, critic_desc=None):
    by_id = {z["id"]: z for z in zs}
    items = []
    for name, its in results:
        for it in its:
            if not isinstance(it, dict):
                continue
            zid = str(it.get("zone", "?"))
            z = by_id.get(zid, {})
            items.append(dict(zone=zid, name=z.get("name", "whole frame" if zid.startswith("ALL") else ""),
                              cam=z.get("cam", zid[4:] if zid.startswith("ALL") else ""),
                              crop=os.path.relpath(z["crop"], out) if z.get("crop") else f"{zid[4:]}.png",
                              severity=int(it.get("severity", 1) or 1), difference=it.get("difference", ""),
                              photo_shows=it.get("photo_shows", ""), render_shows=it.get("render_shows", "")))
    items.sort(key=lambda i: (-i["severity"], i["zone"]))
    with open(os.path.join(out, "critique.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in (3, 2, 1)}
    c = cfg["critic"]
    if not critic_desc:
        critic_desc = (f"Critic: Claude {c['model']}, {c.get('effort', 'low')} effort, fresh session per group, "
                       f"Read tool only; {len(zs)} zone crops + {len(cfg['cameras'])} full frames"
                       + (f"; {secs:.0f} s." if secs is not None else "."))
    lines = [f"# Critique: {os.path.basename(os.path.normpath(out))}", "",
             critic_desc,
             f"Severity 3 (gives the render away at judging size): **{counts[3]}** · severity 2 (noticeable on a "
             f"close look): **{counts[2]}** · severity 1 (only in the enlarged crop): **{counts[1]}**.",
             "Fix the worst first, then run the check again.", ""]
    for e in errors:
        lines.append(f"> {e}")
    for s, title in ((3, "Severity 3"), (2, "Severity 2"), (1, "Severity 1")):
        group = [i for i in items if i["severity"] == s]
        if not group:
            continue
        lines += ["", f"## {title}", ""]
        for i in group:
            lines.append(f"- **{i['zone']} {i['name']}** ({i['cam']}, `{i['crop']}`): {i['difference']}  ")
            lines.append(f"  Photo: {i['photo_shows']}  ")
            lines.append(f"  Render: {i['render_shows']}")
    with open(os.path.join(out, "critique.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asset", required=True)
    p.add_argument("--parts", nargs="*", default=[])
    p.add_argument("--out", required=True)
    p.add_argument("--from", dest="src")
    p.add_argument("--no-critic", action="store_true")
    p.add_argument("--prepare-critic", action="store_true")
    p.add_argument("--merge-critic", action="store_true")
    p.add_argument("--groups", default="", help="comma list of owner collections and/or 'overall'")
    p.add_argument("--runner", default="", help="override critic.runner ('subagent' or 'claude')")
    a = p.parse_args()
    cfg = assetcfg.load(a.asset)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    if a.merge_critic:
        return merge_subagent_jobs(cfg, out, a.groups)
    if a.src:
        for c in cfg["cameras"]:
            shutil.copy(os.path.join(a.src, c + ".png"), os.path.join(out, c + ".png"))
    else:
        code = subprocess.call([sys.executable, os.path.join(HERE, "run.py"), "--asset", cfg["path"],
                                "--parts", *a.parts, "--out", out])
        if code != 0:
            return code
    frames = {c: Image.open(os.path.join(out, c + ".png")).convert("RGB") for c in cfg["cameras"]}
    crops_dir = os.path.join(out, "crops")
    os.makedirs(crops_dir, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    zs = zones(cfg, load_layout(cfg))
    for z in zs:
        crop_sheet(cfg, z, frames, crops_dir, font)
    with open(os.path.join(out, "zones.json"), "w", encoding="utf-8") as f:
        json.dump(zs, f, indent=1)
    print(f"[photo_check] {len(zs)} zone crops in {crops_dir}")
    if a.no_critic:
        return 0
    jobs = critic_jobs(cfg, zs, out)
    if a.groups:
        allow = set(a.groups.split(","))
        jobs = [j for j in jobs if j[0] in allow or j[1] in allow]
    runner = a.runner or cfg["critic"].get("runner", "subagent")
    if a.prepare_critic or runner == "subagent":
        return prepare_subagent_jobs(cfg, jobs, out)
    work = os.path.join(os.getcwd(), "critic_runs")
    logs = os.path.join(out, "critic_logs")
    os.makedirs(work, exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    t = time.time()
    results, errors = [], []
    with cf.ThreadPoolExecutor(max_workers=cfg["critic"]["parallel"]) as ex:
        for name, items, usage, secs, err in ex.map(lambda j: run_claude_critic(cfg, j, work, logs, out), jobs):
            results.append((name, items))
            if err:
                errors.append(err)
            print(f"[photo_check] critic {name}: {len(items)} items in {secs:.0f}s" + (f" ({err})" if err else ""))
    counts = write_report(cfg, out, zs, results, errors, time.time() - t)
    print(f"[photo_check] severity 3: {counts[3]}, 2: {counts[2]}, 1: {counts[1]} -> {os.path.join(out, 'critique.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
