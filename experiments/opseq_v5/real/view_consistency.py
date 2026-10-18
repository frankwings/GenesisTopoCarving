#!/usr/bin/env python3
"""view_consistency.py: find capture frames whose silhouette contradicts the others (2026-10-18).

Why: on mug3rm, 5 of 145 frames (93, 119, 132-134) put the handle 50-106 px away from where the other 126 frames
put it while the (rotationally symmetric) body still fitted - a pose error that only the non-symmetric part reveals.
The vote hull tolerates them, the DR silhouette loss does not: with them in, the handle hole got a membrane
(ho16 0.954, hair 36944); without them the handle came out whole (ho16 0.986, hair 908).

Test (see find_inconsistent): per frame, the solid chunk of "everyone else says material" voxels that this frame
vetoes. A global outside-fraction score was tried first and failed: the handle is too small a share of the hull, so
f_093/119/133 (0.7-0.9 %) ranked below frames with ordinary mask-edge noise (f_057-063, 1.2-2 %).

API: find_inconsistent(names, masks, Rs, ts, f, cx, cy) -> (list of names, per-frame scores dict)
CLI: python3 real/view_consistency.py <scene_dir>"""
import os, sys, numpy as np, torch

VC_DIL = int(os.environ.get("VC_DIL", "6"))          # mask dilation (px) before voting: boundary jitter is not a contradiction
VC_CONF = int(os.environ.get("VC_CONF", "2"))        # a voxel is "confident material" when at most this many OTHER frames veto it
VC_ERODE = int(os.environ.get("VC_ERODE", "2"))      # 3-D erosion of a frame's contradicted set: thin shells (mask edges) vanish, a part does not
VC_MIN_VOX = int(os.environ.get("VC_MIN_VOX", "10")) # frames whose eroded contradicted set keeps >= this many voxels are dropped
VC_RES = int(os.environ.get("VC_RES", "160"))


def _centre_radius(masks, Rs, ts, f, cx, cy):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "despike"))
    import real_scene as rs
    dirs, origs = [], []
    for m, R, t in zip(masks, Rs, ts):
        d, o = rs._mask_centroid_ray(m, R, t, f, cx, cy)
        if d is not None: dirs.append(d); origs.append(o)
    X = rs._ray_intersection(dirs, origs)
    rv = []
    for m, R, t in zip(masks, Rs, ts):
        ys, xs = np.where(m > 127)
        if len(ys): rv.append(np.linalg.norm(-R.T @ t - X) * 0.5 * max(np.ptp(xs), np.ptp(ys)) / f)
    return X, float(np.median(rv))


def find_inconsistent(names, masks, Rs, ts, f, cx, cy, log=print, dev=None):
    """Per frame: voxels that every other frame but <= VC_CONF calls material, yet this frame vetoes. Eroded twice in
    3-D, what survives is a solid chunk this frame disagrees on (wrong pose on an asymmetric part, or a mask that lost a
    part). mug3rm: f_058 (mask lost the rim/inside, 171k), f_134 748, f_093 74, f_119 51, f_133 30; every other frame 0."""
    import cv2
    from scipy import ndimage as nd
    dev = dev or ("cuda" if torch.cuda.is_available() else "cpu")
    X, r = _centre_radius(masks, Rs, ts, f, cx, cy)
    h = 1.05 * r / 0.8                                    # same box as real_scene's normalised [-1.05, 1.05]^3
    N = VC_RES; g = torch.linspace(-h, h, N, device=dev)
    G = torch.stack(torch.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3) + torch.tensor(X, dtype=torch.float32, device=dev)
    H, W = masks[0].shape
    k = np.ones((2 * VC_DIL + 1, 2 * VC_DIL + 1), np.uint8)
    inside = torch.zeros(len(names), G.shape[0], dtype=torch.bool, device=dev)
    for i, (m, R, t) in enumerate(zip(masks, Rs, ts)):
        md = torch.tensor(cv2.dilate((m > 127).astype(np.uint8), k) > 0, device=dev)
        Pc = G @ torch.tensor(R, dtype=torch.float32, device=dev).T + torch.tensor(t, dtype=torch.float32, device=dev)
        z = Pc[:, 2]; u = (f * Pc[:, 0] / z + cx).round().long(); v = (f * Pc[:, 1] / z + cy).round().long()
        ok = (z > 0) & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        inside[i] = ~ok                                   # out of frame = unknown = no veto
        inside[i, ok] = md[v[ok], u[ok]]
    veto = (~inside).sum(0)
    score = {}
    for i, n in enumerate(names):
        others = veto - (~inside[i]).int()
        bad = ((others <= VC_CONF) & ~inside[i]).reshape(N, N, N).cpu().numpy()
        score[n] = int(nd.binary_erosion(bad, iterations=VC_ERODE).sum()) if bad.any() else 0
    dropped = [n for n in names if score[n] >= VC_MIN_VOX]
    log(f"[viewcheck] {len(names)} frames, drop {len(dropped)}: {[(n, score[n]) for n in dropped]}")
    return dropped, score


def load_scene(sd):
    import pycolmap, cv2
    rec = pycolmap.Reconstruction(os.path.abspath(sd) + "/sparse/0"); cam = list(rec.cameras.values())[0]
    f, cx, cy = cam.params[:3]
    ims = sorted(rec.images.values(), key=lambda i: i.name)
    masks = [cv2.imread(f"{sd}/masks_sam2/{os.path.splitext(im.name)[0]}.png", 0) for im in ims]
    Rs = [im.cam_from_world().rotation.matrix() for im in ims]; ts = [np.asarray(im.cam_from_world().translation) for im in ims]
    return [im.name for im in ims], masks, Rs, ts, f, cx, cy


if __name__ == "__main__":
    names, masks, Rs, ts, f, cx, cy = load_scene(sys.argv[1])
    d, sc = find_inconsistent(names, masks, Rs, ts, f, cx, cy)
    print("[viewcheck] top scores:", sorted(sc.items(), key=lambda kv: -kv[1])[:10])
    print("[viewcheck] DROP", ",".join(d))
