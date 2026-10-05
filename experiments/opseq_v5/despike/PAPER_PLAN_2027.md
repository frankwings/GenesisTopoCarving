# Two-paper plan (decided by the Boss, 2026-10-04)

## Paper A - SGP 2027 (deadline ~April 2027, not announced): the TOPOLOGY AUDIT
Working title: "Genus is not topology: a ground-truth-free audit of reconstructed surface topology".
- Claim: a mesh can have the right genus, the right silhouettes and pass a per-handle GT check and still have the
  wrong surface topology. Linking numbers between the mesh's H1 generator loops and closed curves through the
  tunnels of the carved hull give a GT-free rank = number of tunnels the surface realises.
- Material we have: `linking_audit.py` (air loops from hull-surface generators, validated against the hull genus),
  v6.4 fertility 6/21 strict vs 27/27 by genus, bt1 (redundant handle) and s5B (handle collapsed in refinement +
  damaged geometry) caught without GT, `loop_crossings` (sealed tunnel = exactly 2 crossings, usable on coarse
  meshes), the DLFL operators `remove_handle` / same-face `delete_edge` (repair with a manifold guarantee),
  LESSONS 7e-7j.
- To add: audit the OUTPUT OF OTHER METHODS (Nicolet, Palfinger, DMesh, FlexiCubes, NeuS/2DGS-extracted meshes)
  on a larger set (Thingi10K clean high-genus pool: 283 models already filtered) - "how often is the topology
  wrong when the numbers look right"; failure/validity conditions of the audit itself (oracle instability:
  heptoroid hull = 2.24x GT volume, genus 40/31/44 across radii).
- Not in A: the reconstruction pipeline as a contribution (only as one of the audited methods + the repair demo).

## Paper B - ICCV 2027 (deadline ~2027-03-08, estimated): METHOD + APPLICATION
Working title: "Topo-Carving: manifold meshes with discovered topology from casual video".
- Claim: from a phone video (poses + masks) to a watertight manifold mesh whose genus is discovered, every
  topology change a DLFL operator. Synthetic benchmark + real captures.
- Material we have: golden v6.5 chain (5 shapes 15/15 strict, botijo 2/2 strict VolIoU 0.996-0.998, 4-9 min),
  comparisons vs Nicolet / Palfinger / DMesh, `real/CAPTURE_SPEC.md` + ARKit/SAM2 tooling.
- To add: real captures (mug first), STRICT for REAL_DATA (roadmap item 7), larger synthetic set, comparison with
  implicit / Gaussian methods + mesh extraction, the applicability check (refuse when the oracle is unstable).
- B cites A for the audit and uses it as its topology metric.

## Keeping the two papers apart (dual-submission rules)
A = a measurement tool and what it reveals about existing methods; B = a reconstruction system. Different claims,
different experiments (A audits many methods on many shapes; B evaluates one pipeline incl. real data). The audit
may appear in B only as a cited metric, the pipeline in A only as one audited method. If A is not public by the
ICCV deadline, B must describe the metric briefly and cite A as concurrent / anonymous supplementary.

## Facts recorded 2026-10-03/04 (external models)
- Competitor models obtainable: kitten (have), botijo (genus 5), heptoroid (genus 22). Amphora / Pretzel / Birthday /
  Sorter / Elephant: no IDs published, not found. No source code for either Gao/Gu paper (papers, GitHub, web).
- Their metrics are undefined (only "ICP, then CD and Volume IoU"). Shared-baseline check with Nicolet under OUR
  metric and setup: armadillo 0.8987 (they report 0.8968) but botijo 0.9205 (they: 0.464) and heptoroid 0.1506
  (they: 0.564) -> their baseline runs are not reproducible from the paper; do NOT put the two tables side by side,
  re-measure every baseline ourselves.
- botijo, ours: genus 5, 5/5 tunnels, VolIoU 0.9977 / 0.9957, CD 0.0058, 574 / 461 s (2 runs).
- heptoroid, ours: FAILS. Hull g* = 31 (40/31/44 over radii), hull volume 2.24x GT (concavities between the woven
  tubes are invisible to silhouettes). With the hull oracle: genus 10, mesh collapsed (VolIoU 0.02). With the genus
  GIVEN (22) and STRICT off: genus 11, collapsed again (VolIoU 0.02) -> knowing the count does not help, the
  locations come from the hull. Nicolet on it: 0.15. This is the method's boundary (thin woven tubes).


