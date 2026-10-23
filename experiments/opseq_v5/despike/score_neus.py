#!/usr/bin/env python3
"""score_neus.py: score instant-nsr-pl NeuS meshes with the same metrics as RsR / SAP / DMesh++ (2026-10-22).

Synthetic (`--syn`): the NeuS mesh lives in the run_64v frame (export_neus_views renders our 64 star cameras of the
normalize_to_range GT); map it to the compare_dmesh2 frame (norm of the raw GT) through the raw GT (both are
translation + uniform scale of the same vertices), then topo / cd / iou against the GT exactly as for the others.
Rows -> despike/results_genus/neus/neus_syn.jsonl (full mesh + largest component + lenient hole fill).
Real (`--real <scene>`): NeuS normalised its poses (datasets/colmap.normalize_poses: lookat centre, min camera distance
= 1); invert that with the same function on the same COLMAP model, go to COLMAP world, then to our real_scene frame
(X, s) and run exam_real (held-out silhouette IoU) + linking_audit --rank. Rows -> neus_real.jsonl."""
import os, sys, json, glob, argparse, importlib.util, numpy as np
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; NEUS = "/home/kingy/Projects/Genesis/GenesisExp/GenesisNeuS"
OUT = f"{R}/despike/results_genus/neus"; os.makedirs(OUT, exist_ok=True)
sp = importlib.util.spec_from_file_location("rb", f"{R}/despike/run_rsr_batch.py"); rb = importlib.util.module_from_spec(sp); sp.loader.exec_module(rb)
sys.path[:0] = [R, f"{R}/despike", "/home/kingy/Projects/Genesis/GenesisTopmod"]

def largest(m):
    import trimesh
    parts = m.split(only_watertight=False); return max(parts, key=lambda q: len(q.faces)) if len(parts) else m

def score_syn(shape, mesh_path, gtg):
    import trimesh
    from eval_local_refine import load_obj, normalize_to_range
    gv, gf = load_obj(rb.gt_path(shape)); g64 = normalize_to_range(gv); gcmp = rb.norm(gv)
    # affine run_64v frame -> compare frame: p_cmp = a * p_64 + b (uniform), fitted on the GT vertices
    a = (gcmp.max(0) - gcmp.min(0))[0] / (g64.max(0) - g64.min(0))[0]; b = gcmp.min(0) - a * g64.min(0)
    m = trimesh.load(mesh_path, force="mesh"); V = a * np.asarray(m.vertices, float) + b; F = np.asarray(m.faces, np.int64)
    t = rb.topo(V, F); rec = dict(shape=shape, gt_genus=gtg, mesh=mesh_path); rec.update(t)
    big = largest(trimesh.Trimesh(V, F, process=False)); tb = rb.topo(np.asarray(big.vertices, float), np.asarray(big.faces, np.int64)); rec["largest"] = tb
    try:
        mb = big.copy(); mb.fill_holes(); tl = rb.topo(np.asarray(mb.vertices, float), np.asarray(mb.faces, np.int64))
        rec["lenient"] = dict(closed=tl["closed"], genus=tl["genus"], genus_right=bool(tl["closed"] and tl["genus"] == gtg))
    except Exception: rec["lenient"] = dict(closed=False, genus=None, genus_right=False)
    try: cd, iou, fit = rb.metrics(V, F, gcmp, gf)
    except Exception: cd, iou, fit = float("nan"), float("nan"), 0.0
    rec.update(cd=cd, iou=iou, icp=fit, strict=bool(t["closed"] and t["comps"] == 1 and t["genus"] == gtg), genus_right_largest=bool(tb["closed"] and tb["genus"] == gtg))
    return rec

