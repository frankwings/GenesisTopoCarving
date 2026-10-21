#!/usr/bin/env python3
"""make_syn_scene.py <scene_dir> <mesh.npz (normalised frame)> <out_scene_dir> [--taubin N]

Controlled experiment (2026-10-19, kettle "diagonal ridges"): build a copy of a real scene whose masks are exact
renders of a known smooth mesh through the SAME COLMAP cameras. Same images, poses, crops, normalisation -> any
artifact the chain still produces is the method's (silhouette-only optimisation), not pose/mask inconsistency.
The normalisation X, s is recomputed exactly as real_scene does, from the ORIGINAL masks; the new masks are close
enough that real_scene recomputes nearly the same frame (printed for checking)."""
import os, sys, shutil, argparse, numpy as np, torch, cv2, pycolmap, trimesh
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike"))
import real_scene as rs
import nvdiffrast.torch as dr

ap = argparse.ArgumentParser(); ap.add_argument("scene"); ap.add_argument("mesh"); ap.add_argument("out")
ap.add_argument("--taubin", type=int, default=200); a = ap.parse_args()
sd = os.path.abspath(a.scene); od = os.path.abspath(a.out)
rec = pycolmap.Reconstruction(sd + "/sparse/0"); cam = list(rec.cameras.values())[0]; f, cx, cy = cam.params[:3]
W, H = int(cam.width), int(cam.height)
ims = sorted(rec.images.values(), key=lambda i: i.name)
masks = [cv2.imread(f"{sd}/masks_sam2/{os.path.splitext(im.name)[0]}.png", 0) for im in ims]
dirs, origs = [], []
for im, m in zip(ims, masks):
    c = im.cam_from_world(); d, o = rs._mask_centroid_ray(m, c.rotation.matrix(), c.translation, f, cx, cy)
    if d is not None: dirs.append(d); origs.append(o)
X = rs._ray_intersection(dirs, origs); rv = []
for im, m in zip(ims, masks):
    ys, xs = np.where(m > 127)
    if len(ys) == 0: continue
    c = im.cam_from_world(); C = -c.rotation.matrix().T @ c.translation
    rv.append(np.linalg.norm(C - X) * 0.5 * max(np.ptp(xs), np.ptp(ys)) / f)
s = float(np.median(rv)) / 0.8
z = np.load(a.mesh); tm = trimesh.Trimesh(z["verts"].astype(np.float64), z["tris"], process=False)
if a.taubin > 0: trimesh.smoothing.filter_taubin(tm, iterations=a.taubin)
print(f"[syn] X={np.round(X, 4)} s={s:.5f} mesh V={len(tm.vertices)} taubin={a.taubin}", flush=True)
for d in ("images", "sparse"): shutil.copytree(f"{sd}/{d}", f"{od}/{d}", dirs_exist_ok=True)
for fn in ("frame_map.npy",):
    if os.path.exists(f"{sd}/{fn}"): shutil.copy(f"{sd}/{fn}", od)
os.makedirs(f"{od}/masks_sam2", exist_ok=True)
np.savez(f"{od}/gt_mesh_norm.npz", verts=np.asarray(tm.vertices, np.float32), tris=np.asarray(tm.faces, np.int32))
dev = "cuda"; ctx = dr.RasterizeCudaContext()
Vt = torch.tensor(np.asarray(tm.vertices), dtype=torch.float32, device=dev); Ft = torch.tensor(np.asarray(tm.faces), dtype=torch.int32, device=dev)
for im in ims:
    c = im.cam_from_world(); R = torch.tensor(c.rotation.matrix(), dtype=torch.float32, device=dev)
    te = torch.tensor((c.rotation.matrix() @ X + c.translation) / s, dtype=torch.float32, device=dev)
    Xc = Vt @ R.T + te; x, y, zc = Xc[:, 0], Xc[:, 1], Xc[:, 2]; near, far = 0.05, 100.0
    clip = torch.stack([(2 * f / W) * x + (2 * cx / W - 1) * zc, (2 * f / H) * y + (2 * cy / H - 1) * zc,
                        zc * (far + near) / (far - near) - 2 * far * near / (far - near), zc], -1)
    rast, _ = dr.rasterize(ctx, clip[None].contiguous(), Ft, resolution=[H, W])
    m = ((rast[0, :, :, 3] > 0).cpu().numpy() * 255).astype(np.uint8)    # row index == image row (see bake_vertex_colors)
    cv2.imwrite(f"{od}/masks_sam2/{os.path.splitext(im.name)[0]}.png", m)
shutil.copytree(f"{od}/masks_sam2", f"{od}/masks", dirs_exist_ok=True)
print(f"[syn] wrote {len(ims)} masks -> {od}", flush=True)
