"""Comparison sheets for finished rounds: every camera side by side, and close-ups of the focus zones.

    python compare_rounds.py --asset asset.json --rounds rounds\\r1 rounds\\r2 [--labels "R1 ..." "R2 ..."]
        [--focus H01,H03] [--refs "ref32_x.jpg:0.55,0.06,0.86,0.80" ...] --out compare_r1_r2

Reads <round>\\final\\renders\\<cam>.png (the coordinator's judging renders). Writes <out>_all.jpg (rounds x cameras)
and, with --focus, <out>_focus.jpg: each focus zone cropped from the camera that sees it best, as judged and +2
stops. --refs adds a top row of reference crops (file in the asset's ref folder : x0,y0,x1,y1 as fractions).
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assetcfg  # noqa: E402
import photo_check as pc  # noqa: E402


def boost(im, stops=2.0):
    a = np.asarray(im).astype(np.float32) / 255
    return Image.fromarray((pc.to_srgb(pc.to_lin(a) * 2 ** stops) * 255 + 0.5).astype(np.uint8))


def focus_box(cfg, layout, zone_id, pad=0.35):
    it = next(i for i in layout.ITEMS if i["id"] == zone_id)
    cam, (x0, y0, x1, y1) = pc.best_view(cfg, *pc.item_bounds(layout, it))
    W, H = pc.frame_size(cfg)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    return cam, (int(max(0, x0 - px)), int(max(0, y0 - py)), int(min(W, x1 + px)), int(min(H, y1 + py)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asset", required=True)
    p.add_argument("--rounds", nargs="+", required=True)
    p.add_argument("--labels", nargs="*", default=[])
    p.add_argument("--focus", default="")
    p.add_argument("--refs", nargs="*", default=[])
    p.add_argument("--out", required=True)
    a = p.parse_args()
    cfg = assetcfg.load(a.asset)
    labels = a.labels + [os.path.basename(os.path.normpath(r)) for r in a.rounds[len(a.labels):]]
    try:
        font = ImageFont.truetype("arial.ttf", 22)
        small = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = small = ImageFont.load_default()
    cams = list(cfg["cameras"])

    def frame(r, c):
        return Image.open(os.path.join(r, "final", "renders", c + ".png")).convert("RGB")

    # 1. all cameras
    W, H = pc.frame_size(cfg)
    cw, lab = 480, 34
    ch = round(cw * H / W)
    sheet = Image.new("RGB", (cw * len(cams), (ch + lab) * len(a.rounds)), "white")
    d = ImageDraw.Draw(sheet)
    for i, (r, name) in enumerate(zip(a.rounds, labels)):
        y = i * (ch + lab)
        d.text((8, y + 6), name, fill="black", font=font)
        for j, c in enumerate(cams):
            sheet.paste(frame(r, c).resize((cw, ch), Image.LANCZOS), (j * cw, y + lab))
    sheet.save(a.out + "_all.jpg", quality=88)
    print("wrote", a.out + "_all.jpg")
    if not a.focus:
        return 0

    # 2. focus zones, as judged and +2 stops, with an optional row of reference crops on top
    layout = pc.load_layout(cfg)
    cols = []
    for zid in a.focus.split(","):
        cam, box = focus_box(cfg, layout, zid)
        cols += [(f"{zid} ({cam})", cam, box, 0), (f"{zid} +2 stops", cam, box, 2)]
    cw2, ch2 = 360, 450
    rows = ([(None, "Reference photos")] if a.refs else []) + list(zip(a.rounds, labels))
    sheet = Image.new("RGB", (cw2 * len(cols), (ch2 + lab) * len(rows) + lab), "white")
    d = ImageDraw.Draw(sheet)
    for j, col in enumerate(cols):
        d.text((j * cw2 + 8, 6), col[0], fill="black", font=small)
    for i, (r, name) in enumerate(rows):
        y = lab + i * (ch2 + lab)
        d.text((8, y + 6), name, fill="black", font=font)
        for j, (_, cam, box, stops) in enumerate(cols):
            if r is None:
                if j >= len(a.refs):
                    continue
                fname, fr = a.refs[j].rsplit(":", 1)
                ref = Image.open(os.path.join(cfg["ref_dir"], fname)).convert("RGB")
                f = [float(v) for v in fr.split(",")]
                im = ref.crop((int(f[0] * ref.width), int(f[1] * ref.height), int(f[2] * ref.width), int(f[3] * ref.height)))
            else:
                im = frame(r, cam).crop(box)
                if stops:
                    im = boost(im, stops)
            im.thumbnail((cw2, ch2), Image.LANCZOS)
            sheet.paste(im, (j * cw2 + (cw2 - im.width) // 2, y + lab))
    sheet.save(a.out + "_focus.jpg", quality=90)
    print("wrote", a.out + "_focus.jpg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
