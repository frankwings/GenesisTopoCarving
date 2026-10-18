"""depth_carve.py <dataset_dir> <stray_src> : free-space carving with the iPhone LiDAR depth (v8 oracle, 2026-10-17).
A voxel is EMPTY if some depth ray passes through it before hitting a surface; everything never proven empty stays solid,
then the result is clipped to the (permissive) silhouette hull and to the half-space above the support plane.
Why: fusing LiDAR points as occupancy gave the mug a tube through the body (its floor and underside are never measured)
and filled the handle hole - right genus, wrong tunnel. Carving gets both right in principle: the cup interior is seen ->
empty pocket open at the top; the underside is never seen -> solid; rays through the handle hole hit the table -> hole carved.
Writes <dataset_dir>/depth_hull.npz (hull, lo, hi) in the normalised scene frame (LIDAR_HULL input of real_scene)."""
import sys, os, numpy as np, cv2, torch, pycolmap
from scipy import ndimage; from skimage import measure
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike")); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
D, src = sys.argv[1], sys.argv[2]; dev = "cuda"
# MARGIN: the iPhone LiDAR reads 7-17 mm behind the silhouette-fitted surface on this glazed mug, so rays stop well short of it
NC = int(os.environ.get("DC_RES", "128")); STRIDE = int(os.environ.get("DC_STRIDE", "1")); MARGIN = float(os.environ.get("DC_MARGIN", "0.02")); CONF = int(os.environ.get("DC_CONF", "1"))
os.environ.pop("LIDAR_HULL", None); os.environ["REAL_DATA"] = D
from real_scene import load_real_scene
sc = load_real_scene(D, dev); X = np.asarray(sc.X, float); s = float(sc.s); lo = np.asarray(sc._lo_norm, float); hi = np.asarray(sc._hi_norm, float)
rec = pycolmap.Reconstruction(f"{D}/sparse/0"); cam = list(rec.cameras.values())[0]; f, cx, cy = float(cam.params[0]), float(cam.params[1]), float(cam.params[2])
by = {im.name: im for im in rec.images.values()}; fm = np.load(f"{D}/frame_map.npy"); W, H = 256, 192; sx = cam.width / W
pitch = (hi - lo) / (NC - 1); free = torch.zeros((NC,) * 3, dtype=torch.int32, device=dev); seen_pts = []; VOTE = int(os.environ.get("DC_VOTE", "3"))
lo_t = torch.tensor(lo, device=dev, dtype=torch.float32); pt = torch.tensor(pitch, device=dev, dtype=torch.float32)
v_, u_ = np.mgrid[0:H:STRIDE, 0:W:STRIDE]; u_ = u_.ravel(); v_ = v_.ravel()
step_m = float(pitch.min()) * s * 0.5
for k, o in fm:
    im = by.get(f"f_{k:03d}.jpg")
    if im is None: continue
    d = cv2.imread(f"{src}/depth/{o:06d}.png", cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000; c = cv2.imread(f"{src}/confidence/{o:06d}.png", 0)
    z = d[v_, u_]; ok = (z > 0) & (c[v_, u_] >= CONF); uu, vv, zz = u_[ok], v_[ok], z[ok]
    cfw = im.cam_from_world(); R = torch.tensor(cfw.rotation.matrix(), device=dev, dtype=torch.float32); t = torch.tensor(cfw.translation, device=dev, dtype=torch.float32)
    dirc = torch.tensor(np.stack([(uu * sx - cx) / f, (vv * sx - cy) / f, np.ones_like(zz)], 1), device=dev, dtype=torch.float32)   # z-depth parametrisation
    zt = torch.tensor(zz, device=dev, dtype=torch.float32)
    Cw = -(R.T @ t); dist = float(np.linalg.norm(Cw.cpu().numpy() - X))
    z0 = max(0.0, dist - 1.6 * s)                                          # start where the ray can enter the grid
    nst = int((float(zz.max()) - z0) / step_m) + 1
    for a in range(0, nst, 64):                                           # march in chunks of 64 steps
        zs = z0 + step_m * torch.arange(a, min(nst, a + 64), device=dev, dtype=torch.float32)
        keep = zs[None, :] < (zt[:, None] - MARGIN)                         # stop MARGIN before the measured surface
        if not keep.any(): continue
        Pc = dirc[:, None, :] * zs[None, :, None]; Pw = (Pc - t) @ R          # world
        Pn = (Pw - torch.tensor(X, device=dev, dtype=torch.float32)) / s
        idx = torch.round((Pn - lo_t) / pt).long(); inb = keep & ((idx >= 0) & (idx < NC)).all(-1)
        ii = idx[inb]; lin = torch.unique(ii[:, 0] * NC * NC + ii[:, 1] * NC + ii[:, 2]); free.view(-1).index_add_(0, lin, torch.ones_like(lin, dtype=torch.int32))   # one vote per frame per voxel
    Pend = ((dirc * zt[:, None] - t) @ R).cpu().numpy(); seen_pts.append(Pend[::4])
free = (free >= VOTE).cpu().numpy(); np.save(f"{D}/dc_free.npy", free)
# support plane (RANSAC on all measured points, the dominant plane is the table)
import open3d as o3d
allp = np.vstack(seen_pts); pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(allp))
(a_, b_, c_, d_), inl = pc.segment_plane(0.003, 3, 2000); nrm = np.array([a_, b_, c_]); side = np.sign(nrm @ X + d_)
print(f"[depth_carve] {len(fm)} frames, {free.sum()} free voxels of {NC**3}; support plane normal {np.round(nrm,3)} ({len(inl)} inliers), object side {side:+.0f}")
g = np.stack(np.meshgrid(*[lo[i] + pitch[i] * np.arange(NC) for i in range(3)], indexing="ij"), -1)
above = side * ((g * s + X) @ nrm + d_) > -0.5 * float(pitch.min()) * s
# permissive silhouette hull, resampled onto this grid
import nvdiffrast.torch as dr
hf = sc.hull(dr.RasterizeCudaContext(), vote=int(os.environ.get("DC_SIL_VOTE", "12")))
hs = np.asarray(hf.hull.cpu() if hasattr(hf.hull, "cpu") else hf.hull).astype(bool); n6 = hs.shape[0]
j = np.clip(np.rint((g - np.asarray(hf.lo)) / (np.asarray(hf.hi) - np.asarray(hf.lo)) * (n6 - 1)).astype(int), 0, n6 - 1)
sil = hs[j[..., 0], j[..., 1], j[..., 2]]
np.savez_compressed(f"{D}/dc_parts.npz", above=above, sil=sil); h = (~free) & above & sil
h = ndimage.binary_opening(h, iterations=int(os.environ.get("DC_OPEN", "1")))
lab, nc = ndimage.label(h); h = lab == (1 + np.argmax(np.bincount(lab.ravel())[1:])); h = ndimage.binary_fill_holes(h)
gen = 1 - measure.euler_number(h, connectivity=1)
print(f"[depth_carve] hull {h.sum()} voxels ({nc} components before keeping the largest), genus {gen}; silhouette-only {sil.sum()}, carved free {(sil & ~free).sum()}")
k2 = max(1, 256 // NC); hb = h
for ax in range(3): hb = np.repeat(hb, k2, axis=ax)
np.savez_compressed(f"{D}/depth_hull.npz", hull=hb, lo=lo.astype(np.float32), hi=hi.astype(np.float32), genus=gen, coarse=h, X=X, s=s)
print(f"[depth_carve] saved {D}/depth_hull.npz ({hb.shape[0]}^3)")
