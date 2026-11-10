---
name: photoreal-asset
description: >-
  Build photoreal Blender assets from reference photos with one builder and an independent
  photo critic. Optionally prepare baked textures, LODs and collision for Godot or Unreal Engine.
  Use for photoreal props, scenes and reference-driven refinement in Blender. Start another
  refinement round only when the user requests it.
---

# Photoreal asset

Research a brief, run one solo build, compare it with photos, and report the result.
Use the installed Blender and the host's available agent tools; no particular agent provider,
model, Blender installation path or project location is required.

## Setup

- Resolve `{SKILL}` to the directory containing this file and `{SCRIPTS}` to its `scripts/` directory.
  Resolve `{PROJECT}` to the user's chosen project directory. Quote paths in commands.
  Examples use forward slashes, which Python accepts on Windows, macOS and Linux.
- Use Python 3 with `numpy` and `Pillow` (`python -m pip install -r "{SKILL}/requirements.txt"`).
  SciPy is optional and speeds up UV checks. Blender uses its bundled Python for `bpy` scripts.
- Find `blender` on PATH, or set `PHOTOREAL_BLENDER` to the executable's full path, without
  surrounding quotes in the value. Use that same executable for build scripts and the harness.
  Check its version and adapt build code to its supported `bpy` API; do not assume a fixed version.
- Cycles selects an available GPU backend and falls back to CPU. Set `PHOTOREAL_CYCLES_DEVICE`
  to `CPU`, `OPTIX`, `CUDA`, `HIP`, `METAL` or `ONEAPI` to override automatic selection.
  Run renders sequentially. An optional external `gpu_slot.py` queue can be supplied through
  `PHOTOREAL_GPU_TOOLS`; it is not bundled or required.
- Paths in `asset.json` are relative to that file. An empty `hdri` uses a procedural daylight sky;
  otherwise point it at an existing HDRI. Keep the lighting and cameras fixed once building starts.
- Default delivery is an editable `.blend` with packed images and review renders. Add game exports
  only when requested, following [templates/GAME_READY.md](templates/GAME_READY.md).

## Project layout

```text
<project>/
  asset.json          cameras, lighting, collection prefix and critic references
  BRIEF.md            research brief plus the filled RULES.md template
  ref/SOURCES.md      photo provenance; reference images are not shipped
  research/           layout.py, blockout.py, blockout.blend, NOTES.md
  rounds/r01-build/   TASK.md, build.py, NOTES.md, tex/, renders/, final/, DONE.txt
  <Title>.md          rounds table and project log
```

Use an existing asset library if the user provides one. Record source URLs and licenses for
external images and textures. Keep unknown licenses marked as unknown; do not invent ownership
or redistribute reference photos with the deliverable.

## 1. Research

1. Copy [templates/asset.json](templates/asset.json) into the project and adapt the subject,
   `collection_prefix`, sky and ground. Frame a hero, side/front, top three-quarter and close view
   of the hardest part. Set `render_as`, `photo_kind` and `scope_note` for the critic.
2. Fill [templates/TASK_research.md](templates/TASK_research.md): `{ASSET}`, `{PROJECT}`, `{PREFIX}`,
   `{SUBJECT_PLURAL}`, `{SKILL}` and `{SCRIPTS}`. Save it as `research/TASK.md`.
   Run one researcher through the host's agent tools, or perform the research directly.
3. Deliver reference photos with provenance, `BRIEF.md`, `research/layout.py` with one zone per
   part and an owner collection, the blockout, and `owner_refs` / `overall_refs` in `asset.json`.
4. Inspect the blockout renders with the host's image viewer. Adjust cameras until each frames
   its subject, then lock them.

For a supplied design sheet, copy it unchanged into `ref/`, record the supplied provenance
(unknown where unspecified), and make detail crops. Use its views for the judged cameras.
Set `critic_goal` when matching a stylised design is the goal instead of passing as a photograph;
adjust the task wording and any extra deliverables accordingly.

## 2. Build

1. Create `rounds/r01-build/TASK.md` from [templates/TASK_build.md](templates/TASK_build.md).
   Fill `{ROUND}`, `{ASSET}`, `{PROJECT}`, `{ROUND_DIR}`, `{FILE}` and `{SCRIPTS}`.
2. Leave `{GAME_READY}` empty for a Blender-only asset. Otherwise insert the filled
   [templates/GAME_READY.md](templates/GAME_READY.md), selecting Godot, Unreal Engine or both.
3. Give the task to one builder. Use the current model unless the user requests another.
   Keep its session identifier if the host exposes one. One builder owns the geometry;
   independent critics only review it.

## 3. Review every round

