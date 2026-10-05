"""Run DMesh++ (official code, config mvrecon_thingi10k.yaml) on our shapes and bring the result into our frame."""
import os, sys, time, glob, subprocess, json, numpy as np
D2 = "/home/kingy/Projects/Genesis/GenesisExp/GenesisDMesh2"; PY = f"{D2}/.venv/bin/python"
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; OUT = f"{R}/despike/results_genus/dmesh2"
SM = "/home/kingy/Projects/Genesis/GenesisExp/GenesisHunyuan/.venv/lib/python3.12/site-packages/pymeshlab/tests/sample_meshes"
shapes = [(s, f"{SM}/{s}.obj") for s in ["kitten", "armadillo", "rockerarm", "threeholes", "fertility"]] + [("botijo", f"{R}/shapes_ext/botijo.obj")]
shapes += [(f"t10k_{l.split()[0]}", f"{R}/shapes_ext/t10k_{l.split()[0]}.obj") for l in open("/tmp/t10k_batch_list.txt")]
def smi():
    try: return int(subprocess.run(["/usr/lib/wsl/lib/nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.split()[0])
    except Exception: return -1
def load_obj(p):
    V, F = [], []
    for l in open(p):
        a = l.split()
        if not a: continue
        if a[0] == "v": V.append([float(x) for x in a[1:4]])
        elif a[0] == "f": F.append([int(t.split("/")[0]) - 1 for t in a[1:4]])
    return np.array(V, float), np.array(F, np.int64)
env = dict(os.environ, TORCH_CUDA_ARCH_LIST="12.0")
for name, src in shapes:
    dst = f"{OUT}/{name}.npz"
    if os.path.exists(dst): print(f"[D2 {name}] skip (exists)", flush=True); continue
    while smi() > 24000: print(f"[D2 {name}] GPU busy ({smi()} MiB used), waiting", flush=True); time.sleep(60)
    base = smi(); t0 = time.time()
    # their generator names the input folder after the file stem
    g = subprocess.run([PY, "input/generate_mvrecon_3d_input.py", "--input-path", src], cwd=D2, env=env, capture_output=True, text=True)
    inp = f"{D2}/input/3d/mvrecon/{os.path.splitext(os.path.basename(src))[0]}"
    if not os.path.exists(f"{inp}/mv.npy"): print(f"[D2 {name}] input generation FAILED: {(g.stderr or g.stdout)[-300:]}", flush=True); continue
    before = set(glob.glob(f"{D2}/exp/result/d3/mvrecon/*"))
    p = subprocess.Popen([PY, "mvrecon_3d.py", "--config", "exp/config/d3/mvrecon_thingi10k.yaml", "--input-path", inp + "/"], cwd=D2, env=env, stdout=open(f"/tmp/d2_{name}.log", "w"), stderr=subprocess.STDOUT)
    peak = base
    while p.poll() is None:
        peak = max(peak, smi()); time.sleep(5)
        if time.time() - t0 > 3600: p.kill(); break
    wall = time.time() - t0
    new = sorted(set(glob.glob(f"{D2}/exp/result/d3/mvrecon/*")) - before)
    res = f"{new[-1]}/result/mesh.obj" if new else None
    if p.returncode != 0 or not res or not os.path.exists(res):
        print(f"[D2 {name}] FAILED rc={p.returncode} after {wall:.0f}s (log /tmp/d2_{name}.log)", flush=True); continue
    V, F = load_obj(res)
    # undo their normalisation ((v - mean) / max_norm * 0.8), then apply ours (scalar centre + 3.2 / extent)
    gv, _ = load_obj(src); mean = gv.mean(0); mx = np.linalg.norm(gv - mean, axis=1).max() + 1e-6
    Vs = V * mx / 1.0 + mean   # they call the importer with scale=DOMAIN=1.0, not its 0.8 default; mn_, mx_ = float(gv.min()), float(gv.max()); Vn = (Vs - (mn_ + mx_) / 2) * (0.8 * 4.0 / max(mx_ - mn_, 1e-6))
    np.savez(dst, verts=Vn.astype(np.float32), tris=F.astype(np.int32), wall=wall, src=res, scale_fixed=1)
    print(f"[D2 {name}] ok V={len(V)} F={len(F)} wall {wall:.0f}s | GPU: {base} MiB before, peak {peak} MiB (this job ~{max(peak - base, 0)} MiB)", flush=True)
print("[D2] ALL DONE", flush=True)
