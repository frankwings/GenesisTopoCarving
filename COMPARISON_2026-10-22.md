# Topo-Carving vs published methods — 2026-10-22

Benchmark: the 96 oracle-usable Thingi10K models (+ kitten, armadillo, rockerarm, threeholes, fertility, botijo),
GT genus from the GT mesh, ONE scorer for every method (`despike/compare_dmesh2.py` metrics: closed = every edge has
two faces; single component; genus from the Euler characteristic when closed and single; Chamfer (ICP-aligned,
100k samples each way); volume IoU on a 192³ grid; "strict" = closed AND single component AND genus == GT).
Ours = golden v7.2 (STATUS_2026-10-17), 64 silhouette views. Per-model data: `despike/results_genus/{rsr,sap,dmesh2,neus}/`.

## 中文摘要
同一批 96 个 Thingi10K 模型、同一套打分：
- RsR（TOG 2024，组合式）：表面最准（Chamfer 0.0071、IoU 0.990）但只有 3/96 闭合、3/96 严格 genus 正确；给它真值 genus 也无用。
- SAP（NeurIPS 2021，可微 Poisson）：76/96 闭合、35/96 严格正确；错法是假把手（最多 +14）、把孔抹平、细结构碎裂。
- DMesh++（ICCV 2025）：0/96 闭合。
- NeuS（NeurIPS 2021，神经 SDF）：在跑，明早补。
- 我们：96/96 闭合、71/96 严格正确；表面距离最差（0.0126）。结论：别的方法保表面不保拓扑，或封口但 genus 不受控；我们用表面精度换来经过验证的 genus。

## 1. Summary table

| method | venue | topology source | input | closed | single comp | **strict genus** | Chamfer med ↓ | vol IoU med ↑ | time / object |
|---|---|---|---|---|---|---|---|---|---|
| RsR — Surface Reconstruction Using Rotation Systems | TOG 2024 (SIGGRAPH Asia) | combinatorial: spanning tree + explicit handle edges, n-path rule | 60k blue-noise points + exact normals | 3/96 | 61/96 | **3/96** (10/96 after hole filling) | **0.0071** | **0.990** | 4 s |
| SAP — Shape As Points | NeurIPS 2021 | emerges: differentiable Poisson level set | same points | 76/96 | 53/96 | **35/96 (36 %)** | 0.0079 | 0.971 | 175 s |
| DMesh++ | ICCV 2025 | emerges: point existence probabilities | 64 views | 0/96 | — | — | 0.0096 | 0.837 | 4–16 min |
| NeuS (instant-nsr-pl) | NeurIPS 2021 | emerges: neural SDF level set | 64 RGB views + masks | running | | | | | ~10 min |
| **Topo-Carving (ours, v7.2)** | — | **discovered from the silhouette hull, one verified add_handle per tunnel** | 64 silhouettes | **96/96** | 96/96 | **71/96 (74 %)** | 0.0126 | 0.880 | 5–12 min |

Reading. Every published method reproduces the surface more accurately than we do — they keep the input points
(RsR) or fit them directly (SAP) — but none delivers the right closed topology: RsR does not close, SAP closes with
uncontrolled genus, DMesh++ is a soup. None of them can tell a spurious handle from a real tunnel, and none refuses
a case it cannot decide. That is the claim; the Chamfer gap (0.0126 vs 0.007–0.008) is the cost and is stated as such.

## 2. RsR (Cui, Gæde, Rotenberg, Kobbelt, Bærentzen) — `GenesisExp/GenesisRsR`, official C++ (CGAL/Eigen/Boost)
Method: kNN graph → MST (genus 0, one face) → insert edges longest-first with a topology test (edge must split a face:
|E| and |F| rise together) and a geometry test → optional handle connection: an edge between two different faces
raises the genus when the shortest graph path between its endpoints is longer than n (= 50) edges → ear clipping.
Same primitive as our DLFL add_handle; the evidence is the point-cloud graph instead of the images.
Runs (defaults k=30 r=20 θ=60 n=50; 12 GB / 15 min cap per run after one run reached 37 GB in the handle search):
| input variant | closed | single comp | strict | genus right after hole filling | CD | IoU |
|---|---|---|---|---|---|---|
| clean: blue-noise 60k + exact normals, Euclidean mode | 3/96 | 61/96 | 3/96 | 10/96 | 0.0071 | 0.990 |
| clean + `genus <GT>` (its topology-control mode) | 3/96 | 59/96 | 3/96 | 10/96 | 0.0071 | 0.988 |
| points only, RsR estimates normals | 14/96 (2 crash) | 32/96 | 14/96 | 22/96 | 0.0071 | 0.986 |
| positional noise 0.5× mean spacing, scan mode | 0/96 | 2/96 | 0/96 | 0/96 | 0.0085 | 0.850 |
| GT vertices + vertex normals | 0/96 (61 crash) | 8/96 | 0/96 | 0/96 | 0.072 | 0.15 |
Observations: median 183 boundary edges per model; every closed result has the right genus (the handle rule is sound,
closure is what fails); the genus prior cannot close holes; CAD-mesh vertices (adaptive density, edges 10× the median)
shred under the long-edge rule, while dense scan-like samples of smooth shapes work (kitten with its own vertices:
closed, genus 1; fertility from samples: closed, genus 4). Sampling sensitivity on kitten: random 60k → 100 boundary
edges, blue-noise 60k → 4, GT vertices → 0.
Caveat: default parameters and one density; the authors tune per dataset. A tuned row (k=50, 150k points) is the fair
follow-up before the number goes into the paper.

