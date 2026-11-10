# Fixed sections: fill the {placeholders} and copy into BRIEF.md verbatim

## Scene conventions and locked cameras

Metres, real-world scale, Z up, ground at z = 0. The harness supplies the ground, the sky and the sun (see
`asset.json`). Put everything in top-level collections whose names start with `{PREFIX}` (the harness appends
only those). The judged cameras are fixed:

| Camera | Location → target, lens | Must show |
|---|---|---|
{CAMERA_ROWS}

## Rules

1. Build with the installed Blender's Python, headless:
   `blender --background --factory-startup --python-exit-code 1 --python build.py`
   Use the executable configured by `PHOTOREAL_BLENDER` if set, with the current shell's path quoting.
   Check its version before choosing `bpy` APIs. Your script must regenerate your `.blend` from scratch.
2. No downloaded or purchased 3D models, no add-ons beyond what ships with Blender. Image textures may come
   from a user-provided library (copy what you use into your own `tex/` folder), be generated
   (numpy/PIL/Blender bake), or be CC0 downloads from Poly Haven / ambientCG saved in your own `tex/` folder
   and listed in `NOTES.md` with URL + license. Never send a
   person's name or email to any site or service, including in a User-Agent.
3. The photos in `ref/` are your only references: don't look up other images or reference material.
4. No real brand names, logos or trademarks anywhere; use the invented design in this brief.
5. No lights except physical fixtures in the scene. No studio or fill lights, no world changes. Lighting
   belongs to the harness.
6. Pack all images into the `.blend` before saving (`bpy.ops.file.pack_all()`).
7. Only write inside your own round folder. Read only this brief, `ref/`, `research/`, `asset.json`, the
   harness scripts and your own round's folder.
8. Render only through the harness runner (one render at a time). Never start Cycles another way.
9. Iterate: render previews, compare with the references side by side (the host's image viewer on `sheet.jpg` and the
   PNGs), write down what looks fake, fix, repeat. At least 3 iterations; stop when another iteration
   wouldn't visibly improve realism.
10. Fix what you can see. Every flaw in your work gets fixed before you finish; there is no "known issues"
    list. Your notes may only name problems you can't fix from your own folder (say whose they are).
11. Prove it against the photos (see your `TASK.md` for the command and when to stop). Where this brief's
    numbers, positions or angles and the photos disagree, the photos win; move connected parts with them and
    write the conflict in `NOTES.md`.

## Harness (locked; don't edit the scripts or `asset.json`)

```sh
python "{SCRIPTS}/run.py" --asset "{PROJECT}/asset.json" --parts part.blend --out renders/v1 --preview
```

- `--cams hero,detail` renders a subset of the locked cameras.
- `--custom "fx,fy,fz:tx,ty,tz:lens"` adds your own inspection camera (location : target : mm), repeatable.
- `--preview` = the asset's preview size and samples. Judging renders use the final settings; the photo check
  (rule 11) and the coordinator render those.
- Writes `<out>/<cam>.png`, `<out>/sheet.jpg` and `<out>/render.log`. View `sheet.jpg` with the host's image viewer after every render.
