#!/usr/bin/env python3
"""mesh_health.py - did the chain return a usable mesh? (2026-10-04)

A run can end with the "right" genus on a mesh that is not a reconstruction at all: on thin plates the two sides
pass through each other at the coarse stage, the refinement cannot untangle them, and before the 2026-10-04 fix the
mesh was coarsened down to 8-40 vertices (Thingi10K batch: 6 of 31 runs) while the chain still printed a genus.
This check makes such runs explicit. FAILED if any of:
  - the final mesh has fewer vertices than the mesh that entered refinement (refinement should grow it);
  - more than SI_MAX (default 10 %) of the faces self-intersect;
  - fewer than V_MIN (default 2000) vertices.
Usage: python3 despike/mesh_health.py final.npz [before_refine.npz]   -> "ok ..." or "FAILED ..."
"""
import sys, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

def si_fraction(V, F):
    try:
        from topmod import core_backend as cb
        prs = np.asarray(cb.si_faces(np.asarray(V, float), np.asarray(F, np.int64)))
        return len(np.unique(prs)) / max(len(F), 1) if prs.size else 0.0
    except Exception:
        return float("nan")

if __name__ == "__main__":
    m = np.load(sys.argv[1]); V, F = m["verts"], m["tris"]
    v0 = len(np.load(sys.argv[2])["verts"]) if len(sys.argv) > 2 and os.path.exists(sys.argv[2]) else None
    si = si_fraction(V, F); why = []
    if len(V) < int(os.environ.get("V_MIN", "2000")): why.append(f"only {len(V)} vertices")
    if v0 is not None and len(V) < v0: why.append(f"refinement shrank the mesh ({v0} -> {len(V)} vertices)")
    if si == si and si > float(os.environ.get("SI_MAX", "0.10")): why.append(f"{100 * si:.0f}% of the faces self-intersect")
    print(("FAILED: " + "; ".join(why)) if why else f"ok (V={len(V)}, self-intersecting faces {100 * si:.1f}%)")
