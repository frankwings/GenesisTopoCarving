# Baselines on the 96 oracle-usable Thingi10K models — 2026-10-22

Same inputs, same scorer (`compare_dmesh2` metrics: closed / components / genus / Chamfer / volume IoU), GT genus from
the model. Point-cloud methods get 60k blue-noise surface samples with exact face normals of the GT; image methods get
our 64 star cameras (ours: silhouettes; NeuS: Lambertian RGB renders + masks, `export_neus_views.py`).

| method | topology source | input | closed | single comp | **strict genus** | Chamfer med | vol IoU med | notes |
|---|---|---|---|---|---|---|---|---|
| RsR (Cui et al., TOG 2024) | combinatorial: explicit handle edges, n-threshold | points + normals | 3/96 | 61/96 | **3/96** (10/96 holes filled) | **0.0071** | **0.990** | keeps the points; ~183 boundary edges median; GT genus prior does not help (3/96) |
| SAP (Peng et al., NeurIPS 2021) | emerges: Poisson level set | points + normals | 76/96 | 53/96 | **35/96 (36 %)** | 0.0079 | 0.971 | 9 with spurious handles (up to +14), 6 missing, 29 shattered (>= 9 comps) |
| DMesh++ (ICCV 2025) | emerges: point existence | 64 views | 0/96 | — | — | 0.0096 | 0.837 | soup, STATUS_2026-10-17 |
| NeuS (instant-nsr-pl, NeurIPS 2021) | emerges: SDF level set | 64 RGB views + masks | pending | | | | | batch running (10k steps, finite-difference SDF grad) |
| **Topo-Carving v7.2 (ours)** | **discovered + verified** | 64 silhouettes | **96/96** | 96/96 | **71/96 (74 %)** | 0.0126 | 0.880 | strict linking audit, oracle refusal |

Reading: the point/combinatorial methods reproduce the surface more accurately than we do (they keep the points) but
do not deliver the right closed topology; SAP is the strongest of them and still gets the genus right only a third of
the time, with no way to tell a spurious Poisson handle from a real tunnel. Ours trades Chamfer for a verified genus.

## GIFs (GT | ours | SAP | RsR | NeuS when available), `baselines_gifs/<shape>.gif`
| shape (GT genus) | ours | SAP | RsR | why it is here |
|---|---|---|---|---|
| kitten (1) | genus 1 | genus 1 | open | the easy case: everyone but RsR |
| fertility (4) | genus 4 | 100 components | genus 4 (closed!) | RsR's best case: dense clean samples of a smooth scan |
| t10k_91610 (2) | genus 2 | genus 13 | open | SAP spurious handles |
| t10k_1158268 (2) | genus 0 (ours fails too) | genus 16 | open | hard model: SAP +14 handles, ours misses both |
| t10k_399567 (3) | genus 3 | genus 0 | open | SAP smooths the tunnels shut |
| t10k_135074 (1) | genus 1 | 830 components | open | thin parts shatter in SAP |

Per-model data: `rsr/rsr_*.jsonl`, `sap/sap.jsonl`, `dmesh2/compare_*.jsonl`, `neus/neus_syn.jsonl` (pending).
Docs: `GenesisExp/GenesisRsR/docs/20261022_RsR_results.md`, `GenesisExp/GenesisSAP/docs/20261022_SAP_results.md`,
`GenesisExp/NoCode/20261022_NeuS_summary.md`. Script: `despike/make_baseline_gifs.py`.
