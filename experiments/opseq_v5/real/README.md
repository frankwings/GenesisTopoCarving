# Real-data setup for the topo-carving chain (Plan A) — runbook

Status 2026-09-16: pipeline runs end-to-end on a phone video of a static object with NO ground-truth mesh.
First object: dinosaur toy (`benchmarks/dinasour/1000007062.mp4`, genus 0). Losses = silhouette only (no photometric yet).

## 0. Capture requirements
- Static object (no moving parts), matte preferred. For the topology claim: an object with a through-hole (mug handle).
- Full 360 deg orbit at 2 elevations (~20 and ~45 deg) + a few seconds top-down, slow, 30-40 s, 1080p is enough.
- Textured background is GOOD (desk clutter gives SfM features); blank tables/mousepads are where COLMAP fails.
- Constant lighting. Object should stay fully inside the frame (crops assume this).

## 1. Frames + masks + poses  (`real/prep_video.py`, ~2 min for 150 frames, CPU/GPU)
```bash
cd experiments/opseq_v5/real
SIFT_ROBUST=1 python3 prep_video.py /path/to/video.mp4 <dataset_dir> --n 150
#  -> <dataset_dir>/images/f_XXX.jpg   sharpest frame per window (Laplacian variance), cv2 auto-rotates portrait video
#  -> <dataset_dir>/masks/f_XXX.png    rembg isnet-general-use, largest component (255 = object)
#  -> <dataset_dir>/sparse/0           pycolmap: SIFT (16k features, affine-shape + DSP when SIFT_ROBUST=1),
#                                      sequential(overlap 25) + exhaustive matching (guided), incremental mapping,
#                                      one SIMPLE_RADIAL camera (CAM_MODE=SINGLE; PER_IMAGE was tested: no gain)
#  -> <dataset_dir>/prep.json          names, picks, colmap {registered, points, reproj, camera}
```
Expect >= 90 % of frames registered, reprojection ~1 px. Frames over textureless background may drop out.

## 2. SAM2 masks  (`real/sam2_masks.py`, 10 s / 155 frames on GPU)
```bash
python3 sam2_masks.py <dataset_dir>        # -> <dataset_dir>/masks_sam2/  (the chain reads THIS directory)
```
Prompt = rembg bbox + 5 positive points (centroid + 4 k-means centres), multimask, pick the candidate with the best IoU
vs rembg, clip to the dilated rembg mask (kills background leaks), largest component, holes filled.
Dinosaur: IoU vs rembg median 0.98; hull consistency identical (0.869 vs 0.861) -> segmentation is not the bottleneck.

## 3. Pose/mask sanity check  (`real/hull_consistency.py`, 30 s)
```bash
python3 hull_consistency.py <dataset_dir>                 # all views
python3 hull_consistency.py <dataset_dir> --views 60-90   # a sub-arc
```
Carves a visual hull (all-but-`slack` voting) and reports the fraction of every mask covered by the projected hull.
Rigid object + exact poses -> ~1.0. Dinosaur: median 0.87 on all 145 views, 0.99 on any narrow arc; unchanged by
rembg/SAM2, relaxed/robust SIFT, single/per-image intrinsics -> residual per-frame pose error of a few px
(rolling shutter / EIS of the phone video are the remaining suspects). Deficit shows as a ~7 % shrink of the head (lever arm).

## 4. Run the chain  (`despike/golden_chain.sh`, ~7-9 min per object on a shared GPU)
```bash
cd experiments/opseq_v5/despike
export REAL_DATA=real/<dataset_dir>   # relative to experiments/opseq_v5
export HULL_INIT=1 S1_STEPS=400        # project the init sphere onto the hull; Stage-1 400+400 steps
export HULL_VOTE=8 HULL_DEAD=3         # permissive hull for noisy poses (see 5.)
TAGP=<tag> SHAPES="<name>" bash golden_chain.sh
```
What `REAL_DATA` changes (all in `despike/real_scene.py`, synthetic path untouched when unset):
- 145 registered frames -> 16 held-out (every ~9th) + 64 training views.
- World normalisation: centre X = LSQ intersection of the mask-centroid rays; scale s = median over views of
  camera-distance x (mask bbox half-size / f) / 0.8  -> object radius 0.8 like the synthetic shapes.
