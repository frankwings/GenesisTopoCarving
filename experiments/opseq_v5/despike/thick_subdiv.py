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


def local_thickness_grid(hull, sp, r_max_vox=48):
    """hull: bool [n,n,n] (True inside); sp: voxel spacing per axis (world). Returns L [n,n,n] in world units (0 outside
    the hull) = 2 x radius of the largest inscribed ball covering the voxel (Hildebrand & Ruegsegger local thickness).
    2026-10-13: exact per integer radius. A voxel is covered by a ball of radius >= r iff its distance to the set
    {din >= r} is <= r, so L = 2 x max r with EDT(~{din >= r}) <= r. The previous max-filter ladder propagated each
    ball centre only within a Chebyshev box of the next LOWER ladder radius, which under-estimated a 0.19-thick wall
    as 0.07 and made THICK_SUBDIV refine whole models (1681123: 962 -> 30k vertices, Stage 3 wrecked)."""
    sp = np.asarray(sp, float); pitch = float(np.max(sp))
    # the hull grid is nres^3 over the object's bbox, so a flat part has 5x finer voxels along its thin axis
    # (1681123: sp = 0.0128, 0.0128, 0.0025). Work on an isotropic grid at the coarsest spacing (integer strides),
    # then expand back - the per-radius test below needs isotropic voxel distances.
    k = np.maximum(1, np.rint(pitch / sp).astype(int)); h = hull[::k[0], ::k[1], ::k[2]]
    din = distance_transform_edt(h, sampling=(pitch, pitch, pitch)).astype(np.float32)   # inside distance to boundary (world)
    rvox = din / pitch
    L = np.zeros(h.shape, np.float32)
    r = 1
    while r <= r_max_vox:
        centres = rvox >= r
        if not centres.any(): break
        d = distance_transform_edt(~centres)                                   # voxel units, isotropic now
        L[d <= r] = 2.0 * r * pitch
        r += 1 if r < 12 else 2
    L = L * h
    for ax in range(3):                                                        # expand back to the original grid
        if k[ax] > 1: L = np.repeat(L, k[ax], axis=ax)
    L = L[:hull.shape[0], :hull.shape[1], :hull.shape[2]]
    if L.shape != hull.shape:                                                  # strided grid shorter than the original: pad by edge
        L = np.pad(L, [(0, hull.shape[i] - L.shape[i]) for i in range(3)], mode="edge")
    return L * hull


def thickness_at(L, lo, hi, pts, _cache={}):
    """Nearest-voxel lookup of L at world points. Points outside the hull (DR vertices sit a little outside, spikes
    far outside) take the thickness of the NEAREST inside voxel (EDT feature transform), never 0."""
    key = (id(L), L.shape, float(L.sum()))      # id alone can be recycled after a free (stale field for the next shape)
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


def thickness_subdivide(V, Fa, thick_fn, ratio=1.0, rounds=2, max_v=30000, log=print, ratio_thin=None, thin=0.08):
    """Subdivide faces whose mean edge exceeds ratio x local thickness. thick_fn(V) -> per-vertex thickness.
    ratio_thin / thin (2026-10-14): faces thinner than `thin` (absolute, world units) use ratio_thin instead - a 0.05
    plate needs edge <= thickness (ratio 1: 81291 lost a thin bar between two holes at ratio 2, 4/5), a 0.18 part
    only needs the cc4 edge below the wall (ratio 2: 1681123 refined whole at ratio 1 and Stage 3 broke).
    Returns (V, Fa, n_faces_split_per_round)."""
    from phase1c_pipeline import dlfl_subdivide_arrays
    V = np.asarray(V, float); Fa = np.asarray(Fa, np.int64); hist = []
    for r in range(rounds):
        th = thick_fn(V); tc = thick_fn(V[Fa].mean(1))
        # 2026-10-13: per-face thickness = median of the three vertices and the centroid (was the vertex minimum: on a
        # coarse, spiky cc3 mesh one vertex that lands next to a thin fin dragged every face around it into refinement)
        tf = np.median(np.stack([th[Fa[:, 0]], th[Fa[:, 1]], th[Fa[:, 2]], tc]), axis=0)
        e = (np.linalg.norm(V[Fa[:, 0]] - V[Fa[:, 1]], axis=1) + np.linalg.norm(V[Fa[:, 1]] - V[Fa[:, 2]], axis=1)
             + np.linalg.norm(V[Fa[:, 2]] - V[Fa[:, 0]], axis=1)) / 3.0
        rr = np.full(len(Fa), float(ratio))
        if ratio_thin is not None: rr[tf < thin] = float(ratio_thin)
        sel = np.flatnonzero((tf > 0) & (e > rr * tf))
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
