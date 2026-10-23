#!/usr/bin/env python3
"""make_baseline_gifs.py [shapes...]: side-by-side turntable GIFs GT | ours | SAP | RsR | NeuS (when available) for the
baseline comparison (2026-10-22). All meshes in the compare_dmesh2 frame, one common normalisation (the GT's), label =
method + closed/genus. RsR is re-run here (clean variant) because the batch kept only the metrics.
Output: despike/results_genus/baselines_gifs/<shape>.gif (+ _grid.png contact sheet)."""
import os, sys, json, glob, math, subprocess, tempfile, shutil, importlib.util, numpy as np, torch, cv2, trimesh
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; sys.path[:0] = [R, f"{R}/despike", "/home/kingy/Projects/Genesis/GenesisTopmod"]
os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "12.0")
import nvdiffrast.torch as dr
from pipeline.cameras import perspective, look_at, transform_to_clip
sp = importlib.util.spec_from_file_location("rb", f"{R}/despike/run_rsr_batch.py"); rb = importlib.util.module_from_spec(sp); sp.loader.exec_module(rb)
from eval_local_refine import load_obj, normalize_to_range
OUT = f"{R}/despike/results_genus/baselines_gifs"; os.makedirs(OUT, exist_ok=True); os.makedirs(f"{OUT}/rsr_meshes", exist_ok=True)
S = rb.shapes_all()

def ours_mesh(shape):
    for tag in ("v72", "c65", "r15", "b2"):
        f = f"{R}/despike/results_genus/{shape}_{tag}_auto.npz"
        if os.path.exists(f):
            z = np.load(f); gv, _ = load_obj(rb.gt_path(shape)); g64 = normalize_to_range(gv); gcmp = rb.norm(gv)
            a = (gcmp.max(0) - gcmp.min(0))[0] / (g64.max(0) - g64.min(0))[0]; b = gcmp.min(0) - a * g64.min(0)
            return a * z["verts"].astype(np.float64) + b, z["tris"].astype(np.int64), tag
    return None

def sap_mesh(shape):
    for l in open(f"{R}/despike/results_genus/sap/sap.jsonl"):
        r = json.loads(l)
        if r["shape"] == shape and "mesh" in r:
            m = trimesh.load(r["mesh"], force="mesh"); return np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)
    return None

def rsr_mesh(shape):
    keep = f"{OUT}/rsr_meshes/{shape}.obj"
    if not os.path.exists(keep):
        gv, gf = load_obj(rb.gt_path(shape)); Vg = rb.norm(gv); tm = trimesh.Trimesh(Vg, gf, process=False)
        P, fid = trimesh.sample.sample_surface_even(tm, 60000, seed=0); N = np.asarray(tm.face_normals)[fid]
        wd = tempfile.mkdtemp(prefix="rsrgif_"); od = f"{wd}/out"; os.makedirs(od)
        with open(f"{wd}/pc.obj", "w") as f:
            for p, n in zip(np.asarray(P), N): f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\nvn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
        open(f"{wd}/cfg.txt", "w").write(f"root {wd}\nmodel_name pc.obj\nout_root {od}\nout_name rec\nisEuclidean true\nisGTNormal true\nisNoiseExp false\nisDebug false\nk 30\nr 20\ntheta 60\nn 50\n")
        subprocess.run([rb.RSR, f"{wd}/cfg.txt"], capture_output=True, cwd=wd, timeout=900)
        Vs, Fs, off = [], [], 0
        for c in sorted(glob.glob(f"{od}/rec_component_*.obj")):
            v, f = rb.load_obj(c)
            if len(f): Vs.append(v); Fs.append(f + off); off += len(v)
        shutil.rmtree(wd, ignore_errors=True)
        if not Vs: return None
        trimesh.Trimesh(np.vstack(Vs), np.vstack(Fs), process=False).export(keep)
    m = trimesh.load(keep, force="mesh"); return np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)

def neus_mesh(shape):
    ms = sorted(glob.glob(f"/home/kingy/run/neus_exp/neus-blender-{shape}/full@*/save/*.obj"))
    if not ms: return None
    gv, _ = load_obj(rb.gt_path(shape)); g64 = normalize_to_range(gv); gcmp = rb.norm(gv)
    a = (gcmp.max(0) - gcmp.min(0))[0] / (g64.max(0) - g64.min(0))[0]; b = gcmp.min(0) - a * g64.min(0)
    m = trimesh.load(ms[-1], force="mesh"); return a * np.asarray(m.vertices, float) + b, np.asarray(m.faces, np.int64)

