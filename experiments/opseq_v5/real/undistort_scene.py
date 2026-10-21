#!/usr/bin/env python3
"""undistort_scene.py <scene_dir> <out_dir>: remove the COLMAP SIMPLE_RADIAL/RADIAL lens distortion from images and
masks and write the model with a SIMPLE_PINHOLE camera (same f, cx, cy, size, poses) (2026-10-19).

Why: real_scene.py / view_consistency / bake project with a pure pinhole (f, cx, cy) and ignored k1. On the iPhone
captures k1 ~ -0.022, i.e. ~1 px at 0.3 normalised radius, ~4 px at 0.5, ~10 px in the corners. The error depends on
where the object sits in each frame, so silhouettes disagree view-to-view by a few px - the suspected source of the
diagonal ridges on the kettle (exact-silhouette control run: no ridges; RoMa poses: ridges unchanged)."""
import os, sys, glob, shutil, numpy as np, cv2, pycolmap

sd, od = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
rec = pycolmap.Reconstruction(sd + "/sparse/0")
assert len(rec.cameras) == 1, "single shared camera expected"
cid, cam = next(iter(rec.cameras.items()))
name = cam.model.name if hasattr(cam.model, "name") else str(cam.model)
p = np.asarray(cam.params, np.float64)
if "SIMPLE_RADIAL" in name: f, cx, cy, k1, k2 = p[0], p[1], p[2], p[3], 0.0
elif "RADIAL" in name: f, cx, cy, k1, k2 = p[0], p[1], p[2], p[3], p[4]
else: sys.exit(f"unsupported camera model {name}")
W, H = int(cam.width), int(cam.height)
print(f"[undist] {name} f={f:.2f} c=({cx:.1f},{cy:.1f}) k1={k1:.5f} k2={k2:.5f} {W}x{H}", flush=True)
# for every pixel of the UNDISTORTED (pinhole) image, where it lies in the original distorted image
u, v = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
x, y = (u - cx) / f, (v - cy) / f; r2 = x * x + y * y; d = 1 + k1 * r2 + k2 * r2 * r2
mx = (x * d * f + cx).astype(np.float32); my = (y * d * f + cy).astype(np.float32)
shift = np.hypot(mx - u, my - v); print(f"[undist] pixel shift: median {np.median(shift):.2f} p95 {np.percentile(shift, 95):.2f} max {shift.max():.2f}", flush=True)

def remap_dir(sub, interp, ext):
    src = os.path.join(sd, sub)
    if not os.path.isdir(src): return 0
    os.makedirs(os.path.join(od, sub), exist_ok=True); n = 0
    for fp in sorted(glob.glob(os.path.join(src, "*" + ext))):
        im = cv2.imread(fp, cv2.IMREAD_UNCHANGED)
        out = cv2.remap(im, mx, my, interp, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if sub.startswith("mask") and interp == cv2.INTER_LINEAR: out = np.where(out > 127, 255, 0).astype(np.uint8)
        cv2.imwrite(os.path.join(od, sub, os.path.basename(fp)), out, [cv2.IMWRITE_JPEG_QUALITY, 97]); n += 1
    return n
print("[undist] images", remap_dir("images", cv2.INTER_LINEAR, ".jpg"), flush=True)
for sub in ("masks", "masks_sam2"): print(f"[undist] {sub}", remap_dir(sub, cv2.INTER_LINEAR, ".png"), flush=True)
for fn in ("frame_map.npy",):
    if os.path.exists(os.path.join(sd, fn)): shutil.copy(os.path.join(sd, fn), od)
if os.path.isdir(os.path.join(sd, "sparse", "arkit")): shutil.copytree(os.path.join(sd, "sparse", "arkit"), os.path.join(od, "sparse", "arkit"), dirs_exist_ok=True)
new = pycolmap.Camera(model="SIMPLE_PINHOLE", width=W, height=H, params=[f, cx, cy], camera_id=cid)
rec.cameras[cid] = new
os.makedirs(os.path.join(od, "sparse", "0"), exist_ok=True); rec.write(os.path.join(od, "sparse", "0"))
print(f"[undist] wrote {od} (normals_moge must be regenerated on the undistorted images)", flush=True)
