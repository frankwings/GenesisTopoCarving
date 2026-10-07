"""Thickness-aware adaptive subdivision at the coarse stage (2026-10-05, option 1 of the thin-wall plan).

Thin walls (Thingi10K plates, wall 0.03-0.1 in a [-1,1] scene) are lost because the coarse icosphere
(edge 0.14-0.27 at cc3) is far coarser than the wall: the two sides interpenetrate during DR (SI 60-77%
entering Stage 5) and no later stage recovers. The fix refines the coarse mesh WHERE the object is thin,
before the sides can cross, using only the 64 training silhouettes (visual hull), no GT.

  local thickness L(x) = diameter of the largest hull-inscribed ball that covers x (Hildebrand & Ruegsegger)
  approximated on the hull grid by multi-scale max filters of the inside EDT.
  a face is subdivided (DLFL subdivide_edge + stellate, 1-ring expanded) while mean edge > THICK_RATIO x min
  vertex thickness, for at most THICK_ROUNDS rounds and THICK_MAX_V vertices.
"""
import os, numpy as np
from scipy.ndimage import distance_transform_edt, maximum_filter


def local_thickness_grid(hull, sp, radii_vox=(1, 2, 3, 4, 6, 8, 12, 16, 24, 32)):
    """hull: bool [n,n,n] (True inside); sp: voxel spacing per axis (world). Returns L [n,n,n] in world units
    (0 outside the hull) = 2 x radius of the largest inscribed ball covering the voxel (Chebyshev approximation)."""
    din = distance_transform_edt(hull, sampling=tuple(sp)).astype(np.float32)   # inside distance to boundary
    pitch = float(np.max(sp)); L = din.copy()
    for r in radii_vox:
        cand = np.where(din >= r * pitch, din, 0.0).astype(np.float32)        # balls of radius >= r
        if not cand.any(): break
        L = np.maximum(L, maximum_filter(cand, size=2 * r + 1))              # cover every voxel within r
    return 2.0 * L * hull


def thickness_at(L, lo, hi, pts, _cache={}):
    """Nearest-voxel lookup of L at world points. Points outside the hull (DR vertices sit a little outside, spikes
    far outside) take the thickness of the NEAREST inside voxel (EDT feature transform), never 0."""
    key = id(L)
    if key not in _cache:
        _cache.clear()
        inside = L > 0
        _, idx = distance_transform_edt(~inside, return_indices=True)
        _cache[key] = L[idx[0], idx[1], idx[2]]          # L propagated to every voxel from its nearest inside voxel
    Ln = _cache[key]
    n = np.asarray(L.shape); lo = np.asarray(lo, float); hi = np.asarray(hi, float)
    idx = np.rint((np.asarray(pts, float) - lo) / (hi - lo) * (n - 1)).astype(int)
    idx = np.clip(idx, 0, n - 1)
    return Ln[idx[:, 0], idx[:, 1], idx[:, 2]]


def equalize_subdivide(V, Fa, target_edge, log=print):
    """Stage-4 replacement of the global cc4 round when the coarse mesh was already thickness-refined: split only
    the faces whose mean edge is still above target_edge (DLFL, 1-ring expanded). Returns (V, Fa, n_split)."""
    from phase1c_pipeline import dlfl_subdivide_arrays
    V = np.asarray(V, float); Fa = np.asarray(Fa, np.int64)
    e = (np.linalg.norm(V[Fa[:, 0]] - V[Fa[:, 1]], axis=1) + np.linalg.norm(V[Fa[:, 1]] - V[Fa[:, 2]], axis=1)
         + np.linalg.norm(V[Fa[:, 2]] - V[Fa[:, 0]], axis=1)) / 3.0
    sel = np.flatnonzero(e > target_edge)
    if len(sel) == 0:
        log(f"[thick] equalize: no face above target edge {target_edge:.3f}"); return V, Fa, 0
    V2, F2, ne = dlfl_subdivide_arrays(V, Fa, sel.tolist())
    log(f"[thick] equalize: {len(sel)}/{len(Fa)} faces with edge > {target_edge:.3f} (edge p50/p90 {np.median(e):.3f}/{np.percentile(e, 90):.3f}) "
        f"-> split {ne} edges, V {len(V)} -> {len(V2)}, F {len(Fa)} -> {len(F2)}")
    return np.asarray(V2, float), np.asarray(F2, np.int64), int(len(sel))


def thickness_subdivide(V, Fa, thick_fn, ratio=1.0, rounds=2, max_v=30000, log=print):
    """Subdivide faces whose mean edge exceeds ratio x local thickness. thick_fn(V) -> per-vertex thickness.
    Returns (V, Fa, n_faces_split_per_round)."""
    from phase1c_pipeline import dlfl_subdivide_arrays
    V = np.asarray(V, float); Fa = np.asarray(Fa, np.int64); hist = []
    for r in range(rounds):
        th = thick_fn(V)
        tf = np.minimum.reduce([th[Fa[:, 0]], th[Fa[:, 1]], th[Fa[:, 2]]])
        e = (np.linalg.norm(V[Fa[:, 0]] - V[Fa[:, 1]], axis=1) + np.linalg.norm(V[Fa[:, 1]] - V[Fa[:, 2]], axis=1)
             + np.linalg.norm(V[Fa[:, 2]] - V[Fa[:, 0]], axis=1)) / 3.0
        sel = np.flatnonzero((tf > 0) & (e > ratio * tf))
        if len(sel) == 0:
            log(f"[thick] round {r}: no face coarser than {ratio} x local thickness (thick p10/50 = "
                f"{np.percentile(th[th > 0], 10) if (th > 0).any() else 0:.3f}/{np.median(th[th > 0]) if (th > 0).any() else 0:.3f}, edge med {np.median(e):.3f})"); break
        budget = int((max_v - len(V)) / 2.5)            # a split face (+1-ring) adds ~2.5 verts
        if budget <= 0:
            log(f"[thick] round {r}: {len(sel)} faces still too coarse but V={len(V)} >= THICK_MAX_V={max_v}; stop"); break
        if len(sel) > budget:                            # thinnest faces first within the vertex budget
            sel = sel[np.argsort(tf[sel] / e[sel])[:budget]]
            log(f"[thick] round {r}: vertex budget {max_v} -> only the {budget} thinnest faces")
        V2, F2, ne = dlfl_subdivide_arrays(V, Fa, sel.tolist())
        log(f"[thick] round {r}: {len(sel)}/{len(Fa)} faces with edge > {ratio} x thickness (thin thick med "
            f"{np.median(tf[sel]):.3f}, edge med {np.median(e[sel]):.3f}) -> split {ne} edges, V {len(V)} -> {len(V2)}, F {len(Fa)} -> {len(F2)}")
        V, Fa = np.asarray(V2, float), np.asarray(F2, np.int64); hist.append(int(len(sel)))
    return V, Fa, hist
