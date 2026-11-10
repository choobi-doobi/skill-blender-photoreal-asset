"""Rule 12 check for game-ready assets: validate the LODs, collision, UVs and the .glb, and render the LOD
turntable sheet. Agents may NOT edit this file. Exit code 0 = every check passes.

    python game_check.py --blend final\\asset.blend --glb export\\Barrel.glb --name Barrel --tris 4000
        --out renders\\game_check_v1 [--asset asset.json] [--tex 2048] [--padding 8] [--ratios 1,0.5,0.2,0.05]
        [--tolerance 0.10] [--no-render]

Expects objects <name>_LOD0..3, <name>_high (the high-poly bake source) and one collision mesh named
<name>-convcolonly (Godot 4 import suffix: invisible convex collider). Writes <out>\\game_check.md (pass/fail
per check), <out>\\lods_turntable.jpg (each LOD from 4 angles, tri counts labelled) and <out>\\game_data.json.
"""
import argparse
import io
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from scipy.ndimage import distance_transform_edt as _edt
except ImportError:
    def _edt(mask):
        """Exact 2D Euclidean distance transform fallback when scipy is not installed."""
        b = np.asarray(mask, dtype=bool)
        h, w = b.shape
        if b.all():
            return np.full((h, w), np.inf, dtype=np.float64)
        inf = h + w + 1
        g = np.where(b, inf, 0).astype(np.int64)
        for y in range(1, h):
            g[y] = np.minimum(g[y], g[y - 1] + 1)
        for y in range(h - 2, -1, -1):
            g[y] = np.minimum(g[y], g[y + 1] + 1)
        f = g * g
        xs = np.arange(w, dtype=np.int64)
        dx2 = (xs[:, None] - xs[None, :]) ** 2
        out = np.empty((h, w), dtype=np.float64)
        step = max(1, (16 * 1024 * 1024) // max(w * w * 8, 1))
        for y0 in range(0, h, step):
            y1 = min(h, y0 + step)
            out[y0:y1] = np.sqrt((f[y0:y1, None, :] + dx2[None, :, :]).min(axis=2))
        return out

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assetcfg  # noqa: E402
from run import gpu_run  # noqa: E402


def read_glb(path):
    data = open(path, "rb").read()
    magic, _, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a .glb")
    off, js, binary = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<I4s", data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == b"JSON":
            js = json.loads(chunk)
        elif ctype == b"BIN\x00":
            binary = chunk
    return js, binary


def raster(tris_px, size, offset=(0, 0)):
    im = Image.new("1", size, 0)
    d = ImageDraw.Draw(im)
    ox, oy = offset
    for t in tris_px:
        d.polygon([(x - ox, y - oy) for x, y in t], fill=1, outline=1)
    return np.array(im, bool)


def uv_checks(npz_path, tex, padding):
    z = np.load(npz_path)
    uv, island, area_w = z["uv"].astype(np.float64), z["island"], z["area"].astype(np.float64)
    px = uv * tex
    px[..., 1] = tex - px[..., 1]
    oob = int(np.any((uv < -1e-4) | (uv > 1 + 1e-4), axis=(1, 2)).sum())
    a = px[:, 1] - px[:, 0]
    b = px[:, 2] - px[:, 0]
    area_px = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
    count = np.zeros((tex, tex), np.uint8)
    folded, crops = [], {}
    ids = [i for i in np.unique(island) if i >= 0]
    for i in ids:
        t = px[island == i]
        m = raster(t, (tex, tex))
        count += m
        if area_px[island == i].sum() > m.sum() * 1.02 + 50:  # more UV area than texels covered = it folds over itself
            folded.append(int(i))
        x0, y0 = np.floor(t.reshape(-1, 2).min(0)).astype(int) - padding - 2
        x1, y1 = np.ceil(t.reshape(-1, 2).max(0)).astype(int) + padding + 2
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, tex), min(y1, tex)
        if x1 > x0 and y1 > y0:
            crops[i] = ((x0, y0, x1, y1), m[y0:y1, x0:x1].copy())  # reuse this raster: PIL edges shift when re-drawn offset
    overlap = int((count > 1).sum())
    min_gap = math.inf
    for (x0, y0, x1, y1), mine in crops.values():
        others = (count[y0:y1, x0:x1].astype(int) - mine) > 0
        if others.any():
            min_gap = min(min_gap, float(_edt(~mine)[others].min()) - 1)
    ok = area_w > 1e-10
    density = np.sqrt(area_px[ok] / area_w[ok])  # texels per metre
    w = area_w[ok] / area_w[ok].sum()
    order = np.argsort(density)
    cdf = np.cumsum(w[order])
    p10, p50, p90 = (float(density[order][np.searchsorted(cdf, q)]) for q in (0.1, 0.5, 0.9))
    return dict(islands=len(ids), out_of_range_tris=oob, overlap_texels=overlap, folded_islands=folded,
                min_gap_px=None if min_gap == math.inf else round(min_gap, 1),
                density_p10=round(p10), density_p50=round(p50), density_p90=round(p90),
                density_spread=round(p90 / max(p10, 1e-9), 2))


