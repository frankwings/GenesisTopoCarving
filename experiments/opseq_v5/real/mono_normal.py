#!/usr/bin/env python3
"""Cache MoGe-2 monocular normal maps for every image in <scene_dir>/images/ (2026-10-19).

Usage (needs the moge venv):  ~/venvs/moge/bin/python real/mono_normal.py real/kettle
Output: <scene_dir>/normals_moge/<stem>.npy, float16 (H, W, 3), unit normals in the camera frame MoGe predicts in
(OpenCV: x right, y down, z forward); real_scene.py converts to the OpenGL camera frame, crops and flips per view.
The horizontal FoV is taken from the COLMAP camera (sparse/0) so the network does not have to guess it.
Why: real-data runs are silhouette-only (W_DEPTH = W_DIFF = 0); the surface between the silhouette rims is unconstrained
and comes out wrinkled. A per-pixel normal target constrains exactly that part."""
import os, sys, glob, math, time, numpy as np, torch
from PIL import Image
os.environ.setdefault("HF_HUB_OFFLINE", "1")
from moge.model.v2 import MoGeModel

sd = os.path.abspath(sys.argv[1]); out = os.path.join(sd, "normals_moge"); os.makedirs(out, exist_ok=True)
fov_x = None
try:
    import pycolmap
    cam = list(pycolmap.Reconstruction(sd + "/sparse/0").cameras.values())[0]
    fov_x = math.degrees(2 * math.atan(cam.width / (2 * cam.params[0])))
except Exception as e:
    print(f"[mono_normal] no COLMAP fov ({e}), MoGe will infer it", flush=True)
print(f"[mono_normal] fov_x={fov_x}", flush=True)
dev = "cuda"
model = MoGeModel.from_pretrained("Ruicheng/moge-2-vitl-normal").to(dev).eval().half()
ims = sorted(glob.glob(os.path.join(sd, "images", "*.jpg")))
t0 = time.time(); n = 0
for p in ims:
    o = os.path.join(out, os.path.splitext(os.path.basename(p))[0] + ".npy")
    if os.path.exists(o): continue
    img = torch.tensor(np.asarray(Image.open(p).convert("RGB")), dtype=torch.float32, device=dev).permute(2, 0, 1) / 255
    with torch.no_grad():
        r = model.infer(img, fov_x=fov_x, apply_mask=False, use_fp16=True)
    nrm = r["normal"].float()
    nrm = nrm / nrm.norm(dim=-1, keepdim=True).clamp(min=1e-6)
    np.save(o, nrm.cpu().numpy().astype(np.float16)); n += 1
print(f"[mono_normal] {n} new maps in {time.time() - t0:.0f}s -> {out}", flush=True)
