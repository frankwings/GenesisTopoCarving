#!/usr/bin/env python3
"""check_mono_normal.py <scene_dir> <mesh.npz>: angular agreement between a reconstructed mesh's rendered normals and
the MoGe normal targets real_scene loads (GL camera frame), on pixels both call foreground.
Prints the median/mean angle for the loaded convention and for every axis-sign variant (the loaded one must win by a
wide margin, otherwise the frame conversion is wrong), plus a 'facing camera' (0,0,1) baseline."""
import os, sys, itertools, numpy as np, torch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike"))
os.environ.setdefault("TRAIN_RES", "512")
from real_scene import load_real_scene
import run_64v, nvdiffrast.torch as dr
from scipy.ndimage import binary_erosion

sc = load_real_scene(sys.argv[1]); z = np.load(sys.argv[2])
dev = sc.device; ctx = dr.RasterizeCudaContext()
vt = torch.tensor(z["verts"], dtype=torch.float32, device=dev); ft = torch.tensor(z["tris"], dtype=torch.int32, device=dev)
assert run_64v.TRAIN_RES == sc.res, (run_64v.TRAIN_RES, sc.res)
P, G = [], []
with torch.no_grad():
    for i in range(len(sc.mvps)):
        r = run_64v.render_normals(ctx, vt, ft, sc.mvps[i], sc.views[i]).cpu().numpy()
        rn = np.linalg.norm(r, axis=-1)
        m = (rn > 0.5) & binary_erosion(sc.gt[i] < 128, iterations=3) & (np.linalg.norm(sc.nrm[i], axis=-1) > 0.5)
        P.append(r[m] / rn[m, None]); G.append(sc.nrm[i][m])
P = np.concatenate(P); G = np.concatenate(G)
def ang(a, b): return np.degrees(np.arccos(np.clip((a * b).sum(-1), -1, 1)))
for sg in itertools.product((1, -1), repeat=3):
    a = ang(P, G * np.array(sg, np.float32)); tag = " <- loaded" if sg == (1, 1, 1) else ""
    print(f"sign {sg}: median {np.median(a):6.1f} mean {a.mean():6.1f} deg{tag}")
a = ang(P, np.array([0, 0, 1], np.float32)[None]); print(f"baseline facing-camera: median {np.median(a):.1f} mean {a.mean():.1f}")
print(f"pixels {len(P)}")