- Per-view square crop, side = 1.25 x 95th-percentile mask bbox max-dim (robust to leak frames), object-centred,
  resized to 256; intrinsics adjusted; OpenGL MVP per view; x-flip chosen empirically by rasterising the mask-carved
  hull and maximising IoU vs the masks (dinosaur: 0.872 median = the pose-consistency ceiling).
- gt = cropped masks (0 = fg, 255 = bg, nvdiffrast row order); depth / diffuse targets zero, W_DEPTH = W_DIFF = 0.
- Hull = `hull_field.carve_hull` on the 512 px mask crops (same carving loop as synthetic), vote = HULL_VOTE.
- Held-out exam = silhouette IoU on the 16 held-out masks (`exam_real.py`); no CD/VolIoU (no GT).
Outputs: `despike/results_genus/<name>_<tag>_{raw,auto}.npz`, handles json, `[exam_real]` line in the log.
Render: `python3 real/render_mesh.py despike/results_genus/<name>_<tag>_auto.npz <out_prefix> --turn 72 --up "<gravity up>"`

## 5. Results so far (dinosaur, silhouette-only)
| run | hull vote / dead | V | train sil IoU | held-out ho16 | hair | notes |
|---|---|---|---|---|---|---|
| Stage 1 cc3 only | - | 962 | 0.970 | 0.963 | 2k | no hull loss in Stage 1 |
| real1 | 2 / 1 vox | 57.8k | 0.874 | 0.858 | 52 | mesh pulled INTO the eroded hull (= hull IoU 0.872); head 7 % small, arms -> noodles |
| real2 | 8 / 3 vox | 51.4k | 0.955 | 0.963 | 1814 | head volume back; genus 0, watertight, SI 0 |
Lesson: on synthetic data the hull is a superset of the object so the hull-field loss is harmless; with real pose noise the
all-but-2 hull is eroded and the loss actively shrinks the mesh. HULL_VOTE ~ 12 % of the views fixes it.
Renders: `real/dino3/mesh_real{1,2}_grid.png`, `_turn.mp4`. Overlays: `real/dino3/fit_overlay.png`, `hull_overlay.jpg`.

## 6. Known gaps / next
1. Photometric term (per-vertex colour, Nicolet-style) — silhouettes cannot resolve the mouth, eyes, belly stripes.
2. Pose refinement from silhouettes/photometrics (joint camera optimisation) — the 0.87 consistency ceiling.
3. Thin-structure guard from hull thickness (arms collapse to noodles under inconsistent silhouettes).
4. Multi-component objects (hull with >1 connected component) — not handled.
5. A holed object for the topology claim (mug) — capture pending.

