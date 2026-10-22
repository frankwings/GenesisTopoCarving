#!/usr/bin/env python3
"""export_neus_views.py <shape> <out_dir> [--res 512]: the 64 star cameras of run_64v rendered as RGB (Lambertian
headlight + ambient, white background) + masks + transforms_{train,test}.json in NeRF-synthetic/blender format, so the
neural-implicit baseline (instant-nsr-pl NeuS) trains on the SAME views as the golden chain (2026-10-22).
The GT mesh is normalised exactly as run_64v (normalize_to_range); camera_angle_x = run_64v's fov (2*atan(0.5)).
Held-out: the 16 views of run_64v's heldout split are not available here as a list, so test = every 4th view."""
import os, sys, json, math, argparse, numpy as np, torch, cv2
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; sys.path[:0] = [R, f"{R}/despike", "/home/kingy/Projects/Genesis/GenesisTopmod"]
os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "12.0")
ap = argparse.ArgumentParser(); ap.add_argument("shape"); ap.add_argument("out"); ap.add_argument("--res", type=int, default=512); a = ap.parse_args()
import nvdiffrast.torch as dr, run_64v
from eval_local_refine import load_obj, normalize_to_range, BUNNY_PATH
SM = os.path.dirname(BUNNY_PATH)
src = f"{SM}/{a.shape}.obj" if os.path.exists(f"{SM}/{a.shape}.obj") else f"{R}/shapes_ext/{a.shape}.obj"
gv, gf = load_obj(src); gvn = normalize_to_range(gv); max_r = float(np.linalg.norm(gvn, axis=1).max())
mvps, views = run_64v.star_cameras(max_r)
dev = "cuda"; ctx = dr.RasterizeCudaContext(); H = W = a.res
vt = torch.tensor(gvn, dtype=torch.float32, device=dev); ft = torch.tensor(gf, dtype=torch.int32, device=dev)
vn = run_64v.vertex_normals(vt, ft.long(), vt.shape[0])
os.makedirs(f"{a.out}/train", exist_ok=True); os.makedirs(f"{a.out}/test", exist_ok=True)
fov = math.degrees(2.0 * math.atan(0.5)); frames = {"train": [], "test": []}
for i in range(64):
    pos = run_64v.transform_to_clip(vt, mvps[i]); rast, _ = dr.rasterize(ctx, pos, ft, resolution=[H, W])
    n_cam = (vn @ views[i][:3, :3].T)[None].contiguous(); nimg, _ = dr.interpolate(n_cam, rast, ft)
    fg = (rast[0, :, :, 3] > 0)
    shade = 0.25 + 0.75 * nimg[0, :, :, 2].abs().clamp(0, 1)         # headlight Lambertian + ambient
    rgb = torch.stack([shade * 0.85, shade * 0.80, shade * 0.72], -1)   # warm grey so the three channels differ
    rgb = torch.where(fg[..., None], rgb, torch.ones_like(rgb))
    img = (rgb.flip(0).cpu().numpy() * 255).astype(np.uint8); m = (fg.flip(0).cpu().numpy() * 255).astype(np.uint8)
    split = "test" if i % 4 == 0 else "train"; name = f"r_{i:03d}"
    cv2.imwrite(f"{a.out}/{split}/{name}.png", cv2.cvtColor(np.dstack([img, m]), cv2.COLOR_RGBA2BGRA))   # RGBA like NeRF-synthetic
    c2w = np.linalg.inv(views[i].cpu().numpy().astype(np.float64))      # view = world->camera (OpenGL); blender wants c2w OpenGL
    frames[split].append({"file_path": f"./{split}/{name}", "transform_matrix": c2w.tolist()})
for split in ("train", "test"):
    json.dump({"camera_angle_x": math.radians(fov), "frames": frames[split]}, open(f"{a.out}/transforms_{split}.json", "w"), indent=1)
json.dump({"camera_angle_x": math.radians(fov), "frames": frames["test"]}, open(f"{a.out}/transforms_val.json", "w"), indent=1)
np.savez(f"{a.out}/gt_norm.npz", verts=gvn.astype(np.float32), tris=np.asarray(gf, np.int32), max_r=max_r)
print(f"[neus-export] {a.shape}: {len(frames['train'])} train / {len(frames['test'])} test views at {H}px, fov {fov:.2f} deg, max_r {max_r:.3f} -> {a.out}")
