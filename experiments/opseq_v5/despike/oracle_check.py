#!/usr/bin/env python3
"""oracle_check.py - is the space-carving oracle trustworthy for this shape? (2026-10-04)

The whole pipeline rests on the carved hull: its genus is the tunnel count g*, its air is the evidence for every
handle, its tunnels define the audit. The hull is only a superset of the object. When the object has thin walls or
concavities no silhouette can see (heptoroid: hull = 1.9x the object's volume) the hull's topology is not the
object's, and the hull genus does not settle under morphological closing/opening.

Test (ground-truth-free, silhouettes only): genus of the hull after closing+opening with radius r = 1..6.
STABLE  <=>  three consecutive radii give the same genus, and that plateau equals the pipeline's g*.
Measured (2026-10-04, r = 1..6):
    armadillo  [1, 0, 0, 0, 0, 0]   kitten    [1, 1, 1, 1, 1, 1]   rockerarm [1, 1, 1, 1, 1, 1]
    threeholes [9, 4, 3, 3, 3, 3]   fertility [4, 4, 4, 4, 4, 4]   botijo    [5, 5, 5, 4, 4, 2]   -> stable
    heptoroid  [40, 31, 44, 45, 31, 5]                                                              -> UNSTABLE
(Small radii can show noise handles, large radii close real small tunnels - hence a plateau, not "all equal":
"all three of r = 1, 2, 3 equal" would wrongly refuse armadillo and threeholes.)
golden_chain.sh refuses unstable shapes instead of producing a collapsed mesh (ORACLE_CHECK=0 to force).

Usage: SHAPE=fertility python3 despike/oracle_check.py   -> "stable <g> [per-radius list]" or "unstable [list]"
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("MODE", "64v")
import numpy as np

def check(shape):
    import nvdiffrast.torch as dr
    from eval_local_refine import load_obj, normalize_to_range, BUNNY_PATH
    from hull_field import build_vote_hull, hull_genus
    import run_64v
    gv, gf = load_obj(os.path.join(os.path.dirname(BUNNY_PATH), f"{shape}.obj")); g = normalize_to_range(gv)
    mvps, _ = run_64v.star_cameras(float(np.linalg.norm(g, axis=1).max())); ctx = dr.RasterizeCudaContext()
    HF = build_vote_hull(ctx, mvps, g, gf, None, "cuda", nres=256, hires=int(os.environ.get("HULL_HIRES", "512")), vote=2)   # same hull as phase7_handle
    hull = HF.hull.cpu().numpy() if hasattr(HF.hull, "cpu") else np.asarray(HF.hull)
    gstar, _ = hull_genus(hull)                                   # the pipeline's g* (radii 1, 2, 3)
    _, per = hull_genus(hull, radii=(1, 2, 3, 4, 5, 6)); vals = list(per.values())
    plateau = next((vals[i] for i in range(len(vals) - 2) if vals[i] == vals[i + 1] == vals[i + 2]), None)
    return plateau is not None and plateau == gstar, gstar, vals

if __name__ == "__main__":
    ok, gp, per = check(os.environ.get("SHAPE", "fertility"))
    print(f"stable {gp} {per}" if ok else f"unstable {per}")