## 7. Appearance / depth / camera experiments on the dinosaur (2026-09-17/18) — CLOSED, off the TopMod path
Script `despike/phase8_joint.py` (fixed topology, no DLFL remeshing; specs `despike/JOINT_OPT_SPEC{,_V2,_V3}.md`).
Input = silhouette-only golden result `dino_real7_auto` (held-out sil IoU 0.9696). All numbers on real/dino3, 512 px.
Silhouette-only ceiling first: 512 px, soft silhouettes (SIL_BLUR), out-of-frame fix all land at 0.965-0.970 and never
recover the arms — the arms overlap the belly in most views, so the silhouettes barely contain them (residual_real6.png).
| experiment | result |
|---|---|
| v1: per-vertex colour, unshaded, geometry free | surface CRUMPLES (mean adjacent-face angle 47.9 deg vs 5.7 input); not fixed by LR_V/6 + 10x Laplacian (36 deg). Without a shading model geometry only receives noise from colour interpolation; eyes/teeth are painted, not carved. 52k vertex colours = one sample per 3.7 px. |
| v2 d0s1: shading only | texture and highlights get carved into geometry (belly stripes -> ridges), 6.7 deg, IoU 0.9638 |
| v2 d1s0 / d1s1: Depth Anything v2 prior, scale-shift-invariant L1 + gradient term | smooth (3.5 / 5.4 deg), held-out depth err 0.0163 -> 0.0113 / 0.0124, first relief silhouettes cannot give (body/base step, arm relief, brow) BUT held-out sil IoU drops to 0.952 / 0.956: the absolute (affine-aligned) term bends the global shape |
| **v2 dgrad: W_DEPTH_L1=0.2 W_DEPTH_GRAD=1.0 W_SIL=6, no colour on geometry** | **best geometry: 2.7 deg, sil IoU 0.9669, depth err 0.0133.** Mono depth is trustworthy for LOCAL relief (gradient term), not for absolute shape. Arms are still relief, no eyes/teeth. |
| cameras, v1 (vertex colour, geometry free) | free cameras move 0.006 deg; known 0.26 deg perturbation recovered 7 % (prior) / -45 % (no prior) |
| cameras, v3 gate (UV texture 2048^2 via xatlas + dr.texture, mip bias 5->0, geometry frozen), W_CAM=0.1 | 15.5 % (texture) vs 15.7 % (vertex colour) — but this test was BIASED: the prior is centred on omega=0 = the perturbed pose, so it pulls towards the wrong answer; identical numbers for both appearance models = equilibrium set by prior vs silhouette |
| cameras, v3 gate, unbiased (W_CAM=0) | residual GROWS: 0.213 -> 0.494 deg (texture, -132 %) / 0.460 deg (vertex colour, -116 %); train PSNR 21.8 in both |
Conclusion on cameras: with geometry that is itself wrong by several pixels (no arms, no face relief) each camera drifts to
make the wrong mesh fit its own photo; photometric/silhouette refinement does not localise the cameras here, with or
without a sharp texture. (It says nothing about refinement on accurate geometry.) The Boss's prior — do not try to fix
poses, make the reconstruction robust to them — was right for this data.
Why closed: none of this touches topology or the DLFL operators, and the dinosaur is genus 0, so it cannot support the
paper's claim. What the paper needs from real data is one object with a through-hole (mug) reconstructed at silhouette
quality with the handle DISCOVERED (membrane detector + verify only need masks). Reusable pieces if ever needed:
`real/mono_depth.py` + the gradient-dominant depth prior (dgrad settings) as an optional geometry refinement stage.
Env note: xatlas 0.0.11 installed into the user site with `pip install --user --no-deps --break-system-packages`
(PEP 668 guard; wheel has no runtime deps; numpy/torch verified unchanged; undo with `pip uninstall xatlas`).

### 7b. Addendum 2026-09-18: textured renders, the geometry+texture control, texture speckle
- `real/render_textured.py <mesh.npz with uvs,uv_idx> <texture.png> <out> [--turn N] [--tex-down k]`: free-viewpoint renders of
  the UV-textured mesh (full triangle rasterisation + dr.texture; render_mesh.py only knows vertex colours).
- The textured results shown so far (`dino_joint_ctrl_tex1.npz` + `real/dino3/tex_ctrl_tex1.png`) have geometry
  BIT-IDENTICAL to dgrad (max vertex displacement 0.0): every completed v3 run was a gate run with FREEZE_GEO=1.
- Control actually optimising geometry WITH the texture (`v3_cam0`: TEX=1, cameras frozen, dgrad depth settings,
  W_PHO=0.3, 2500 steps, 7.6 min): held-out sil IoU 0.9669 -> 0.9660, held-out PSNR 21.6 -> 22.4 dB, crumpling 2.7 -> 3.5
  deg, vertices move 4.0 px mean / 9.9 px p95, yet no arms / mouth cavity / eye sockets appear; the only visible change is
  the solar-panel outline carved deeper = a TEXTURE edge baked into geometry (same failure as shading-only).
  => texture makes the render more photo-like, it does not improve geometry here (cmp_v3cam0_geo.png).
