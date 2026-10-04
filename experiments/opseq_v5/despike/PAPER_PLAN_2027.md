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
