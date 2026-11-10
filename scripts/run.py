"""Render part files in the locked evaluation scene, optionally queued, then make sheet.jpg.

    python run.py --asset asset.json --parts part.blend [more.blend ...] --out renders/v1 [--preview]
                  [--cams hero,ui] [--custom "fx,fy,fz:tx,ty,tz:lens"] [--save]

Use --preview while iterating. Judging renders use the asset's final settings (the default).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assetcfg  # noqa: E402

# Resolve Blender through PATH unless the user supplies an executable.
BLENDER = os.environ.get("PHOTOREAL_BLENDER") or "blender"
# Optional external queue integration; no queue package is required.
GPU_TOOLS = os.environ.get("PHOTOREAL_GPU_TOOLS", "")


def gpu_run(cmd, log, timeout):
    """One render at a time on the machine-wide GPU queue (gpu_slot.py); plain subprocess if it's missing."""
    cmd = [BLENDER if cmd[0] == "blender" else cmd[0], *cmd[1:]]
    if GPU_TOOLS and os.path.exists(os.path.join(GPU_TOOLS, "gpu_slot.py")):
        sys.path.insert(0, GPU_TOOLS)
        from gpu_slot import run
        return run(cmd, log, slots=1, timeout=timeout)
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        try:
            return subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            return 124
        except FileNotFoundError:
            f.write("Blender executable not found. Put blender on PATH or set PHOTOREAL_BLENDER.\n")
            return 127


def sheet(out_dir, cams):
    from PIL import Image, ImageDraw
    names = [c for c in cams if os.path.exists(os.path.join(out_dir, c + ".png"))]
    names += sorted(f[:-4] for f in os.listdir(out_dir) if f.startswith("custom") and f.endswith(".png"))
    if not names:
        return None
    ims = [Image.open(os.path.join(out_dir, n + ".png")).convert("RGB") for n in names]
    w = 960
    h = round(w * ims[0].height / ims[0].width)
    cols = 2 if len(ims) > 1 else 1
    rows = (len(ims) + cols - 1) // cols
    sh = Image.new("RGB", (w * cols, h * rows), "black")
    for i, (name, im) in enumerate(zip(names, ims)):
        x, y = (i % cols) * w, (i // cols) * h
        sh.paste(im.resize((w, h)), (x, y))
        ImageDraw.Draw(sh).text((x + 8, y + 8), name, fill="yellow")
    path = os.path.join(out_dir, "sheet.jpg")
    sh.save(path, quality=88)
    return path


def main():
    argv = sys.argv[1:]
    cfg = assetcfg.load(argv[argv.index("--asset") + 1])
    out = argv[argv.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "render.log")
    cmd = ["blender", "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.join(HERE, "render.py"), "--", *argv]
    t = time.time()
    # Oversubscribed Cycles jobs hang instead of failing; the timeout turns a hang into an error.
    code = gpu_run(cmd, log, timeout=600 if "--preview" in argv else 1800)
    if code == 124:
        print("render timed out (shared GPU busy or a hung job); just retry")
    print(f"blender exit {code} in {time.time() - t:.0f}s, log {log}")
    if code != 0:
        with open(log, encoding="utf-8", errors="replace") as f:
            print("".join(f.readlines()[-30:]))
        return code
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("[harness]"):
                print(line.rstrip())
    print("sheet:", sheet(out, list(cfg["cameras"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