1. Render the final scene:
   ```sh
   python "{SCRIPTS}/run.py" --asset "{PROJECT}/asset.json" --parts "{ROUND_DIR}/final/{FILE}.blend" --out "{ROUND_DIR}/final/renders"
   ```
2. Read `NOTES.md` and the last `critique.md`. Inspect full-resolution crops of the difficult
   parts next to the photos, including brightened crops where useful. Severity counts are
   noisy; use the actual visual differences to judge progress.
3. Compare with the previous round when one exists:
   ```sh
   python "{SCRIPTS}/compare_rounds.py" --asset "{PROJECT}/asset.json" --rounds <previous-round> <current-round> --focus <zone-ids> --refs "<photo>:x0,y0,x1,y1" --out "{PROJECT}/compare_rounds"
   ```
   Inspect the resulting `_all.jpg` and `_focus.jpg` sheets. Use the round paths expected by
   `compare_rounds.py --help`.
4. For game exports, run the target-specific validation in `GAME_READY.md`. Do not describe
   an Unreal import as validated by the Godot GLB checker.
5. If supported transcripts are available, optionally run:
   ```sh
   python "{SCRIPTS}/audit_round.py" "{ROUND_DIR}" --root "{PROJECT}"
   ```
   This audit understands Antigravity and Claude Code logs, not every host. Pass `--session`
   for an Antigravity conversation and `--allow` for additional permitted tool directories.
   Its file-path scan recognizes Windows drive paths; review other path styles separately.
   Log roots can be overridden with `PHOTOREAL_ANTIGRAVITY_LOGS` and `PHOTOREAL_CLAUDE_LOGS`.
6. Record the round and report images, improvements, regressions, validation results and one
   recommendation. Report costs only if measured. Stop after the requested round; start
   another refinement only when the user asks. Copy or ingest into an external library only
   when that destination and action are requested.

## 4. Refine on request

1. Get better photos of the named parts from relevant views: seated, empty, side-on and from
   the judging camera's angle. Record provenance in `ref/SOURCES.md`.
2. Put the strongest references first in the owner's `owner_refs` list; each group gets up to six.
3. Copy the previous build scripts, `tex/` and `final/{FILE}.blend` into a new `rounds/rNN-<focus>/`
   folder. Preserve its notes as `NOTES_<previous>.md`, its last check as `renders/<previous>_check/`
   and its final renders as `renders/<previous>_final/`.
4. Fill [templates/TASK_refine.md](templates/TASK_refine.md), including the parts, zone IDs and
   new references. Limit changes to those parts, except severity-3 defects elsewhere. Keep
   the rule that photos win over conflicting positions and angles, including connected parts.
5. Run one builder, review as above, and show the previous and current results beside the photos.

## Agent handoff and independent critique

Use the host's native agent interface rather than assuming a tool name or model alias.
Give the researcher or builder its working directory and the full task file. Keep writes within
the assigned project or round directory. The task ends by writing `DONE.txt`.
If builder delegation is unavailable, build directly while preserving the same task boundaries.

Rule 11's critic must be independent of the builder. `photo_check.py` prepares prompts and a
`critic_jobs.json` manifest. Send each prompt to a fresh reviewer with image/file reading only,
no network or editing tools, then save its JSON reply to the manifest's `response_file` and merge.
Run critics concurrently only when the host supports it, respecting `critic.parallel`.
Use the host's image viewer wherever a prompt refers to image/file reading.

If independent subagents are unavailable, `--runner claude` can use an installed, authenticated
Claude Code CLI. Otherwise deliver the renders and prepared review jobs, and report independent
critique as incomplete. Do not substitute the builder's own review and call it independent.

## Checks

| Script | Purpose |
|---|---|
| `run.py` / `render.py` | Render prefix-matching collections in the locked Cycles scene; write camera PNGs and `sheet.jpg`. |
| `photo_check.py` | Crop layout zones, prepare independent critic jobs and merge JSON responses into `critique.md`. `--from` reuses renders; `--groups` selects owners. |
| `game_check.py` / `game_check_bl.py` | Validate Godot LOD meshes, UVs, convex collision and embedded GLB textures; produce an LOD turntable. See `GAME_READY.md` for Unreal validation. |
| `compare_rounds.py` | Compare rounds and focused crops with a reference row. |
| `audit_round.py` | Optionally inspect supported transcripts for file access, sibling rounds, web calls and measured token usage. |

## Review principles

- Better photos of the weak part usually help more than adding rules to the brief.
- Compare each refinement with the previous round: a fix can erase earlier improvements.
- Check proportion complaints with a scale-matched overlay before changing geometry.
- Dark cavities need visible lip highlights, wall thickness and inner falloff. Brightening is for
  inspection only; keep judged lighting fixed. Skip brightening when it clips a high-key image.
- Use critiques as a repair list within a round, not as a numerical score between rounds.
