# Research: reference photos, brief and blockout for {ASSET}

Your job is the input for the build: gather reference photos and write the full brief. One agent then builds
{ASSET} in the installed Blender / Cycles from your brief, your photos, your blockout and the locked harness, and
"looks like a photograph" is the only score. Everything the builder needs to know has to be in your brief.

Project root: `{PROJECT}` (below, paths are relative to it). The harness config is `asset.json`: sky, ground,
the judged cameras, the collection prefix `{PREFIX}`, and which photos the photo check's critic uses.

## 1. Gather reference photos (`ref/`)

Collect 15–30 real photos of {SUBJECT_PLURAL}. Cover the whole object from several angles, every part that
the cameras show, close-ups of materials, wear, grime, labels and edges, and how parts sit, hang and rest on
each other. Dark or concave parts need their own photos: one well lit, one from each camera's angle. Prefer
daylight photos (the harness lights the scene with a daylight sky).

- Source them from Wikimedia Commons, or another site that states a license on the image page. In
  `ref/SOURCES.md` record each file's name, source page URL, author and license. Never guess a license: skip
  any image whose page doesn't state one. They're reference only; nothing goes into the library.
- Commons: query the API in batches (`action=query&generator=search&gsrnamespace=6&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=1600`),
  send a descriptive User-Agent with the project name only (never a person's name or email), back off and retry
  on HTTP 429 within a bounded retry budget. Use the host's permitted network tools. Download
  full resolution (`url`) for the photos of the hardest parts, `thumburl` (≤ 1600 px) for the rest.
- Inspect every photo you keep with the host's image viewer and discard poor ones (blurry, tiny, night-only, mostly not the
  subject). Name the keepers `refNN_<what_it_shows>.jpg`.

## 2. Write `BRIEF.md` (project root)

Base it on your photos. It must be concrete enough that the builder makes exactly what you mean.

- **What to build:** one coherent design synthesized from the photos (not a collage). Say which faces the
  cameras judge and need full detail.
- **Content:** any text, labels, numbers and markings, word for word. Invented brand only: no real brand
  names, logos or trademarks.
- **Layout contract** in metres (Z up, ground z = 0): the position and size of every part, each a zone in
  `research/layout.py` (see below) assigned to a top-level collection starting with `{PREFIX}`. Include the
  interfaces: what sits on, hangs from or plugs into what.
- **Materials, finishes and wear** per surface, and a "what makes it read as a photo" section drawn from what
  you see in the photos (edge highlights, wall thickness, contact shadows, dirt where hands and weather reach).
- **References table:** which photo to look at for what.
- The fixed sections from `{SKILL}/templates/RULES.md`, filled in and copied verbatim at the end.

`research/layout.py` defines `ITEMS`: one dict per zone with `id` (letter + two digits), `owner` (collection),
`name`, `note` (what it is, its interfaces, the refs that show it as `refNN`) and geometry: `kind="box", lo=(x, y, z), hi=(x, y, z)`
(or `cyl`, `disc`, `hoop`, `tube`; see `photo_check.bounds`). Mark an identical copy of a zone with a note
starting "As <id>" so the photo check inspects it once.

## 3. Prove the layout

Write `research/blockout.py` that builds `research/blockout.blend`: grey boxes of every zone in one collection
`{PREFIX}blockout`. Render it through the harness (`{SKILL}/scripts/run.py`) and check with the host's image viewer that each
camera frames its subject. You may adjust the cameras in `asset.json` now; they are locked once the build starts.
Put the owner → photo lists in `asset.json` (`owner_refs`, `overall_refs`): the critic gets up to six photos per
collection, first listed first.

## 4. Scope

Work only inside the project root: `research/`, `ref/`, `BRIEF.md`, `asset.json`. Last step: write
`research/NOTES.md` (search terms, photos looked at, kept and rejected, the design decisions), then
`research/DONE.txt` with the finish time (ISO 8601) and a one-line summary, only when everything is finished.