def neus_to_colmap_world(scene_root, V):
    """Invert instant-nsr-pl's pose normalisation (lookat centre, up from ground/camera, scale = min camera distance)."""
    import torch
    import importlib.util as _iu   # load colmap_utils.py by path: the datasets package __init__ imports the model stack (tinycudann)
    _s = _iu.spec_from_file_location("colmap_utils", f"{NEUS}/datasets/colmap_utils.py"); _cu = _iu.module_from_spec(_s); _s.loader.exec_module(_cu)
    read_images_binary, read_points3d_binary = _cu.read_images_binary, _cu.read_points3d_binary
    # datasets/colmap.py imports the model stack (tinycudann); pull only normalize_poses/get_center out of its source
    import ast, math, torch.nn.functional as F
    src = open(f"{NEUS}/datasets/colmap.py").read(); tree = ast.parse(src); ns = {"torch": torch, "F": F, "math": math, "np": np}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("get_center", "normalize_poses"): exec(ast.get_source_segment(src, node), ns)
    normalize_poses = ns["normalize_poses"]
    imdata = read_images_binary(os.path.join(scene_root, "sparse/0/images.bin"))
    mats = []
    for d in sorted(imdata.values(), key=lambda x: x.name):
        Rm = torch.tensor(d.qvec2rotmat(), dtype=torch.float32); t = torch.tensor(d.tvec, dtype=torch.float32).reshape(3, 1)
        c2w = torch.cat([torch.cat([Rm.T, -Rm.T @ t], dim=1), torch.tensor([[0., 0., 0., 1.]])], dim=0); mats.append(c2w)
    c2w = torch.stack(mats)[:, :3]; c2w[:, :, 1:3] *= -1.0                       # COLMAP -> OpenGL camera convention (as the loader does)
    pts3d = read_points3d_binary(os.path.join(scene_root, "sparse/0/points3D.bin")); pts = torch.tensor([p.xyz for p in pts3d.values()], dtype=torch.float32)
    import omegaconf
    cfg = omegaconf.OmegaConf.create({"up_est_method": "ground", "center_est_method": "lookat"})
    # replicate normalize_poses but RETURN the transform: recompute poses_norm and solve the similarity from the camera centres
    # the 'ground' up vector comes from a RANSAC plane fit (pyransac3d, random); launch.py seeds everything with 42
    # right before the dataset builds -> reseed identically so the same plane (hence the same rotation) is found
    import random; random.seed(42); np.random.seed(42); torch.manual_seed(42)
    poses_norm, _ = normalize_poses(c2w.clone(), pts.clone(), up_est_method=cfg.up_est_method, center_est_method=cfg.center_est_method)
    C0 = c2w[:, :, 3].numpy().astype(np.float64); C1 = poses_norm[:, :, 3].numpy().astype(np.float64)      # world -> normalised: C1 = s R C0 + t
    m0, m1 = C0.mean(0), C1.mean(0); H = (C0 - m0).T @ (C1 - m1); U, S, Vt = np.linalg.svd(H); Rr = Vt.T @ U.T
    if np.linalg.det(Rr) < 0: Vt[-1] *= -1; Rr = Vt.T @ U.T
    s = S.sum() / ((C0 - m0) ** 2).sum(); t = m1 - s * Rr @ m0
    resid = np.abs((s * (Rr @ C0.T).T + t) - C1).max()
    Vw = ((np.asarray(V, np.float64) - t) @ Rr) / s                                                           # inverse similarity
    return Vw, resid

