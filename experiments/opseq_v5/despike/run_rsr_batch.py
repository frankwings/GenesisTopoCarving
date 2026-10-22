#!/usr/bin/env python3
"""run_rsr_batch.py: RsR (Surface Reconstruction Using Rotation Systems, Cui et al. TOG 2024, GenesisExp/GenesisRsR)
as the explicit-topology-control baseline on the oracle-usable Thingi10K models + the 6 classic shapes (2026-10-22).

Per shape the GT mesh (compare_dmesh2 frame, `norm`) is sampled to N_PTS surface points; four RsR inputs:
  clean : exact face normals, isEuclidean=true, no genus prior      (RsR's best case, topology DISCOVERED by its n rule)
  gtg   : clean + `genus <GT>`                                      (RsR's "topology control" = genus given, upper bound)
  pca   : points only, isGTNormal=false (RsR estimates normals)     (no oracle normals)
  noisy : positional Gaussian noise sigma = NOISE x mean NN spacing, GT normals, isEuclidean=false (scan mode)
Output: despike/results_genus/rsr/rsr_<variant>.jsonl with topo (closed/comps/genus), cd/iou (compare_dmesh2.metrics),
wall, and gt_genus; run `python3 despike/run_rsr_batch.py --summary` for the table.
Usage: python3 despike/run_rsr_batch.py [--variants clean,gtg,pca,noisy] [--shapes a,b] [--jobs 6]"""
import os, sys, json, time, glob, argparse, subprocess, tempfile, shutil
import numpy as np
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as _mp   # spawn: open3d/torch forked workers deadlocked (2026-10-22 smoke test)
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; sys.path.insert(0, f"{R}/despike")
RSR = "/home/kingy/Projects/Genesis/GenesisExp/GenesisRsR/build/RsR"
SM = "/home/kingy/Projects/Genesis/GenesisExp/GenesisHunyuan/.venv/lib/python3.12/site-packages/pymeshlab/tests/sample_meshes"
OUT = f"{R}/despike/results_genus/rsr"; os.makedirs(OUT, exist_ok=True)
MEM_GB = int(os.environ.get("RSR_MEM_GB", "12")); N_PTS = int(os.environ.get("RSR_PTS", "60000")); NOISE = float(os.environ.get("RSR_NOISE", "0.5"))
CLASSIC = {"kitten", "armadillo", "rockerarm", "threeholes", "fertility"}

def load_obj(p):
    V, F = [], []
    for l in open(p):
        a = l.split()
        if not a: continue
        if a[0] == "v": V.append([float(x) for x in a[1:4]])
        elif a[0] == "f": F.append([int(t.split("/")[0]) - 1 for t in a[1:4]])
    return np.array(V, float), np.array(F, np.int64)
