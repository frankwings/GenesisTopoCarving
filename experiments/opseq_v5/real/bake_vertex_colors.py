#!/usr/bin/env python3
"""bake_vertex_colors.py <scene_dir> <mesh.npz> <out.npz> [--subdiv N] [--exclude a.jpg,b.jpg]

Projection-bake photo colours onto a golden-chain mesh (normalised frame) of a real capture.
For every view: rasterise the mesh with the COLMAP camera (nvdiffrast, full photo resolution) to get a depth
buffer, keep vertices that are visible (depth test), front-facing and inside the (eroded) SAM2 mask, and
accumulate the photo pixel with weight facing^3. Output npz: verts, tris, colors (float RGB in [0,1]).
The normalisation (X, s) is recomputed exactly as real_scene.RealScene does (mask-centroid rays, mask-bbox radius),
so REAL_EXCLUDE / --exclude must match the run that produced the mesh."""
import os, sys, argparse, numpy as np, torch, cv2, pycolmap, trimesh
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike"))
import real_scene as rs
import nvdiffrast.torch as dr

ap = argparse.ArgumentParser(); ap.add_argument("scene"); ap.add_argument("mesh"); ap.add_argument("out")
ap.add_argument("--subdiv", type=int, default=1); ap.add_argument("--exclude", default=os.environ.get("REAL_EXCLUDE", ""))
ap.add_argument("--tol", type=float, default=0.02, help="depth-test tolerance (normalised units)")
a = ap.parse_args()
sd = os.path.abspath(a.scene)
rec = pycolmap.Reconstruction(sd + "/sparse/0"); cam = list(rec.cameras.values())[0]; f, cx, cy, _ = cam.params
W, H = int(cam.width), int(cam.height)
ims = sorted(rec.images.values(), key=lambda i: i.name)
excl = set(x for x in a.exclude.split(",") if x); ims = [im for im in ims if im.name not in excl]
masks = [cv2.imread(f"{sd}/masks_sam2/{os.path.splitext(im.name)[0]}.png", 0) for im in ims]

# --- normalisation, identical to real_scene ---
dirs, origs = [], []
for im, m in zip(ims, masks):
    c = im.cam_from_world(); d, o = rs._mask_centroid_ray(m, c.rotation.matrix(), c.translation, f, cx, cy)
    if d is not None: dirs.append(d); origs.append(o)
X = rs._ray_intersection(dirs, origs)
rv = []
for im, m in zip(ims, masks):
    ys, xs = np.where(m > 127)
    if len(ys) == 0: continue
    c = im.cam_from_world(); C = -c.rotation.matrix().T @ c.translation
    rv.append(np.linalg.norm(C - X) * 0.5 * max(np.ptp(xs), np.ptp(ys)) / f)
s = float(np.median(rv)) / 0.8
print(f"[bake] {len(ims)} views, X={np.round(X, 4)} s={s:.5f}", flush=True)

z = np.load(a.mesh); V, Fa = z["verts"].astype(np.float64), z["tris"].astype(np.int64)
for _ in range(a.subdiv): V, Fa = trimesh.remesh.subdivide(V, Fa)
tm = trimesh.Trimesh(V, Fa, process=False); VN = np.asarray(tm.vertex_normals)
print(f"[bake] mesh V={len(V)} F={len(Fa)}", flush=True)