def glb_checks(path, name, tex):
    js, binary = read_glb(path)
    nodes = [n.get("name", "") for n in js.get("nodes", [])]
    imgs = []
    for im in js.get("images", []):
        size = None
        if "bufferView" in im:
            bv = js["bufferViews"][im["bufferView"]]
            off = bv.get("byteOffset", 0)
            size = list(Image.open(io.BytesIO(binary[off:off + bv["byteLength"]])).size)
        imgs.append(dict(name=im.get("name"), embedded="bufferView" in im and "uri" not in im, size=size))
    tex_src = [t.get("source") for t in js.get("textures", [])]
    mats = []
    for m in js.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        src = {k: tex_src[v["index"]] for k, v in (("base", pbr.get("baseColorTexture")), ("normal", m.get("normalTexture")),
                                                   ("mr", pbr.get("metallicRoughnessTexture")),
                                                   ("ao", m.get("occlusionTexture"))) if v}
        mats.append(dict(name=m.get("name"), maps=src))
    lod_mats = {}
    for n in js.get("nodes", []):
        if n.get("name", "").startswith(f"{name}_LOD") and "mesh" in n:
            prims = js["meshes"][n["mesh"]]["primitives"]
            lod_mats[n["name"]] = sorted({p.get("material", -1) for p in prims})
    return dict(nodes=nodes, images=imgs, materials=mats, lod_materials=lod_mats)