def norm(v): mn, mx = float(v.min()), float(v.max()); return (v - (mn + mx) / 2) * (3.2 / max(mx - mn, 1e-6))
def om(V, F):
    import open3d as o3d
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F.astype(np.int32))); m.compute_vertex_normals(); return m
def topo(V, F):
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1); u, cnt = np.unique(E, axis=0, return_counts=True)
    comp = len(set(np.asarray(om(V, F).cluster_connected_triangles()[0]))); used = len(np.unique(F)); chi = used - len(u) + len(F)
    closed = bool((cnt == 2).all())
    return dict(V=int(used), F=int(len(F)), boundary=int((cnt == 1).sum()), nonmanifold=int((cnt > 2).sum()), comps=int(comp), closed=closed, genus=(int((2 * comp - chi) // 2) if closed and comp == 1 else None))
def metrics(V, F, Vg, Fg):   # verbatim
    import open3d as o3d
    # compare_dmesh2.metrics (that file is a script, importing it would re-run its batch)
    a = om(V, F).sample_points_uniformly(50000); b = om(Vg, Fg).sample_points_uniformly(50000); a.estimate_normals(); b.estimate_normals()
    reg = o3d.pipelines.registration.registration_icp(a, b, 0.05, np.eye(4), o3d.pipelines.registration.TransformationEstimationPointToPlane())
    Va = (np.c_[V, np.ones(len(V))] @ reg.transformation.T)[:, :3]
    pa = om(Va, F).sample_points_uniformly(100000); pb = om(Vg, Fg).sample_points_uniformly(100000)
    cd = 0.5 * (np.asarray(pa.compute_point_cloud_distance(pb)).mean() + np.asarray(pb.compute_point_cloud_distance(pa)).mean())
    lo, hi = Vg.min(0) - 0.05, Vg.max(0) + 0.05; g = [np.linspace(lo[i], hi[i], 192, dtype=np.float32) for i in range(3)]; P = np.stack(np.meshgrid(*g, indexing="ij"), -1).reshape(-1, 3)
    def occ(Vx, Fx):
        sc = o3d.t.geometry.RaycastingScene(); sc.add_triangles(o3d.t.geometry.TriangleMesh(o3d.core.Tensor(Vx.astype(np.float32)), o3d.core.Tensor(Fx.astype(np.int32)))); return sc.compute_occupancy(o3d.core.Tensor(P)).numpy() > 0.5
    o1, o2 = occ(Va, F), occ(Vg, Fg)
    return float(cd), float((o1 & o2).sum() / max((o1 | o2).sum(), 1)), float(reg.fitness)


def gt_path(s): return f"{SM}/{s}.obj" if s in CLASSIC else f"{R}/shapes_ext/{s}.obj"

def shapes_all():
    rows = {}
    for f in ("compare_37.jsonl", "compare_c65.jsonl"):
        for l in open(f"{R}/despike/results_genus/dmesh2/{f}"):
            d = json.loads(l); rows[d["shape"]] = d["gt_genus"]
    return rows

def run_one(args):
    shape, variant, gtg = args
    import trimesh
    gv, gf = load_obj(gt_path(shape)); Vg = norm(gv)
    tm = trimesh.Trimesh(Vg, gf, process=False)
    rng = np.random.default_rng(0)
    if variant == "verts":    # RsR's best case: the GT vertices themselves with vertex normals (kitten: closed, genus 1)
        P = np.asarray(tm.vertices); Nrm = np.asarray(tm.vertex_normals)
    else:                     # blue-noise sampling: random sampling left 100-500 boundary edges on kitten/118307, even sampling 4
        P, fid = trimesh.sample.sample_surface_even(tm, N_PTS, seed=0); P = np.asarray(P); Nrm = np.asarray(tm.face_normals)[fid]
    if variant == "noisy":
        from scipy.spatial import cKDTree
        d, _ = cKDTree(P).query(P, k=2); sig = NOISE * float(d[:, 1].mean())
        P = P + rng.normal(0, sig, P.shape)
    wd = tempfile.mkdtemp(prefix=f"rsr_{shape}_{variant}_", dir="/tmp"); od = os.path.join(wd, "out"); os.makedirs(od)
    with open(os.path.join(wd, "pc.obj"), "w") as f:
        for p, n in zip(P, Nrm):
            f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
            if variant != "pca": f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
    cfg = [f"root {wd}", "model_name pc.obj", f"out_root {od}", "out_name rec",
           f"isEuclidean {'false' if variant == 'noisy' else 'true'}", f"isGTNormal {'false' if variant == 'pca' else 'true'}",
           "isNoiseExp false", "isDebug false", "k 30", "r 20", "theta 60", "n 50"]
    if variant == "gtg": cfg.append(f"genus {gtg}")
    open(os.path.join(wd, "cfg.txt"), "w").write("\n".join(cfg) + "\n")
    t0 = time.time(); rec = dict(shape=shape, variant=variant, gt_genus=gtg, n_pts=N_PTS)
    try:
        import resource
        def _lim():   # 2026-10-22: one RsR process reached 37 GB RSS (handle search) and the OOM killer took the whole batch
            resource.setrlimit(resource.RLIMIT_AS, (MEM_GB << 30, MEM_GB << 30))
        p = subprocess.run([RSR, os.path.join(wd, "cfg.txt")], capture_output=True, text=True, timeout=900, cwd=wd, preexec_fn=_lim)
        rec["stdout_tail"] = (p.stdout or "")[-400:]
        rec["rc"] = p.returncode; rec["wall"] = time.time() - t0
        comps = sorted(glob.glob(os.path.join(od, "rec_component_*.obj")))
        if not comps:
            rec["error"] = ("rc=%d " % p.returncode) + ("memory/abort " if p.returncode < 0 or p.returncode > 1 else "") + (p.stderr or p.stdout)[-200:]
            shutil.rmtree(wd, ignore_errors=True); return rec
        Vs, Fs, off = [], [], 0
        for c in comps:
            v, f = load_obj(c)
            if len(f) == 0: continue
            Vs.append(v); Fs.append(f + off); off += len(v)
        V, F = np.vstack(Vs), np.vstack(Fs); t = topo(V, F); rec.update(t); rec["n_components_files"] = len(comps)
        # largest component alone (RsR writes one file per connected component)
        big = max(comps, key=os.path.getsize); vb, fb = load_obj(big); tb = topo(vb, fb); rec["largest"] = tb
        try: cd, iou, fit = metrics(V, F, Vg, gf)
        except Exception as e: cd, iou, fit = float("nan"), float("nan"), 0.0
        rec.update(cd=cd, iou=iou, icp=fit)
        rec["strict"] = bool(t["closed"] and t["comps"] == 1 and t["genus"] == gtg)
        # lenient: fill the small holes a combinatorial method leaves (boundary loops), then the genus of the largest component
        try:
            mb = trimesh.Trimesh(vb, fb, process=False); mb.fill_holes(); tl = topo(np.asarray(mb.vertices), np.asarray(mb.faces))
            rec["lenient"] = dict(closed=tl["closed"], genus=tl["genus"], genus_right=bool(tl["closed"] and tl["genus"] == gtg))
        except Exception as e: rec["lenient"] = dict(closed=False, genus=None, genus_right=False)
        rec["genus_right_largest"] = bool(tb["closed"] and tb["genus"] == gtg)
    except subprocess.TimeoutExpired:
        rec["error"] = "timeout"; rec["wall"] = time.time() - t0
    shutil.rmtree(wd, ignore_errors=True)
    return rec

def summary():
    print(f"{'variant':7s} {'n':>3s} {'closed':>7s} {'1 comp':>7s} {'strict':>7s} {'genus ok (largest)':>19s} {'cd med':>8s} {'iou med':>8s} {'wall med':>9s}")
    for f in sorted(glob.glob(f"{OUT}/rsr_*.jsonl")):
        rows = [json.loads(l) for l in open(f)]
        for r in rows:   # a run that produced no mesh (crash, memory, timeout) is a failure, not a missing sample
            if "error" in r: r.update(closed=False, comps=0, strict=False, genus_right_largest=False, cd=float("nan"), iou=float("nan"), wall=r.get("wall", 0))
        if not rows: continue
        v = rows[0]["variant"]; n = len(rows)
        t10 = [r for r in rows if r["shape"].startswith("t10k")]
        for lab, rr in (("all", rows), ("t10k96", t10)):
            if not rr: continue
            cd = np.nanmedian([r["cd"] for r in rr]); iou = np.nanmedian([r["iou"] for r in rr]); w = np.median([r["wall"] for r in rr])
            print(f"{v:7s} {len(rr):3d} {sum(r['closed'] for r in rr):7d}", end=""); print(f" (no mesh: {sum('error' in r for r in rr)})", end=""); print(f"{'':0s}", end="")
            print(f"{'':1s} {sum(r['comps']==1 for r in rr):7d} {sum(r['strict'] for r in rr):7d} {sum(r['genus_right_largest'] for r in rr):19d} {cd:8.4f} {iou:8.3f} {w:8.1f}s  lenient(fill holes) genus right {sum(r.get('lenient',{}).get('genus_right',False) for r in rr)}  [{lab}]")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--variants", default="verts,clean,gtg,pca,noisy"); ap.add_argument("--shapes", default="")
    ap.add_argument("--jobs", type=int, default=6); ap.add_argument("--summary", action="store_true"); a = ap.parse_args()
    if a.summary: summary(); sys.exit(0)
    S = shapes_all()
    names = a.shapes.split(",") if a.shapes else sorted(S)
    for v in a.variants.split(","):
        outf = f"{OUT}/rsr_{v}.jsonl"; done = set(json.loads(l)["shape"] for l in open(outf)) if os.path.exists(outf) else set()
        todo = [(s, v, S[s]) for s in names if s not in done]
        print(f"[rsr] {v}: {len(todo)} to run ({len(done)} done)", flush=True)
        with ProcessPoolExecutor(a.jobs, mp_context=_mp.get_context("spawn")) as ex:
            for rec in ex.map(run_one, todo):
                open(outf, "a").write(json.dumps(rec) + "\n")
                print(f"[rsr {v}] {rec['shape']}: closed={rec.get('closed')} comps={rec.get('comps')} genus={rec.get('genus')} gt={rec['gt_genus']} strict={rec.get('strict')} cd={rec.get('cd', float('nan')):.4f} wall={rec.get('wall', 0):.0f}s {rec.get('error', '')}", flush=True)
    summary()
