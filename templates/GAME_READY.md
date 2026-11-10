## Game-ready deliverable (rule 12)

Choose Godot, Unreal Engine, or both from the user's request. Keep the common requirements
and the selected engine sections when inserting this template into a build/refine task.
If no engine is specified, deliver the portable Godot-compatible GLB and name that choice in the report.
Fill `{NAME}` (PascalCase), `{TRIS}` (LOD0 budget; default 4000), and the usual task paths.

### Common source asset

Using the installed Blender's Python API (`bpy`), make {ASSET} at real-world scale
(1 Blender unit = 1 metre), Z up, origin at base centre, transforms applied.

- Build clean topology with bevelled edges and a separate high-poly bake source `{NAME}_high`.
  Bake dents, panel lines and weld seams into the low-poly asset rather than shipping the high-poly.
- Bake 2K base colour, tangent-space normal and ORM (R = AO, G = roughness, B = metallic).
  Bake curvature for wear as needed. Keep base colour in sRGB and normal/ORM as non-colour data.
- Unwrap UVs without overlaps or folds, with 8 px island padding at 2048 and consistent texel density.
- Name meshes `{NAME}_LOD0` through `{NAME}_LOD3`, targeting {TRIS}, 50%, 20% and 5% of that
  budget, within 10%. Preserve the silhouette, UV seams and shared material across LODs.
  Triangulate the export geometry consistently with the normal bake.
- Put only LOD0 with its baked maps in the `{PREFIX}` collection judged by the photo check.
  Keep high-poly, lower LODs and collision in collections without that prefix.
- Deliver the packed `.blend`, build/export scripts, engine exports and `NOTES.md` recording
  units, forward axis, normal convention, export/import settings and validation results.

### Godot

Add a closed convex collision mesh `{NAME}-convcolonly`. Export the four LODs and collision
as `export/{NAME}.glb`, with textures embedded; exclude the high-poly, cameras and lights.
Use an OpenGL (+Y) normal map.

Godot's `-convcolonly` suffix creates collision and removes the visible collision mesh.
`_LODn` names do not configure manual LOD switching: use visibility ranges for the supplied
meshes and disable automatic mesh LOD generation when testing those manual levels. Alternatively
use Godot's generated LODs from LOD0; hide/remove the other render meshes in that scene.
Verify that only the intended LOD is visible and that collision works.
See [import suffixes](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html)
and [mesh LOD](https://docs.godotengine.org/en/stable/tutorials/3d/mesh_lod.html).

**Validate:** run the locked checker until it passes, then inspect `lods_turntable.jpg`:

```sh
python "{SCRIPTS}/game_check.py" --asset "{PROJECT}/asset.json" --blend "{ROUND_DIR}/final/{FILE}.blend" --glb "{ROUND_DIR}/export/{NAME}.glb" --name {NAME} --tris {TRIS} --out "{ROUND_DIR}/renders/game_check_v1"
```

It checks source LODs/high-poly, triangle budgets, topology, normals, applied transforms, base-centred
origin, shared materials/UV layer names, UV overlaps/padding/density, closed convex collision,
and GLB nodes, embedded 2K images and base colour / normal / ORM wiring. It does not run Godot.
Verify the final scene in Godot too; if the editor is unavailable, report the import check as pending.

### Unreal Engine

**Export:** use FBX static meshes plus external PNG textures in `export/unreal/`.
Keep the common Blender source in metres; export unit metadata/conversion so a 1 m dimension
imports as 100 cm in Unreal. Apply axis conversion once, then verify Z up and the intended
forward direction in Unreal. Record actual settings rather than assuming an exporter preset.
Unreal defaults to centimetres; see [units](https://dev.epicgames.com/documentation/en-us/unreal-engine/units-of-measurement-in-unreal-engine).

1. Export `{NAME}_LOD0.fbx` with the render mesh `{NAME}_LOD0` and a closed convex collision
   mesh named `UCX_{NAME}_LOD0_00`. The name after `UCX_` must match the exported render mesh
   exactly, including `_LOD0`. Add `_01`, `_02`, etc. for additional convex pieces if needed.
   Keep these export-only collision copies out of the judged collection. Exclude high-poly,
   other LODs, Godot collision, cameras and lights from this file.
2. Export each lower LOD to its own `{NAME}_LOD1.fbx` through `{NAME}_LOD3.fbx`, sharing the same
   pivot, placement, material slots and unit/axis conversion. Import LOD0 as one Static Mesh,
   then import each lower file into its corresponding LOD slot in the Static Mesh Editor.
   Merely naming meshes `_LOD1` does not wire them as LODs. A single FBX with an actual LOD
   group is also valid if the exporter supports it; enable Import Mesh LODs for that route.
3. Import authored normals/tangents consistently with the bake and disable automatic collision
   generation when using UCX. In the Static Mesh Editor, display simple collision and confirm
   the intended hulls were imported. Check every LOD slot and set screen-size transitions.
   See [Epic's FBX pipeline](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine)
   and [LOD import](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-static-mesh-lods-using-fbx-in-unreal-engine).

**Materials:** save `{NAME}_BaseColor.png`, `{NAME}_Normal_DX.png` and `{NAME}_ORM.png`.
For Unreal's DirectX (-Y) normal convention, invert the green channel of the Blender/OpenGL
bake in the Unreal copy, or use Flip Green Channel at import, once. Preserve the OpenGL original
for Blender and Godot. Set the Unreal normal texture to Normalmap compression and sRGB off.
Set base colour sRGB on and ORM sRGB off (Masks compression); wire ORM R to Ambient Occlusion,
G to Roughness and B to Metallic. Rebuild/verify these connections in Unreal; FBX material
import does not reproduce arbitrary Blender shaders. See [texture settings](https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-asset-editor-in-unreal-engine)
and [normal conventions](https://experienceleague.adobe.com/en/docs/substance-3d/bakers/common-questions/what-is-the-difference-between-the-opengl-and-directx-normal-format).

**Validate:** check the common source requirements in Blender, render and inspect each LOD from
four angles, then verify dimensions, pivot, orientation, triangle counts, LOD transitions, simple
collision and texture channels in Unreal. Save screenshots and results in `NOTES.md`. Add a
separate non-overlapping lightmap UV channel if the target project uses baked lighting. Follow
the project's Nanite choice; do not silently replace requested manual LODs with Nanite.

`game_check.py` validates the Godot GLB contract, not FBX or an Unreal project. For Unreal-only
work, use the checks above; for both engines, also run the Godot checker on that export.
If Unreal is unavailable, deliver the FBX/PNGs and source checks but label engine import validation
as pending. Do not claim a successful Unreal import based on file existence or a Blender render.

### Blender baking notes

- Cycles has no curvature bake type. Bake a Geometry Pointiness shader as EMIT from the high-poly,
  or derive curvature from the normal map; use it for wear rather than exporting a separate map.
- Decimate Collapse does not use the Planar-mode Delimit setting. Preserve seams and inspect the
  evaluated UVs and silhouette rather than assuming a particular decimation option protects them.
- For glTF ORM, route G to Roughness and B to Metallic through Separate Color. Route R to an
  Occlusion input in a node group named `glTF Material Output`, so one ORM image supplies both
  occlusion and metallic-roughness. Confirm the exported GLB rather than assuming the wiring worked.