def turntable_sheet(data, out, tris):
    rows = [(k, v) for k, v in sorted(data.get("turntable", {}).items())]
    if not rows:
        return None
    cell = Image.open(rows[0][1][0]).size[0]
    lab = 40
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    sheet = Image.new("RGB", (cell * len(rows[0][1]), (cell + lab) * len(rows)), "white")
    d = ImageDraw.Draw(sheet)
    for r, (lod, files) in enumerate(rows):
        n = data["lods"][lod]["tris"]
        d.text((10, r * (cell + lab) + 8), f"{lod}: {n:,} tris (target {tris[lod]:,})", fill="black", font=font)
        for c, f in enumerate(files):
            sheet.paste(Image.open(f).convert("RGB"), (c * cell, r * (cell + lab) + lab))
    path = os.path.join(out, "lods_turntable.jpg")
    sheet.save(path, quality=90)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--glb", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--tris", type=int, required=True, help="LOD0 target triangle count")
    p.add_argument("--out", required=True)
    p.add_argument("--asset", default="")
    p.add_argument("--tex", type=int, default=2048)
    p.add_argument("--padding", type=int, default=8)
    p.add_argument("--ratios", default="1,0.5,0.2,0.05")
    p.add_argument("--tolerance", type=float, default=0.10)
    p.add_argument("--no-render", action="store_true")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    hdri = assetcfg.load(a.asset)["hdri"] if a.asset else assetcfg.DEFAULT_HDRI
    cmd = ["blender", "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.join(HERE, "game_check_bl.py"), "--",
           "--blend", os.path.abspath(a.blend), "--name", a.name, "--out", out, "--hdri", hdri]
    if a.no_render:
        cmd.append("--no-render")
    code = gpu_run(cmd, os.path.join(out, "blender.log"), timeout=1800)
    if code != 0:
        print(f"blender exit {code}; see {os.path.join(out, 'blender.log')}")
        return code
    data = json.load(open(os.path.join(out, "game_data.json"), encoding="utf-8"))
    ratios = [float(r) for r in a.ratios.split(",")]
    tris = {f"LOD{i}": round(a.tris * r) for i, r in enumerate(ratios)}
    checks = []

    def check(name, ok, detail):
        checks.append((name, bool(ok), detail))

    lods = data["lods"]
    check("LOD objects", len(lods) == 4, f"found {sorted(lods)}; expected {a.name}_LOD0..LOD3")
    check("high-poly mesh", data["high"] and lods.get("LOD0") and data["high"]["tris"] > lods["LOD0"]["tris"],
          f"{a.name}_high: {data['high']['tris']:,} tris" if data["high"] else f"no {a.name}_high")
    mats0 = lods.get("LOD0", {}).get("materials")
    uvs0 = (lods.get("LOD0", {}).get("uv") or {}).get("uv_layers")
    for lod, d in sorted(lods.items()):
        t = tris[lod]
        check(f"{lod} tris", abs(d["tris"] - t) <= a.tolerance * t, f"{d['tris']:,} vs target {t:,} (±{a.tolerance:.0%})")
        check(f"{lod} n-gons", d["ngons"] == 0, f"{d['ngons']} faces with more than 4 sides")
        nm = d["boundary_edges"] + d["multi_face_edges"] + d["wire_edges"]
        check(f"{lod} manifold", nm == 0, f"{d['boundary_edges']} open, {d['multi_face_edges']} shared by 3+ faces, "
              f"{d['wire_edges']} wire edges")
        check(f"{lod} normals", d["inconsistent_edges"] == 0 and d["signed_volume"] > 0,
              f"{d['inconsistent_edges']} edges with flipped neighbours; volume {d['signed_volume']:.4f} m³ "
              "(negative = normals point in)")
        size = max(h - l for l, h in zip(d["bbox_lo"], d["bbox_hi"]))
        tol = max(0.001, 0.005 * size)
        cx, cy = ((d["bbox_lo"][i] + d["bbox_hi"][i]) / 2 for i in (0, 1))
        check(f"{lod} origin at base centre", abs(d["bbox_lo"][2]) <= tol and abs(cx) <= tol and abs(cy) <= tol,
              f"base z {d['bbox_lo'][2]:+.4f}, centre x {cx:+.4f} y {cy:+.4f} (tolerance {tol:.4f} m)")
        rot_ok = all(abs(r) < 1e-4 for r in d["rotation"]) and all(abs(s - 1) < 1e-4 for s in d["scale"])
        check(f"{lod} transforms applied", rot_ok and all(abs(v) < 1e-4 for v in d["location"]),
              f"location {d['location']}, rotation {d['rotation']}, scale {d['scale']}")
        if lod != "LOD0":
            check(f"{lod} same material and UVs as LOD0", d["materials"] == mats0 and (d.get("uv") or {}).get("uv_layers") == uvs0,
                  f"materials {d['materials']}, UV maps {(d.get('uv') or {}).get('uv_layers')}")
        npz = os.path.join(out, f"uv_{lod}.npz")
        if not d.get("uv"):
            check(f"{lod} UVs", False, "no UV map")
            continue
        u = uv_checks(npz, a.tex, a.padding)
        d["uv_checks"] = u
        check(f"{lod} UV overlaps", u["overlap_texels"] == 0 and not u["folded_islands"] and u["out_of_range_tris"] == 0,
              f"{u['overlap_texels']} texels shared by islands, folded islands {u['folded_islands']}, "
              f"{u['out_of_range_tris']} triangles outside 0-1")
        check(f"{lod} UV padding", u["min_gap_px"] is None or u["min_gap_px"] >= a.padding - 1,
              (f"smallest gap between islands {u['min_gap_px']} px at {a.tex} (need {a.padding})" if u["min_gap_px"] is not None
               else f"{u['islands']} islands, none within {a.padding} px of another at {a.tex}"))
        if lod == "LOD0":
            check("LOD0 texel density", u["density_spread"] <= 1.5,
                  f"{u['density_p50']} px/m median, p90/p10 = {u['density_spread']} (≤ 1.5)")
    c = data["collision"]
    check("collision mesh", c and c["object"] == f"{a.name}-convcolonly" and c.get("convex")
          and c["boundary_edges"] + c["multi_face_edges"] + c["wire_edges"] == 0,
          (f"{c['object']}: {c['verts']} verts, convex {c.get('convex')} (worst {c.get('convex_excess', 0) * 1000:.2f} mm "
           f"outside a face), open edges {c['boundary_edges']}, edges shared by 3+ faces {c['multi_face_edges']}"
           if c else f"no {a.name}-convcolonly"))
    if os.path.exists(a.glb):
        g = glb_checks(a.glb, a.name, a.tex)
        data["glb"] = g
        want = [f"{a.name}_LOD{i}" for i in range(4)] + [f"{a.name}-convcolonly"]
        check("glb nodes", all(w in g["nodes"] for w in want), f"nodes {g['nodes']}")
        check("glb textures embedded", g["images"] and all(i["embedded"] for i in g["images"]),
              f"{len(g['images'])} images: " + ", ".join(f"{i['name']} {i['size']}" for i in g["images"]))
        check(f"glb textures {a.tex}px", g["images"] and all(i["size"] == [a.tex, a.tex] for i in g["images"]),
              ", ".join(f"{i['name']} {i['size']}" for i in g["images"]))
        m = g["materials"][0]["maps"] if g["materials"] else {}
        check("glb maps: base colour, normal, ORM", {"base", "normal", "mr", "ao"} <= set(m) and m.get("mr") == m.get("ao"),
              f"material maps {m} (ORM = occlusion and metallicRoughness use the same image)")
        check("glb one material across LODs", len({tuple(v) for v in g["lod_materials"].values()}) == 1,
              f"{g['lod_materials']}")
    else:
        check("glb exported", False, f"missing {a.glb}")
    sheet = turntable_sheet(data, out, tris) if not a.no_render else None
    with open(os.path.join(out, "game_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    passed = sum(ok for _, ok, _ in checks)
    lines = [f"# Game check: {a.name}", "", f"**{passed} / {len(checks)} checks pass.**"
             + (f" Turntable: `{os.path.basename(sheet)}`." if sheet else ""), "",
             "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {n} | {'PASS' if ok else '**FAIL**'} | {d} |" for n, ok, d in checks]
    with open(os.path.join(out, "game_check.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for n, ok, d in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {n}: {d}")
    print(f"[game_check] {passed}/{len(checks)} pass -> {os.path.join(out, 'game_check.md')}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
