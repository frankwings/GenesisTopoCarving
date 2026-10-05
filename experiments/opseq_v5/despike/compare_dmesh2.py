import os, sys, re, json, glob, numpy as np
R = "/home/kingy/Projects/Genesis/GenesisTopmod/experiments/opseq_v5"; os.chdir(R)
sys.path.insert(0, "despike"); sys.path.insert(0, "."); os.environ["SHAPE_DIR"] = f"{R}/shapes_ext"; os.environ.setdefault("MODE", "64v")
import open3d as o3d
OUT = "/tmp/cmp_dmesh2.jsonl"; done = {json.loads(l)["shape"] for l in open(OUT)} if os.path.exists(OUT) else set()
ours_tag = {"kitten": "fx1", "armadillo": "fx1", "rockerarm": "fx1", "threeholes": "fx1", "fertility": "hf1", "botijo": "fx1"}
SM = "/home/kingy/Projects/Genesis/GenesisExp/GenesisHunyuan/.venv/lib/python3.12/site-packages/pymeshlab/tests/sample_meshes"
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
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F.astype(np.int32))); m.compute_vertex_normals(); return m
def topo(V, F):
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1); u, cnt = np.unique(E, axis=0, return_counts=True)
    comp = len(set(np.asarray(om(V, F).cluster_connected_triangles()[0]))); used = len(np.unique(F)); chi = used - len(u) + len(F)
    closed = bool((cnt == 2).all())
    return dict(V=int(used), F=int(len(F)), boundary=int((cnt == 1).sum()), nonmanifold=int((cnt > 2).sum()), comps=int(comp), closed=closed, genus=(int((2 * comp - chi) // 2) if closed and comp == 1 else None))
def metrics(V, F, Vg, Fg):
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
for f in sorted(glob.glob("despike/results_genus/dmesh2/*.npz")):
    shape = os.path.basename(f)[:-4]
    if shape in done: continue
    src = f"{SM}/{shape}.obj" if shape in ours_tag and shape != "botijo" else f"{R}/shapes_ext/{shape}.obj"
    gv, gf = load_obj(src); Vg = norm(gv)
    rec = dict(shape=shape); gt = topo(Vg, gf); rec["gt_genus"] = gt["genus"]
    for who, p in (("dmesh2", f), ("ours", f"despike/results_genus/{shape}_{ours_tag.get(shape, 'b2')}_auto.npz")):
        if not os.path.exists(p): rec[who] = None; continue
        z = np.load(p); V, F = z["verts"].astype(float), z["tris"].astype(np.int64); t = topo(V, F)
        try: cd, iou, fit = metrics(V, F, Vg, gf)
        except Exception as e: cd, iou, fit = float("nan"), float("nan"), 0.0
        t.update(cd=cd, iou=iou, icp=fit, wall=float(z["wall"]) if "wall" in z.files else None); rec[who] = t
    open(OUT, "a").write(json.dumps(rec) + "\n"); print(shape, "done", flush=True)
