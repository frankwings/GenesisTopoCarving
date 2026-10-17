"""lidar_hull.py <dataset_dir> <stray_src> : fuse the StrayScanner LiDAR depth (masked by masks_sam2, ARKit poses) into an
occupancy grid in the normalised scene frame of real_scene.py and save <dataset_dir>/lidar_hull.npz (hull, lo, hi).
v8 depth route (2026-10-17): the silhouette hull of a hand-held capture is eroded by ARKit drift (mask coverage 0.96) and
loses the mug handle; the LiDAR cloud keeps it (genus 1 at 4 mm voxels)."""
import sys, os, csv, numpy as np, cv2, torch
from scipy import ndimage; from skimage import measure
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike")); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
D, src = sys.argv[1], sys.argv[2]; VOX_M = float(os.environ.get("LIDAR_VOX", "0.004")); CLOSE = int(os.environ.get("LIDAR_CLOSE", "1")); CONF = int(os.environ.get("LIDAR_CONF", "1"))
os.environ["REAL_DATA"] = D
from real_scene import load_real_scene
sc = load_real_scene(D, "cuda"); X = np.asarray(sc.X, float); s = float(sc.s); lo = np.asarray(sc._lo_norm, float); hi = np.asarray(sc._hi_norm, float)
print(f"[lidar_hull] scene centre {np.round(X,4)} scale s={s:.4f} (1 normalised unit = {s*1000:.1f} mm); grid {lo} .. {hi}")
K = np.loadtxt(f"{src}/camera_matrix.csv", delimiter=","); fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
odom = {int(r["frame"]): [float(r[k]) for k in ("x", "y", "z", "qx", "qy", "qz", "qw")] for r in csv.DictReader(open(f"{src}/odometry.csv"), skipinitialspace=True)}
def R(qx, qy, qz, qw): return np.array([[1-2*(qy*qy+qz*qz), 2*(qx*qy-qz*qw), 2*(qx*qz+qy*qw)], [2*(qx*qy+qz*qw), 1-2*(qx*qx+qz*qz), 2*(qy*qz-qx*qw)], [2*(qx*qz-qy*qw), 2*(qy*qz+qx*qw), 1-2*(qx*qx+qy*qy)]])
fm = np.load(f"{D}/frame_map.npy"); W, H = 256, 192; sx = 1920 / W; P = []
import pycolmap; _rec = pycolmap.Reconstruction(f"{D}/sparse/0"); _by = {im.name: im for im in _rec.images.values()}
if os.environ.get("LIDAR_POSES", "arkit") == "colmap":
    _cam = list(_rec.cameras.values())[0]; fx = fy = float(_cam.params[0]); cx, cy = float(_cam.params[1]), float(_cam.params[2]); print(f"[lidar_hull] poses from COLMAP model (BA), focal {fx:.1f}")
for k, o in fm:
    d = cv2.imread(f"{src}/depth/{o:06d}.png", cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000; c = cv2.imread(f"{src}/confidence/{o:06d}.png", 0)
    mp = f"{D}/masks_sam2/f_{k:03d}.png"
    if not os.path.exists(mp): continue
    m = cv2.resize(cv2.imread(mp, 0), (W, H), interpolation=cv2.INTER_NEAREST) > 127; m = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    v, u = np.nonzero((d > 0) & (c >= CONF) & m); z = d[v, u]; Xc = np.stack([(u * sx - cx) * z / fx, (v * sx - cy) * z / fy, z], 1)
    if os.environ.get("LIDAR_POSES", "arkit") == "colmap":                 # BA-refined poses from <dataset>/sparse/0 (refine_poses_ba.py)
        im = _by.get(f"f_{k:03d}.jpg")
        if im is None: continue
        cfw = im.cam_from_world(); P.append((Xc - cfw.translation) @ cfw.rotation.matrix())
    else:
        x, y, zz, qx, qy, qz, qw = odom[o]; P.append(Xc @ R(qx, qy, qz, qw).T + np.array([x, y, zz]))
P = np.vstack(P)
import open3d as o3d                                     # statistical outlier removal: floaters create spurious tunnels (genus 13 without, 1 with)
pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P)); pc, _ = pc.remove_statistical_outlier(int(os.environ.get("LIDAR_NB", "20")), float(os.environ.get("LIDAR_STD", "2.0")))
print(f"[lidar_hull] outlier removal: {len(P)} -> {len(pc.points)} points"); P = np.asarray(pc.points)
Pn = (P - X) / s                                         # normalised scene frame (world axes unchanged; flip_x lives in the projection)
nres = 256; sp = (hi - lo) / (nres - 1); vox_n = VOX_M / s; k = max(1, int(round(vox_n / sp[0])))
# occupancy on a COARSE grid at the LiDAR voxel size (closing/fill/genus are stable there: 4 mm -> genus 1 on the point
# cloud; on the fine 0.6 mm grid the same cloud gives 171 components and genus 14), then upsampled to the chain's grid.
nc_ = int(np.ceil(nres / k)); spc = sp * k
idx = np.floor((Pn - lo) / spc).astype(int); ok = np.all((idx >= 0) & (idx < nc_), 1); idx = idx[ok]
occ = np.zeros((nc_,) * 3, bool); occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
print(f"[lidar_hull] {len(P)} points, {ok.mean()*100:.1f} % inside the grid, {occ.sum()} occupied cells on the {nc_}^3 grid ({VOX_M*1000:.0f} mm)")
h = ndimage.binary_closing(occ, iterations=CLOSE); h = ndimage.binary_fill_holes(h)
lab, ncomp = ndimage.label(h); h = lab == (1 + np.argmax(np.bincount(lab.ravel())[1:]))
g = 1 - measure.euler_number(h, connectivity=1); print(f"[lidar_hull] coarse hull: {h.sum()} voxels, {ncomp} components before keeping the largest, genus {g}")
hf = h
for ax in range(3): hf = np.repeat(hf, k, axis=ax)
hf = hf[:nres, :nres, :nres]
if hf.shape != (nres,) * 3: hf = np.pad(hf, [(0, nres - hf.shape[i]) for i in range(3)], mode="edge")
h = hf
np.savez_compressed(f"{D}/lidar_hull.npz", hull=h, lo=lo.astype(np.float32), hi=hi.astype(np.float32), genus=g, X=X, s=s)
print(f"[lidar_hull] saved {D}/lidar_hull.npz")