def score_real(scene, mesh_path):
    import trimesh, torch, subprocess
    sd = f"{R}/real/{scene}"; m = trimesh.load(mesh_path, force="mesh")
    Vw, resid = neus_to_colmap_world(f"{NEUS}/data/real/{scene}", np.asarray(m.vertices))
    # COLMAP world -> our normalised frame (same X, s as real_scene / bake_vertex_colors)
    import pycolmap, cv2
    sys.path.insert(0, f"{R}/despike"); import real_scene as rs
    rec_ = pycolmap.Reconstruction(sd + "/sparse/0"); cam = list(rec_.cameras.values())[0]; f, cx, cy = cam.params[:3]
    ims = sorted(rec_.images.values(), key=lambda i: i.name); excl = set(open(f"{sd}/viewcheck_drop.txt").read().split(",")) if os.path.exists(f"{sd}/viewcheck_drop.txt") else set()
    ims = [im for im in ims if im.name not in excl]
    masks = [cv2.imread(f"{sd}/masks_sam2/{os.path.splitext(im.name)[0]}.png", 0) for im in ims]
    dirs, origs = [], []
    for im, mk in zip(ims, masks):
        c = im.cam_from_world(); d, o = rs._mask_centroid_ray(mk, c.rotation.matrix(), c.translation, f, cx, cy)
        if d is not None: dirs.append(d); origs.append(o)
    X = rs._ray_intersection(dirs, origs); rv = []
    for im, mk in zip(ims, masks):
        ys, xs = np.where(mk > 127)
        if len(ys) == 0: continue
        c = im.cam_from_world(); C = -c.rotation.matrix().T @ c.translation; rv.append(np.linalg.norm(C - X) * 0.5 * max(np.ptp(xs), np.ptp(ys)) / f)
    s = float(np.median(rv)) / 0.8; Vn = (Vw - X) / s
    # 2026-10-23: NeuS's 'ground' up vector is a RANSAC plane fit (random; its seed state is not reproducible from
    # outside), so the inverse above can be off by a rigid offset (kettle: held-out IoU 0.76 with a visible shift, fish
    # 0.38). ICP onto the visual hull was tried and withdrawn (the hull over-estimates the object: mug 0.989 -> 0.920).
    # Fair nuisance alignment: a 7-DOF similarity fitted to the TRAINING silhouettes (differentiable render, L1), then the
    # held-out IoU is measured as for every other method. The correction size is recorded (align_sil).
    import torch, nvdiffrast.torch as dr, torch.nn.functional as Fn
    from real_scene import load_real_scene
    import run_64v
    sc = load_real_scene(f"real/{scene}"); ctx = dr.RasterizeCudaContext(); dev = "cuda"
    big0 = largest(trimesh.Trimesh(Vn, np.asarray(m.faces, np.int64), process=False))
    V0 = torch.tensor(np.asarray(big0.vertices), dtype=torch.float32, device=dev); F0 = torch.tensor(np.asarray(big0.faces), dtype=torch.int32, device=dev)
    c0 = V0.mean(0, keepdim=True); gt = torch.tensor((sc.gt < 128).astype(np.float32), device=dev)
    rv_ = torch.full((3,), 1e-4, device=dev, requires_grad=True); tv_ = torch.zeros(3, device=dev, requires_grad=True); ls_ = torch.zeros(1, device=dev, requires_grad=True)   # rv_ not exactly 0: the axis-angle map has zero gradient at r = 0
    opt = torch.optim.Adam([rv_, tv_, ls_], lr=5e-3)
    def rotm(r):
        th = r.norm() + 1e-9; k = r / th; K = torch.tensor([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]], device=dev)
        return torch.eye(3, device=dev) + torch.sin(th) * K + (1 - torch.cos(th)) * (K @ K)
    def apply(V): return (V - c0) @ rotm(rv_).T * torch.exp(ls_) + c0 + tv_
    NV = sc.mvps.shape[0]
    for it in range(300):
        idx = torch.randperm(NV)[:8].tolist(); Vt = apply(V0); loss = 0
        for i in idx:
            pos = run_64v.transform_to_clip(Vt, sc.mvps[i]); rast, _ = dr.rasterize(ctx, pos, F0, resolution=[sc.res, sc.res])
            ones = torch.ones(1, Vt.shape[0], 1, device=dev); col, _ = dr.interpolate(ones, rast, F0); sil = dr.antialias(col, rast, pos, F0)[0, :, :, 0]
            loss = loss + (sil - gt[i]).abs().mean()
        opt.zero_grad(); (loss / len(idx)).backward(); opt.step()
    with torch.no_grad():
        Rm = rotm(rv_); ang = float(np.degrees(np.arccos(np.clip((torch.trace(Rm).item() - 1) / 2, -1, 1)))); scl = float(torch.exp(ls_).item()); sh = float(tv_.norm().item())
        Vn = ((torch.tensor(Vn, dtype=torch.float32, device=dev) - c0) @ Rm.T * scl + c0 + tv_).cpu().numpy().astype(np.float64)
    align_icp = dict(method="silhouette-7dof-on-train-views", rot_deg=ang, scale=scl, shift=sh)
    F = np.asarray(m.faces, np.int64); out = f"{OUT}/{scene}_neus.npz"; np.savez(out, verts=Vn.astype(np.float32), tris=F.astype(np.int32))
    big = largest(trimesh.Trimesh(Vn, F, process=False)); outb = f"{OUT}/{scene}_neus_largest.npz"; np.savez(outb, verts=np.asarray(big.vertices, np.float32), tris=np.asarray(big.faces, np.int32))
    rec = dict(scene=scene, mesh=mesh_path, align_resid=float(resid), align_icp=align_icp); rec.update(rb.topo(Vn, F)); rec["largest"] = rb.topo(np.asarray(big.vertices, float), np.asarray(big.faces, np.int64))
    env = dict(os.environ, REAL_DATA=f"real/{scene}", HULL_VOTE="10", REAL_VIEWCHECK="1", TRAIN_RES="512", TORCH_CUDA_ARCH_LIST="12.0", SHAPE=scene)
    ex = subprocess.run(["python3", "despike/exam_real.py", f"raw={out}", f"taubin={outb}"], cwd=R, env=env, capture_output=True, text=True)
    rec["exam"] = [l for l in ex.stdout.splitlines() if "[exam_real]" in l]
    rk = subprocess.run(["python3", "despike/linking_audit.py", "--rank", outb], cwd=R, env=env, capture_output=True, text=True)
    rec["rank_largest"] = rk.stdout.strip().splitlines()[-1] if rk.stdout.strip() else rk.stderr[-200:]
    return rec

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--syn", action="store_true"); ap.add_argument("--real", default=""); ap.add_argument("--mesh", default=""); ap.add_argument("--tag", default="full"); a = ap.parse_args()
    if a.syn:
        S = rb.shapes_all(); outf = f"{OUT}/neus_syn.jsonl"; done = set(json.loads(l)["shape"] for l in open(outf)) if os.path.exists(outf) else set()
        for s in sorted(S):
            if s in done: continue
            ms = sorted(glob.glob(f"/home/kingy/run/neus_exp/neus-blender-{s}/{a.tag}@*/save/*.obj"))
            if not ms: continue
            rec = score_syn(s, ms[-1], S[s]); open(outf, "a").write(json.dumps(rec) + "\n")
            print(f"[neus syn] {s}: closed={rec['closed']} comps={rec['comps']} genus={rec['genus']} gt={S[s]} strict={rec['strict']} largest_ok={rec['genus_right_largest']} lenient={rec['lenient']['genus_right']} cd={rec['cd']:.4f} iou={rec['iou']:.3f}", flush=True)
    if a.real:
        ms = [a.mesh] if a.mesh else sorted(glob.glob(f"/home/kingy/run/neus_exp/neus-colmap-{a.real}/{a.tag}@*/save/*.obj"))
        rec = score_real(a.real, ms[-1]); open(f"{OUT}/neus_real.jsonl", "a").write(json.dumps(rec) + "\n"); print(json.dumps(rec, indent=1))