## 3. SAP (Peng, Jiang, Liao, Niemeyer, Pollefeys, Geiger) — `GenesisExp/GenesisSAP`, official code, patched
Method: oriented point cloud → spectral differentiable Poisson (DPSR, Gaussian σ) → indicator grid → Marching Cubes;
optimisation setting starts from a sphere of 20k oriented points and minimises Chamfer to the input points,
coarse-to-fine; "topology-agnostic": the genus is whatever the smoothed level set has.
Setup: authors' Thingi10K config (grid 128³, σ 2, 1600 epochs, resample every 200), same 102 point clouds as RsR.
Patch (pytorch3d / torch_scatter / libigl unavailable for torch 2.14+cu130): Chamfer = cKDTree nearest neighbours +
torch distances (same reduction as pytorch3d; cdist was 3–7 s/step, KD-tree 0.06 s), connected components via scipy,
unused imports guarded; separate venv. 175 s per object, 3 in parallel.
Result: closed 76/96, single component 53/96, strict 35/96, genus right on the largest component 43/96, CD 0.0079,
IoU 0.971. Of the 50 closed single-component meshes: 35 right, 9 with spurious handles (+1 … +14; e.g. t10k_91610
genus 13 for GT 2, t10k_1158268 genus 16 for GT 2), 6 with tunnels smoothed shut (t10k_399567: 0 for GT 3);
29/96 shatter into ≥ 9 components (thin parts; fertility 100, t10k_135074 830).

## 4. DMesh++ — from STATUS_2026-10-17 (official code, same 64 views, same scorer)
0/96 closed (triangle soup), Chamfer 0.0096 (wins 63:33 against us on distance), IoU 0.837, no genus defined.

## 5. NeuS (Wang, Liu, Liu, Theobalt, Komura, Wang) — `GenesisExp/GenesisNeuS` = instant-nsr-pl, running
Method: neural SDF, unbiased occlusion-aware volume-rendering weights, mesh by Marching Cubes at the end.
Setup: our 64 star cameras rendered to RGB (Lambertian headlight + ambient, white background, 512², masks;
`despike/export_neus_views.py`), 48 train / 16 test; 10 000 steps, MC 512, per-shape bounding radius / near / far
from the GT extent. Environment: tiny-cuda-nn fails to build with nvcc 13.0 (compiler internal errors) → separate venv
torch 2.7.1 + CUDA 12.8 (C++17, `-lcuda` from the CUDA stubs); the analytic SDF gradient crashes on the 5090 (illegal
memory access in tcnn double-backward) → `grad_type=finite_difference` (an option of the same code); full-image
validation renders crashed → `ray_chunk=512`. Scorer `despike/score_neus.py` maps the mesh into the compare frame.
Smoke (kitten, 1500 steps): a complete kitten with the tail tunnel, IoU 0.898 before the bounding-radius fix.
Numbers: to be added when the batch finishes (`despike/results_genus/neus/neus_syn.jsonl`).

## 6. Side-by-side turntable GIFs — `despike/results_genus/baselines_gifs/<shape>.gif` (GT | ours | SAP | RsR | NeuS)
| shape (GT genus) | ours | SAP | RsR | why |
|---|---|---|---|---|
| kitten (1) | genus 1 | genus 1 | open | easy case |
| fertility (4) | genus 4 | 100 components | genus 4, closed | RsR's best case: dense samples of a smooth scan |
| t10k_91610 (2) | genus 2 | genus 13 | open | SAP spurious handles inside a thin plate — invisible in the render, caught only by the topology audit |
| t10k_1158268 (2) | genus 0 (ours fails) | genus 16 | open | hard model, reported as is |
| t10k_399567 (3) | genus 3 | genus 0 | open | SAP smooths the tunnels shut |
| t10k_135074 (1) | genus 1 | 830 components | open | thin parts shatter in SAP |
Script: `despike/make_baseline_gifs.py` (re-runs RsR to keep its mesh; all panels in the compare frame, GT normalisation).

## 7. Method-table position (extends STATUS_2026-10-17 §1)
| | RsR | SAP | DMesh++ | NeuS | ours |
|---|---|---|---|---|---|
| topology | combinatorial, explicit handles | emerges (Poisson) | emerges (points) | emerges (SDF) | **discovered + verified** |
| closed output | no | yes | no | yes (after cleanup) | **yes, by construction** |
| genus control | prior or n rule, no closure | none | none | none | **oracle g\*, one audited handle at a time** |
| knows when not to answer | no | no | no | no | **refuses unstable hulls** |
| surface accuracy | best | very good | good | expected good | worst of the five |
