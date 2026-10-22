#!/usr/bin/env python3
"""run_sap_batch.py: Shape-As-Points (Peng et al. NeurIPS 2021, GenesisExp/GenesisSAP, pytorch3d-free patch) on the same
102 point clouds as the RsR baseline (60k blue-noise samples + face normals, GenesisSAP/data/ours/*.ply), authors'
Thingi10K optimisation config (configs/optim_based/thingi.yaml: sphere init, 20k points, grid 128^3, sigma 2, 1600
epochs, Chamfer only). Output: despike/results_genus/sap/sap.jsonl (topo of the full mesh and of the largest component,
cd/iou vs GT in the compare_dmesh2 frame, wall). Usage: python3 despike/run_sap_batch.py [--jobs 3] [--shapes a,b] [--summary]"""
import os, sys, json, time, glob, argparse, subprocess
import numpy as np, importlib.util
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; SAP = "/home/kingy/Projects/Genesis/GenesisExp/GenesisSAP"
PY = "/home/kingy/venvs/sap/bin/python"; OUT = f"{R}/despike/results_genus/sap"; os.makedirs(OUT, exist_ok=True)
sp = importlib.util.spec_from_file_location("rb", f"{R}/despike/run_rsr_batch.py"); rb = importlib.util.module_from_spec(sp); sp.loader.exec_module(rb)

def run_one(args):
    shape, gtg = args
    od = f"{OUT}/runs/{shape}"; os.makedirs(od, exist_ok=True)
    cfg = f"{od}/cfg.yaml"
    open(cfg, "w").write(f"inherit_from: configs/optim_based/thingi.yaml\ndata:\n  data_path: '{SAP}/data/ours/{shape}.ply'\n  object_id: -1\ntrain:\n  out_dir: {od}/out\n  save_every: 1600\n  checkpoint_every: 100000\n  print_every: 400\n  visualize_every: 100000\n  o3d_vis_pcl: False\n  exp_pcl: False\n")
    t0 = time.time(); rec = dict(shape=shape, gt_genus=gtg)
    p = subprocess.run([PY, "optim.py", cfg], cwd=SAP, capture_output=True, text=True, timeout=3600, env=dict(os.environ, TORCH_CUDA_ARCH_LIST="12.0"))
    rec["wall"] = time.time() - t0; rec["rc"] = p.returncode
    meshes = sorted(glob.glob(f"{od}/out/vis/mesh/*.ply"))
    if not meshes: rec["error"] = (p.stderr or p.stdout)[-300:]; return rec
    import trimesh
    m = trimesh.load(meshes[-1], force="mesh"); V, F = np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)
    gv, gf = rb.load_obj(rb.gt_path(shape)); Vg = rb.norm(gv)
    t = rb.topo(V, F); rec.update(t); rec["mesh"] = meshes[-1]
    parts = m.split(only_watertight=False); big = max(parts, key=lambda q: len(q.faces)) if len(parts) else m
    tb = rb.topo(np.asarray(big.vertices, float), np.asarray(big.faces, np.int64)); rec["largest"] = tb
    try: cd, iou, fit = rb.metrics(V, F, Vg, gf)
    except Exception: cd, iou, fit = float("nan"), float("nan"), 0.0
    rec.update(cd=cd, iou=iou, icp=fit)
    rec["strict"] = bool(t["closed"] and t["comps"] == 1 and t["genus"] == gtg)
    rec["genus_right_largest"] = bool(tb["closed"] and tb["genus"] == gtg)
    return rec

def summary():
    rows = [json.loads(l) for l in open(f"{OUT}/sap.jsonl")]
    for r in rows:
        if "error" in r: r.update(closed=False, comps=0, strict=False, genus_right_largest=False, cd=float("nan"), iou=float("nan"))
    for lab, rr in (("all", rows), ("t10k96", [r for r in rows if r["shape"].startswith("t10k")])):
        if not rr: continue
        print(f"SAP {lab}: n={len(rr)} closed={sum(r['closed'] for r in rr)} 1comp={sum(r['comps']==1 for r in rr)} strict={sum(r['strict'] for r in rr)} genus_ok_largest={sum(r['genus_right_largest'] for r in rr)} cd_med={np.nanmedian([r['cd'] for r in rr]):.4f} iou_med={np.nanmedian([r['iou'] for r in rr]):.3f} wall_med={np.median([r['wall'] for r in rr]):.0f}s no_mesh={sum('error' in r for r in rr)}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--jobs", type=int, default=3); ap.add_argument("--shapes", default=""); ap.add_argument("--summary", action="store_true"); a = ap.parse_args()
    if a.summary: summary(); sys.exit(0)
    S = rb.shapes_all(); names = a.shapes.split(",") if a.shapes else sorted(S)
    outf = f"{OUT}/sap.jsonl"; done = set(json.loads(l)["shape"] for l in open(outf)) if os.path.exists(outf) else set()
    todo = [(s, S[s]) for s in names if s not in done]; print(f"[sap] {len(todo)} to run ({len(done)} done)", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(a.jobs) as ex:
        for rec in ex.map(run_one, todo):
            open(outf, "a").write(json.dumps(rec) + "\n")
            print(f"[sap] {rec['shape']}: closed={rec.get('closed')} comps={rec.get('comps')} genus={rec.get('genus')} gt={rec['gt_genus']} strict={rec.get('strict')} cd={rec.get('cd', float('nan')):.4f} wall={rec['wall']:.0f}s {rec.get('error', '')[:80]}", flush=True)
    summary()