## ICCV 2027 go / no-go plan (recorded 2026-10-05, Boss request)

Idea under evaluation: a 360-degree turntable video of a real object (mug; dinosaur as a genus-0 control) with
accurate camera poses + the current Topo-Carving chain. Assessment: worth doing, NOT sufficient on its own.

### Where we stand (measured)
- Synthetic, our 6 shapes: all strict-correct, VolIoU 0.987-0.998, 4-9 min.
- Thingi10K (343 clean closed high-genus models): silhouette oracle usable on 28 %; on 31 usable ones 18
  strict-correct with usable geometry (58 %).
- vs DMesh++ (ICCV 2025), 37 models, one scoring script: closed single-component manifold 0/37 (theirs) vs 37/37
  (ours); genus right 0 vs 27; Chamfer median 0.0087 (theirs) vs 0.0122 (ours) - ours better on our 6 shapes (6:0,
  ~5 %), theirs better on Thingi10K (22:9), more robust (thin plates, high genus) and ~40 % faster; their GPU peak
  12-29 GB.
- Real data: zero successful reconstructions so far (earlier captures dino..dino4, mug, mug2 all had problems).
- So the only axis we win is topology (closed, manifold, verified genus). A paper must be built on that axis.

### Minimum bar for submitting (missing any one -> do not submit)
| item | needed | have (2026-10-05) |
|---|---|---|
| real objects | 8-10, at least 6 with genus >= 1, genus covering 0 / 1 / 2 / 3+ (a genus-0 negative control included) | 0 |
| synthetic objects | 30-50, chosen by a published rule (Thingi10K "usable" pool has 96) | 37 run, 18 of 31 usable ones succeed |
| baselines | >= 4: DMesh++, one Gaussian (2DGS or SuGaR), one implicit (NeuS2), one mesh-based (Nicolet / Palfinger) | DMesh++, DMesh, Nicolet, Palfinger; no Gaussian, no implicit |
| success inside the declared scope | >= 85 % strict-correct | 58 % |
| topology comparison | every baseline's outputs through the audit: closed / manifold / genus right | DMesh++ only (0/37) |

### Strengtheners (any one makes the case clearly better)
- A downstream task that needs a closed manifold (physics simulation, 3D printing, parameterisation), run on our
  output and shown to fail on the baselines' outputs. Best value for effort.
- Ablations (oracle / strict repair / audit removed) - most of the data exists.
- Run time and GPU memory comparison (our memory footprint is far smaller).

### The two hard items
1. Success 58 % -> 85 %: failures are thin plates tangling at the coarse stage and missing tunnels at high genus.
   Either fix them or narrow the declared scope (e.g. exclude thin walls with a hull-thickness pre-check).
   Narrowing is realistic but weakens the paper.
2. Real objects 0 -> 8: depends entirely on getting the first mug right.

### Capture requirements for the turntable video (from real/CAPTURE_SPEC.md and past failures)
- Two elevations, one full turn each (level, and 30-40 degrees above); a single ring leaves top and bottom
  unconstrained and the hull diverges.
- Empty mug, handle hole showing background in most frames; plain background; object centred in every frame.
- Turntable (static camera, rotating object) gives poses from the rotation angle - far more accurate than hand-held
  SLAM; the rotation axis must be calibrated.

### Decision point
The first real mug is the gate.
- Mug works within ~2-3 weeks -> roll out the list above and aim at ICCV 2027 (deadline ~2027-03-08, not announced).
- Mug stuck for more than a month, or only 2-3 objects ever work -> no ICCV submission; put the real results into
  the SGP paper as a section, or target 3DV / WACV.
- The SGP audit paper proceeds either way; the DMesh++ 0/37 result is its first external data point.

### Immediate next steps
1. Try the existing real/mug, real/mug2 captures with the current chain (strict repair + health check) to see
   where it breaks.
2. New turntable capture of the mug per the requirements above (Boss).
3. In parallel: audit figures for the SGP paper from the 37 DMesh++ outputs.
