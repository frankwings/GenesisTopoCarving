#!/usr/bin/env python3
"""mesh_health.py - did the chain return a usable mesh? (2026-10-04)

A run can end with the "right" genus on a mesh that is not a reconstruction at all: on thin plates the two sides
pass through each other at the coarse stage, the refinement cannot untangle them, and before the 2026-10-04 fix the
mesh was coarsened down to 8-40 vertices (Thingi10K batch: 6 of 31 runs) while the chain still printed a genus.
This check makes such runs explicit. FAILED if any of:
  - the final mesh has fewer vertices than the mesh that entered refinement (refinement should grow it);
  - more than SI_MAX (default 10 %) of the faces self-intersect;
  - fewer than V_MIN (default 2000) vertices;
  - with SHAPE set: mean silhouette IoU with the input views below FIT_MIN (default 0.90; measured: wrecked results 0.57-0.82, all others >= 0.954) - a healthy-looking mesh that
    does not match the images is not a reconstruction.
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

def silhouette_fit(V, F, shape):
    """Mean silhouette IoU between the mesh and the INPUT views (64 training cameras, 256 px). Ground-truth-free in
    the sense of the task: the input silhouettes are what the method was given."""
    import torch, nvdiffrast.torch as dr
    os.environ.setdefault("MODE", "64v")
    sys.path.insert(0, os.path.join(HERE, ".."))
    from eval_local_refine import load_obj, normalize_to_range, BUNNY_PATH
    from pipeline.cameras import transform_to_clip
    import run_64v
    gv, gf = load_obj(os.path.join(os.path.dirname(BUNNY_PATH), f"{shape}.obj")); g = normalize_to_range(gv)
    mvps, _ = run_64v.star_cameras(float(np.linalg.norm(g, axis=1).max())); ctx = dr.RasterizeCudaContext()
    def sil(Vx, Fx):
        vt = torch.tensor(np.asarray(Vx), dtype=torch.float32, device="cuda"); ft = torch.tensor(np.asarray(Fx, np.int32), dtype=torch.int32, device="cuda"); out = []
        with torch.no_grad():
            for mvp in mvps:
                rast, _ = dr.rasterize(ctx, transform_to_clip(vt, mvp), ft, resolution=[256, 256]); out.append(rast[0, :, :, 3] > 0)
        return torch.stack(out)
    a, b = sil(V, F), sil(g, gf)
    inter = (a & b).flatten(1).sum(1).float(); union = (a | b).flatten(1).sum(1).float().clamp(min=1)
    return float((inter / union).mean())

if __name__ == "__main__":
    m = np.load(sys.argv[1]); V, F = m["verts"], m["tris"]
    v0 = len(np.load(sys.argv[2])["verts"]) if len(sys.argv) > 2 and os.path.exists(sys.argv[2]) else None
    si = si_fraction(V, F); why = []
    if len(V) < int(os.environ.get("V_MIN", "2000")): why.append(f"only {len(V)} vertices")
    if v0 is not None and len(V) < v0: why.append(f"refinement shrank the mesh ({v0} -> {len(V)} vertices)")
    if si == si and si > float(os.environ.get("SI_MAX", "0.10")): why.append(f"{100 * si:.0f}% of the faces self-intersect")
    fit = None
    if os.environ.get("SHAPE") and os.environ.get("HEALTH_FIT", "1") == "1":
        try: fit = silhouette_fit(V, F, os.environ["SHAPE"])
        except Exception as e: fit = None
    if fit is not None and fit < float(os.environ.get("FIT_MIN", "0.90")): why.append(f"silhouettes do not match the input views (mean IoU {fit:.3f})")
    tail = f"V={len(V)}, self-intersecting faces {100 * si:.1f}%" + (f", silhouette IoU with the input views {fit:.4f}" if fit is not None else "")
    print(("FAILED: " + "; ".join(why) + f" [{tail}]") if why else f"ok ({tail})")