dev = "cuda"; ctx = dr.RasterizeCudaContext()
Vt = torch.tensor(V, dtype=torch.float32, device=dev); Ft = torch.tensor(Fa, dtype=torch.int32, device=dev)
acc = torch.zeros(len(V), 3, device=dev); wsum = torch.zeros(len(V), device=dev); nseen = torch.zeros(len(V), device=dev)
VNt = torch.tensor(VN, dtype=torch.float32, device=dev)
for k, (im, m) in enumerate(zip(ims, masks)):
    c = im.cam_from_world(); R = torch.tensor(c.rotation.matrix(), dtype=torch.float32, device=dev)
    te = torch.tensor((c.rotation.matrix() @ X + c.translation) / s, dtype=torch.float32, device=dev)
    Xc = Vt @ R.T + te                                   # camera coords (OpenCV), normalised units
    x, y, zc = Xc[:, 0], Xc[:, 1], Xc[:, 2]
    near, far = 0.05, 100.0
    clip = torch.stack([(2 * f / W) * x + (2 * cx / W - 1) * zc,
                        (2 * f / H) * y + (2 * cy / H - 1) * zc,
                        zc * (far + near) / (far - near) - 2 * far * near / (far - near), zc], -1)
    rast, _ = dr.rasterize(ctx, clip[None].contiguous(), Ft, resolution=[H, W])
    zbuf, _ = dr.interpolate(zc[None, :, None].contiguous(), rast, Ft)
    zbuf = zbuf[0, :, :, 0]; cov = rast[0, :, :, 3] > 0     # row index == image row v (ndc y = 2v/H - 1)
    u = (f * x / zc + cx); v = (f * y / zc + cy); ui = u.round().long(); vi = v.round().long()
    inb = (zc > 0) & (ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
    uc, vc = ui.clamp(0, W - 1), vi.clamp(0, H - 1)
    vis = inb & cov[vc, uc] & ((zbuf[vc, uc] - zc).abs() < a.tol)
    C = -(R.T @ te)                                       # camera centre (normalised)
    view = C[None] - Vt; view = view / (view.norm(dim=1, keepdim=True) + 1e-9)
    facing = (VNt * view).sum(1); vis &= facing > 0.2
    me = cv2.erode((m > 127).astype(np.uint8), np.ones((7, 7), np.uint8))
    vis &= torch.tensor(me, device=dev, dtype=torch.bool)[vc, uc]
    ph = torch.tensor(cv2.imread(f"{sd}/images/{os.path.splitext(im.name)[0]}.jpg")[:, :, ::-1].copy(), device=dev).float() / 255
    # bilinear sample
    jj = torch.where(vis)[0]
    if len(jj) == 0: continue
    uu, vv = u[jj].clamp(0, W - 1.001), v[jj].clamp(0, H - 1.001); u0, v0 = uu.floor().long(), vv.floor().long(); du, dv = (uu - u0)[:, None], (vv - v0)[:, None]
    col = (ph[v0, u0] * (1 - du) * (1 - dv) + ph[v0, u0 + 1] * du * (1 - dv) + ph[v0 + 1, u0] * (1 - du) * dv + ph[v0 + 1, u0 + 1] * du * dv)
    w = facing[jj] ** 3
    acc[jj] += col * w[:, None]; wsum[jj] += w; nseen[jj] += 1
good = wsum > 0
cols = torch.full((len(V), 3), 0.5, device=dev); cols[good] = acc[good] / wsum[good, None]
# fill unseen vertices by neighbour diffusion
cols_np = cols.cpu().numpy(); good_np = good.cpu().numpy()
if (~good_np).any():
    nb = tm.vertex_neighbors
    for _ in range(50):
        bad = np.where(~good_np)[0]
        if len(bad) == 0: break
        newly = []
        for i in bad:
            g = [j for j in nb[i] if good_np[j]]
            if g: cols_np[i] = cols_np[g].mean(0); newly.append(i)
        if not newly: break
        good_np[newly] = True
print(f"[bake] seen {good.float().mean().item()*100:.1f}% of vertices, median views/vertex {nseen[good].median().item():.0f}", flush=True)
np.savez_compressed(a.out, verts=V.astype(np.float32), tris=Fa.astype(np.int32), colors=cols_np.astype(np.float32))
trimesh.Trimesh(V, Fa, vertex_colors=(np.clip(cols_np, 0, 1) * 255).astype(np.uint8), process=False).export(a.out.replace(".npz", ".ply"))
print(f"[bake] saved {a.out} (+ .ply)", flush=True)
