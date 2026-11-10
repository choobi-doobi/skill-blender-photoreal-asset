# photoreal-asset

Build photoreal Blender assets from reference photos, with independent visual review and optional Godot or Unreal Engine exports.

Requires Blender with Cycles, Python 3, and an agent with file, shell and image tools. Review uses subagents or Claude Code.

Install this folder as `photoreal-asset` in your agent's skills directory.

```sh
python -m pip install -r requirements.txt
```

Put Blender on PATH or set `PHOTOREAL_BLENDER` to its executable. Use any project directory.

> Use photoreal-asset to build a weathered steel barrel, game-ready for Unreal Engine.

See [SKILL.md](SKILL.md) for the workflow and [game-ready instructions](templates/GAME_READY.md) for engine exports.