- "Pits" on the textured surface are texture noise, not geometry and not point rendering: the 2048^2 atlas is finer than
  the 512 px supervision, so a training pixel only constrains the AVERAGE of ~4x4 texels and single texels stay free.
  Box-filtering the texture to 512^2 before rendering removes the speckle (textured_zoom_texres.png). Proper fix if ever
  needed: supervise with the full-resolution photos. Grey mosaic on the back = never observed (capture covers ~150 deg).

## 8. iPhone (StrayScanner) captures survey — 2026-09-18
Pipeline: prep_object.sh (frames + prep_arkit.py ARKit->COLMAP + rembg + sam2_video_masks.py) then carve_object.py.
ARKit poses are excellent everywhere (ray-miss 4-8 mm). The captures were shot for Gaussian Splatting scenes, so the
BLOCKERS are (a) partial angular coverage of the object even when the camera path is a "full orbit", (b) SAM2-video can't
track thin/dark clutter-surrounded objects, (c) handle holes fill in the silhouette (see 7b).
| capture | object | genus | ray-miss | object-orbit | SAM2-video | hull result | usable? |
|---|---|---|---|---|---|---|---|
| bb126f8e17 | flower mug | 1 | 7 mm | ~full | ok (12/148 leak) | handle HOLE fills -> genus 0; force-reopen -> genus 1670 (coffee/interior) | NO (hole ambiguity) |
| e7da89a9bb | flower mug | 1 | 4 mm | ~220° arc | ok | handle visible, back unbounded | NO (partial) |
| 1bea72bf80 | green-tea bottle | 0 | 4 mm | 151° eff. | poor (IoU 0.64) | thin crescent wedge, spurious genus 5 | NO (coverage) |
| 6c96741473 | headphones | ~1 | 8 mm | 347° | FAIL (IoU 0.16) | empty hull (tiny dark object untrackable) | NO (segmentation) |
| others (0b555, 120d, 1470, b2c4, e354, e3bc) | rooms / bottle | - | - | 238-286° | - | scene captures, not single objects | NO |
Conclusion: none of the existing iPhone captures are clean enough for silhouette-based topology. ARKit conversion +
SAM2-video tooling is ready and reusable; a dedicated CLEAN capture (plain background, single object, full 360° at two
elevations, empty mug) is the path to a real genus-1 result. Tools: real/prep_object.sh, real/carve_object.py.

## 7. iPhone mug (mug_0f1e2c6e4f), 2026-10-17 — first real genus run: the count was right, the tunnel was WRONG
- Pipeline: StrayScanner -> SAM2 with explicit seeds (`SAM2_SEEDS`/`SAM2_NEG`; the bottle heuristic segmented only the
  interior) -> ARKit-seeded SIFT BA (`refine_poses_ba.py`: 145/145, 0.67 px; consistency 0.962 -> 0.976) -> LiDAR
  occupancy as the hull (`lidar_hull.py`) -> chain. `real_scene` view matrix fixed (metric ARKit scale put every vertex
  before the near plane; ho16 was 0). Result `mug3ba_lid3`: genus 1, watertight, SI 0 %, held-out IoU 0.981 — BUT the
  handle is solid and the tunnel runs vertically through the cup body.
- Why: the LiDAR never measures the cup's floor or underside (it stands on the table), so fused occupancy is a tube open
  at both ends (genus 1 from the tube); the 10 mm handle hole is closed by the 4 mm closing and by the permissive
  silhouette hull (vote 12, needed against ARKit drift). STRICT audit is off for real data, so nothing flagged it.
