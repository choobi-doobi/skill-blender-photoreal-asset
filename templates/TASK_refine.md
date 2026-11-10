# {ROUND} (one solo pass, refining {PREV}): role `solo`

You are the only builder this round. {PREV} built {ASSET}; its build is copied into this folder and is your
starting point: its build script(s), `tex/`, `final/{FILE}.blend`, its notes (`NOTES_{PREV}.md`), its last
photo check (`renders/{PREV}_check/`) and its judging renders (`renders/{PREV}_final/`).

Your job: refine **{PARTS}** ({ZONES}){FOCUS} until they read as real ones. {NEW_REFS_SENTENCE}

{NEW_REFS_LIST}
They are in `{PROJECT}/ref/` with the other photos. An image opened whole is shown downscaled, so crop regions at
full resolution to study the details.

1. Read `{PROJECT}/BRIEF.md`, `NOTES_{PREV}.md`, and inspect the reference photos with the host's image viewer, the ones named
   above closely.
2. Keep the rest of the scene as {PREV} left it, except to fix a severity 3 item the photo check reports.
3. The photos win over the brief's numbers, positions and angles included. If matching them means moving a
   part, move it, and move the parts connected to it with it.
4. Work only in this folder (`{ROUND_DIR}`).
5. Save the result as `{ROUND_DIR}/final/{FILE}.blend`, images packed (`bpy.ops.file.pack_all()`).
6. Deliver here: your build script(s), `NOTES.md` (what you changed and why, with the photo details you matched,
   each iteration, and for each photo check its severity counts and what you fixed after it), `renders/`.
7. Fix every flaw you can see in {PARTS} before finishing; you're the only builder, so geometry is not handed off.
8. Rule 11 (below) is part of the brief's rules. Where rule 9 and rule 11 differ on when to stop, rule 11 wins.
9. Last step: write `DONE.txt` with the finish time (ISO 8601) and a one-line summary. Write it only when you're finished.
{GAME_READY}
## Rule 11

11. **Prove it against the photos.** Before you finish, check the scene with the photo check (`check_v1`, next
    run `check_v2`, and so on):

    1. **Render & prepare critic jobs:**
       ```sh
       python "{SCRIPTS}/photo_check.py" --asset "{PROJECT}/asset.json" --parts "{ROUND_DIR}/final/{FILE}.blend" --out "{ROUND_DIR}/renders/check_v1"
       ```
       This renders every locked camera at judging settings, crops every layout zone from the camera that sees it
       best (dark crops get a brightened copy on the right for inspection only; the judged lighting doesn't
       change), and writes `renders/check_v1/critic_jobs.json` plus one prompt file per group in
       `renders/check_v1/critic_prompts/*.md`.
    2. **Run independent read-only critic subagents:**
       Read `renders/check_v1/critic_jobs.json`. For each job, use the host's native agent tools
       to launch a fresh independent critic with the full `prompt_file` text. Give it image/file
       reading only, no network or edit tools. Run jobs concurrently when supported, up to
       `critic.parallel`, and collect results using the host's completion mechanism. Save each
       JSON array reply to its `response_file` (`renders/check_v1/critic_logs/<name>.json`).
       If unavailable, use the configured Claude Code runner or report independent review as incomplete.
    3. **Merge & inspect critique:**
       ```sh
       python "{SCRIPTS}/photo_check.py" --asset "{PROJECT}/asset.json" --out "{ROUND_DIR}/renders/check_v1" --merge-critic
       ```
       Read `renders/check_v1/critique.md` and inspect the crops it names with the host's image viewer. Fix the worst items
       first, then run the check again (`check_v2`, ...).

    A failed or missing critic response is incomplete review, never a clean pass.
    Stop when a successful merged review reports no severity 3 or 2 items for {ZONES}, or after 6 runs. Where the brief's numbers and
    the photos disagree, the photos win; write the conflict in `NOTES.md`. The photo check is part of the locked
    harness: don't edit it.