dev = "cuda"; ctx = dr.RasterizeCudaContext(); RES = 320
proj = perspective(fov_deg=40.0, aspect=1.0, near=0.1, far=20.0, device=dev)
up = np.array([0., 1., 0.]); e1 = np.cross(up, [1, 0, 0]); e1 /= np.linalg.norm(e1); e2 = np.cross(up, e1)

def render(V, F, az, el=18, Rcam=3.2):
    vt = torch.tensor(V, dtype=torch.float32, device=dev); ft = torch.tensor(F, dtype=torch.int32, device=dev)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]); vn = np.zeros_like(V)
    for k in range(3): np.add.at(vn, F[:, k], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-9; vnt = torch.tensor(vn, dtype=torch.float32, device=dev)
    a_, e_ = math.radians(az), math.radians(el); eye = Rcam * (math.cos(e_) * (math.cos(a_) * e1 + math.sin(a_) * e2) + math.sin(e_) * up)
    view = look_at(tuple(map(float, eye)), center=(0, 0, 0), up=tuple(map(float, up)), device=dev); mvp = proj @ view
    pos = transform_to_clip(vt, mvp); rast, _ = dr.rasterize(ctx, pos, ft, resolution=[RES, RES])
    n_img, _ = dr.interpolate(vnt[None].contiguous(), rast, ft); n_img = n_img[0]
    ldir = torch.tensor(eye / np.linalg.norm(eye), dtype=torch.float32, device=dev)
    shade = 0.35 + 0.65 * (n_img @ ldir).abs().clamp(0, 1); fg = rast[0, :, :, 3] > 0
    col = torch.tensor([0.45, 0.62, 0.85], device=dev) * shade[..., None]; img = torch.where(fg[..., None], col, torch.ones_like(col))
    return (img.flip(0).cpu().numpy() * 255).astype(np.uint8)

def label(t, V, F):
    if V is None: return f"{t}: n/a"
    tp = rb.topo(V, F); g = tp["genus"] if tp["closed"] and tp["comps"] == 1 else ("open" if not tp["closed"] else f"{tp['comps']} comps")
    return f"{t}: {'genus ' + str(g) if isinstance(g, int) else g}"

for shape in (sys.argv[1:] or ["kitten", "fertility", "t10k_91610", "t10k_1158268", "t10k_399567", "t10k_135074"]):
    gv, gf = load_obj(rb.gt_path(shape)); Vg = rb.norm(gv); gf = np.asarray(gf, np.int64)
    c = (Vg.max(0) + Vg.min(0)) / 2; sc = 1.0 / np.abs(Vg - c).max()
    panels = [("GT", (Vg, gf)), ("ours", ours_mesh(shape)), ("SAP", sap_mesh(shape)), ("RsR", rsr_mesh(shape)), ("NeuS", neus_mesh(shape))]
    panels = [(t, m) for t, m in panels if m is not None]
    labs = [label(t + (f" ({m[2]})" if t == "ours" else ""), m[0], m[1]) for t, m in panels]
    labs[0] = f"GT: genus {S[shape]}"
    frames = []
    for k in range(36):
        row = []
        for (t, m), lb in zip(panels, labs):
            V = (np.asarray(m[0], float) - c) * sc; img = cv2.cvtColor(render(V, np.asarray(m[1], np.int64), 360 * k / 36), cv2.COLOR_RGB2BGR)
            cv2.putText(img, lb, (8, 22), 0, 0.55, (0, 0, 200), 1, cv2.LINE_AA); row.append(img)
        frames.append(np.hstack(row))
    d = tempfile.mkdtemp(prefix="gif_")
    for i, fr in enumerate(frames): cv2.imwrite(f"{d}/{i:03d}.png", fr)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "12", "-i", f"{d}/%03d.png", "-vf", "split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3", f"{OUT}/{shape}.gif"], check=True)
    cv2.imwrite(f"{OUT}/{shape}_grid.png", np.vstack([frames[0], frames[9], frames[18]])); shutil.rmtree(d, ignore_errors=True)
    print(f"[gif] {shape}: {' | '.join(labs)} -> {OUT}/{shape}.gif ({os.path.getsize(OUT + '/' + shape + '.gif') // 1024} KB)", flush=True)