- Depth free-space carving (`depth_carve.py`, voted, margin 20 mm): gets the body right (cavity open at the top, solid
  bottom -> body genus 0) but carves away the handle and the rim: on this glazed mug the LiDAR reads 7-17 mm BEHIND the
  silhouette-fitted surface and its native resolution is far coarser than the 256x192 map, so every part thinner than
  ~2 cm is lost. Restricting carving to free components that reach > 6 mm inside the silhouette hull does not help (the
  thin parts are connected to the cavity's free space).
- Next: depth for the cavity/bottom only, silhouettes with a STRICT vote for the handle hole (needs better poses:
  RoMa v2 / silhouette-based pose refinement), and the linking audit on real data so a wrong-place tunnel is reported.

## 8. iPhone mug, 2026-10-18 — first CORRECT real genus-1 result (tunnel through the handle), textured
Result `mug3rm_sil1v`: genus 1, one component, watertight, SI 0 %, held-out IoU 0.986, hair 882, 11.8 min. The tunnel
is the handle hole: removing the handle drops the genus to 0, and morphological closing does not seal it up to r = 16
voxels (the wrong-place tunnels of earlier runs sealed at r = 4). Four fixes, each verified by an A/B run:
1. **SAM2 hole filling off** (`sam2_video_masks.py`, `SAM2_FILL_HOLES=0` default): the floodFill erased the handle
   hole in 145/145 frames. Unfilled: 84/145 frames show the hole; silhouette oracle genus 1 for vote slack 8-16 at
   every closing radius, located at the handle (slices).
2. **RoMa v2 poses** (`real/mug3rm`, L4: 145/145 registered, 0.54 px).
3. **Thin handle refinement** `THICK_THIN=0.14` (Thingi10K default 0.08): the handle strap is ~2.7 mm (2.5 % of the
   mug), the Stage-1 handle edges were 0.044 > strap thickness 0.033, the two sides of the strap interpenetrated from
   Stage 1 on, and the Stage-5 untangling cut the strap into 2-3 pieces (traced step by step; THIN_GUARD,
   HANDLE_GUARD and SI_PUSH=0 all still broke it at the same place). Also `TRAIN_RES=512`.
4. **Automatic view-consistency check** `REAL_VIEWCHECK=1` (`real/view_consistency.py`, cached in
   `<scene>/viewcheck_drop.txt`): drops frames that veto a solid chunk every other frame calls material. On mug3rm
   it drops f_058 (SAM2 lost the rim/inside), f_093, f_119, f_133, f_134 (handle 50-106 px off while the symmetric
   body fits: a rotation about the mug axis); every other frame scores 0. Without the drop (only 3.): the handle
   hole gets a membrane, ho16 0.954, hair 36944. `REAL_EXCLUDE=a.jpg,b.jpg` drops frames by hand.
- Texture: `real/bake_vertex_colors.py` projects the photos onto the (once-subdivided) mesh with a depth test, facing
  weight and eroded-mask gate; 85 % of vertices seen (median 38 views), the rest (bottom) diffused from neighbours.
- Still open: the cup is closed at the top (silhouettes cannot see the cavity; needs depth), 0.14 is not yet checked
  on Thingi10K, one object only.

## 9. Five iPhone objects, repeated runs, surface priors — 2026-10-19/21 (commits ebf709e, 21f9ade)
Objects: kettle (handle), mug3rm (handle), wbottle (cap loop ~1 cm), fish, tripod2. Every number below is from the
go-to chain `HULL_INIT=1 S1_STEPS=400 HULL_VOTE=10 HULL_DEAD=3 TRAIN_RES=512 THICK_THIN=0.14 REAL_VIEWCHECK=1
S3_ROUNDS=6 S5_ROUNDS=4` on the UNDISTORTED scene (`real/<obj>_ud`, section 9.3), 4 repeated runs per object.

### 9.1 Results (strict: the surface must realise the hull tunnel, `linking_audit --rank`; not just the genus count)
| object | oracle (plateau r=1..6) | genus | strict tunnels realised | held-out sil IoU | dihedral mean |
|---|---|---|---|---|---|
| kettle | stable 1 | 1 | 2/2 runs | 0.974-0.975 | 3.8-6.5 deg |
| mug3rm | stable 1 | 1 | 4/4 | 0.976 | 7.1-10.3 |
| wbottle, SIFT poses | stable 1 (ORACLE_NRES=320) | 1 (cap loop) | 4/4 | 0.947 | 8.8 |
| wbottle, RoMa poses (`wbottler_ud`) | stable 1 (320) | 1 (cap loop) | 4/4 | 0.958 | 8.8 |
| fish | stable 0 | 0 | 4/4 (consistent) | 0.950 | 11 |
| tripod2 | stable 0 | 0 | 4/4 (consistent; true genus unverified) | 0.913-0.921 | - |
The wbottle cap loop (< 1 cm) is realised in 8/8 runs with ORACLE_NRES=320 + THICK_THIN=0.14 + 4 thin-refine rounds
(THICK_ROUNDS=4): the "holes < 1 cm are out of scope" caveat is withdrawn for this object. RoMa poses beat SIFT on the
bottle (IoU 0.958 vs 0.947, hair 3400 vs 5800) and are a wash on the kettle (0.983 vs 0.982).

### 9.2 Repeated runs, not seeds: the chain is NOT deterministic
`SEED` only seeds torch/numpy; the chain draws no random numbers (except the optional normal-loss view subset). Two
runs of Stage 1 with the same seed and settings differ by up to 0.175 (vertex positions, same topology): GPU float
accumulation order (nvdiffrast backward / index_add). Through the discrete decisions (drill, collapse, flips) this grows
into different outcomes, so every real-data claim must be a SUCCESS RATE OVER REPEATED RUNS; a single run is one sample.
Making the chain deterministic was not attempted (deterministic kernels, slower); repeated runs expose the weak spots.

### 9.3 Bugs found by the repeated runs (all fixed)
1. **Strict audit silently off on real data.** `linking_audit`/`hull_locate`/the AIR_DRILL read the GT `.obj` for the
   hull grid frame; on real captures the load failed inside a try/except and the RANK gate, the air-loop drill and the
   `[STRICT]` audit were skipped without a message. Before the fix the kettle handle membrane got a 1.6-edge drill in
   one corner (count rescue, dho 0.0003, genus 1 = g*), membrane intact: kettle 1/4 to 2/4 runs, mug 1/3. Fix: the plug
   cache stores `lo/hi`; real plug cache built from the RealScene hull; `RESCUE_RANK` (default on for REAL_DATA): a
   handle accepted only by the count rescue must raise the linking rank. After: kettle 4/4, mug 4/4.
2. **Stage 5b / 6b crumple real surfaces.** The late pass DR rounds and the bare 6b seam refit (no adaptive remesh,
   no collapse, no PALF Laplacian) take a clean Stage-5 surface (dihedral 18 deg) to 50 deg; Stage 6 repairs it (13.5)
   and 6b crumples it again (47), Taubin x5 leaves 26. Only runs that enter 5b were hit (synthetic exact silhouettes
   are fine). Fix: on REAL_DATA 6b runs with the Stage-6 PALF settings (500 steps). After: no crumpled run in 22.
3. **Lens distortion ignored.** `real_scene` projects with a pinhole; COLMAP's SIMPLE_RADIAL k1 = -0.015..-0.039 moves
   silhouettes by 2-5 px median, 8-20 px p95 (`real/undistort_scene.py`, scene `<obj>_ud`, camera -> SIMPLE_PINHOLE).
   Fixed, but it is NOT the cause of the surface ridges (9.4).
4. Stage-6 refine can diverge on short edges (tripod: ho16 0.959 -> 0.016). `REFINE_GUARD=0.05` keeps the input mesh.

### 9.4 Surface quality: where the large ridges come from and what does NOT fix them
Silhouette-only real reconstructions carry large oriented ridges (kettle: diagonal, body; mug: fainter). Controls:
- Exact silhouettes rendered from a smooth mesh through the same 151 cameras (`real/make_syn_scene.py`): NO ridges
  (fine grain only, Taubin removes it). +2 px random per-frame shift (sub-pixel at 512): still none. +6 px: the whole
  surface crumples. => the chain is sensitive to few-pixel inter-view silhouette inconsistency, and the real
  inconsistency is STRUCTURED (oriented ridges, not isotropic noise): on the kettle, frames f_072-081 (background seen
  through the handle) and the reflective granite edge push the mask out by a few px in a view-dependent way.
- Not the cause: poses (RoMa vs SIFT: ridges unchanged), lens distortion (undistorted: unchanged), specular reflection
  alone (the ceramic mug has the same ridges), MoGe normals (clean on all views).
- Taubin on the final mesh (`ITERS=15`, dihedral 7.1 -> 2.8 deg, ho16 -0.0016) removes the grain, not the ridges.
  Stronger PALF Laplacian (x2.5, x5) and soft silhouettes (`SIL_BLUR=2/3`) do not remove them either (SIL_BLUR=2 once
  crumpled the whole surface - one sample).
- **Metrics**: held-out silhouette IoU does not see surface quality (the crumpled runs have the HIGHEST IoU, 0.987);
  the median angle to the MoGe normals (`real/check_mono_normal.py`) is better but is also fooled by terraces (9.5).
  Report both plus the dihedral mean, and look at the renders.

### 9.5 Monocular normals (MoGe-2, `real/mono_normal.py`, `W_NORMAL` in phase4_inloop): NOT a default
Frame conversion validated (11.7 deg median vs the kettle mesh, every other axis convention >= 37 deg). Loss: masked to
the eroded silhouette, random 16 views/step, targets > NORMAL_MAXDEG=40 deg off are dropped (mug opening: the photos
see the concave interior, the silhouette mesh has a cap there; without the truncation the cap is twisted and one run
broke apart). Applied ONLY in the PALF refine stages (W_NORMAL_REFINE / SIL_BLUR_REFINE; in the DR/5b/6b loops it
crumpled the surface).
| object | blur3 + normal 0.03 | neither |
|---|---|---|
| kettle | diagonal ridges gone on the front, horizontal terraces below the handle; normal err 8.4 deg | ridges, 11.8 deg |
| wbottle (RoMa) | horizontal TERRACES on the body, IoU 0.958, normal err 7.1 | smooth, IoU 0.971, 13.0 |
| fish | terraces, IoU 0.950, 10.4 | smooth, IoU 0.970, 23.5 |
The terraces come from the normal loss (ablation: blur only = no terraces; normal only = terraces). A terraced surface
scores a LOWER normal error than the smooth one, so the per-pixel normal target is satisfied by stepping rather than
by the smooth surface - presumably small view-dependent biases in the targets that a staircase can honour for every
view at once. Conclusion: per-pixel mono-normal supervision trades the kettle's ridges for terraces elsewhere and costs
IoU; keep it OFF by default. If revisited: a low-frequency version (smooth both normal fields before comparing) or the
depth-GRADIENT prior that worked on the dinosaur (section 7: dgrad, 2.7 deg, IoU kept), validated on kettle + bottle +
fish together, not on one object.

### 9.6 Current real-data defaults
`real/undistort_scene.py` -> `<obj>_ud`; chain as above; `ORACLE_NRES=320` for small loops; RoMa poses when available;
`RESCUE_RANK` and the PALF 6b are automatic on REAL_DATA; no W_NORMAL / SIL_BLUR. Known open: large ridges on the
kettle/mug bodies (9.4), the mug opening is capped (silhouettes cannot see the cavity), tripod true genus unverified,
Thingi10K 71/96 must be re-run before RESCUE_RANK is enabled for synthetic data.
