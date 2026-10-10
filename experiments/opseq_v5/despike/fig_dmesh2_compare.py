import sys, os, json, numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0,"despike"); sys.path.insert(0,"."); import torch, nvdiffrast.torch as dr
from eval_local_refine import load_obj, normalize_to_range
import run_64v
rows=[json.loads(l) for l in open("despike/results_genus/dmesh2/compare_v71.jsonl")]
rows=[r for r in rows if r["ours_v71"]]; rows.sort(key=lambda r:(r["gt_genus"], r["shape"]))
# ---------- Fig A: per-model Chamfer + VolIoU ----------
fig,(ax1,ax2)=plt.subplots(2,1,figsize=(16,8.5),sharex=True); x=np.arange(len(rows)); w=0.27
cd_d=[r["dmesh2"]["cd"] for r in rows]; cd_5=[r["ours_v65"]["cd"] for r in rows]; cd_7=[r["ours_v71"]["cd"] for r in rows]
ax1.bar(x-w,cd_d,w,color="#9e9e9e",label="DMesh++ (ICCV 25)"); ax1.bar(x,cd_5,w,color="#f4a261",label="ours v6.5"); ax1.bar(x+w,cd_7,w,color="#1f77b4",label="ours v7.1")
for i,r in enumerate(rows):
    if r["ours_v71"]["cd"]<r["dmesh2"]["cd"]: ax1.text(i+w, r["ours_v71"]["cd"]*1.08, "✓", ha="center", fontsize=9, color="#1f77b4")
ax1.set_yscale("log"); ax1.set_ylabel("Chamfer distance (lower is better, log)"); ax1.legend(ncol=3, fontsize=9); ax1.grid(axis="y", alpha=0.3)
ax1.set_title(f"Thingi10K, 31 high-genus models (sorted by genus): Chamfer — v7.1 wins {sum(a<b for a,b in zip(cd_7,cd_d))} : {sum(b<a for a,b in zip(cd_7,cd_d))} (v6.5: {sum(a<b for a,b in zip(cd_5,cd_d))} : {sum(b<a for a,b in zip(cd_5,cd_d))}); medians D++ {np.median(cd_d):.4f} / v6.5 {np.median(cd_5):.4f} / v7.1 {np.median(cd_7):.4f}")
io_d=[r["dmesh2"]["iou"] for r in rows]; io_7=[r["ours_v71"]["iou"] for r in rows]
ax2.bar(x-w/2,io_d,w,color="#9e9e9e",label="DMesh++"); ax2.bar(x+w/2,io_7,w,color="#1f77b4",label="ours v7.1")
for i,r in enumerate(rows):
    g=r["ours_v71"]["genus"]; ok=(g==r["gt_genus"]); ax2.text(i, 0.02, f"{g}/{r['gt_genus']}", ha="center", fontsize=7.5, color="#1f77b4" if ok else "#c0392b", rotation=90)
ax2.set_ylabel("volume IoU (higher is better)"); ax2.set_ylim(0,1.05); ax2.legend(ncol=2, fontsize=9); ax2.grid(axis="y", alpha=0.3)
ax2.set_title(f"Volume IoU, medians D++ {np.median(io_d):.3f} / v7.1 {np.median(io_7):.3f}; closed manifold D++ 0/31, ours 31/31. Labels: our genus / GT (blue = right)", fontsize=10)
ax2.set_xticks(x); ax2.set_xticklabels([r["shape"][5:] for r in rows], rotation=60, fontsize=8)
fig.tight_layout(); fig.savefig("despike/results_genus/fig_thingi10k_dmesh2_metrics.png", dpi=130); print("fig A saved")
# ---------- Fig B: renders GT / DMesh++ / ours ----------
ctx=dr.RasterizeCudaContext()
def shade(V,F,mvps,views,i):
    vt=torch.tensor(np.asarray(V,np.float32),device="cuda"); ft=torch.tensor(np.asarray(F,np.int32),device="cuda")
    with torch.no_grad(): sil,z,fg,diff=run_64v.render_sdd(ctx,vt,ft,mvps[i],views[i])
    d=diff.cpu().numpy(); f=fg.cpu().numpy(); img=np.ones_like(d); img[f]=0.25+0.7*d[f]; return img
picks=[("t10k_81291","thin plate, v7 fix"),("t10k_113858","thin walls, genus 9"),("t10k_135222","CD 0.0070 vs 0.0161"),("t10k_399564","genus 7, tie"),("t10k_1432740","loss: 0.0497 vs 0.0330"),("t10k_472194","loss: tunnels 2/4")]
VIEW=int(os.environ.get("FIG_VIEW","9"))
fig,axs=plt.subplots(len(picks),3,figsize=(10.5,3.4*len(picks)))
for r_i,(s,note) in enumerate(picks):
    gv,gf=load_obj(f"shapes_ext/{s}.obj"); g=normalize_to_range(gv); gf=np.asarray(gf,np.int64)
    mvps,views=run_64v.star_cameras(float(np.linalg.norm(g,axis=1).max()))
    rec=[r for r in rows if r["shape"]==s][0]
    d2=np.load(f"despike/results_genus/dmesh2/{s}.npz"); ours=np.load(f"despike/results_genus/{s}_v71_auto.npz")
    for c,(V,F,title) in enumerate([(g,gf,f"GT  genus {rec['gt_genus']}"),(d2["verts"],d2["tris"],f"DMesh++  CD {rec['dmesh2']['cd']:.4f}\n{rec['dmesh2']['boundary']} boundary edges, {rec['dmesh2']['comps']} components, genus n/a"),(ours["verts"],ours["tris"],f"ours v7.1  CD {rec['ours_v71']['cd']:.4f}\nclosed, genus {rec['ours_v71']['genus']}/{rec['gt_genus']}")]):
        ax=axs[r_i,c]; ax.imshow(shade(V,F,mvps,views,VIEW),cmap="gray",vmin=0,vmax=1); ax.axis("off"); ax.set_title(title,fontsize=9, color=("#c0392b" if c==2 and rec['ours_v71']['genus']!=rec['gt_genus'] else "k"))
    axs[r_i,0].text(-0.02,0.5,f"{s[5:]}\n{note}",transform=axs[r_i,0].transAxes,rotation=90,va="center",ha="right",fontsize=9)
fig.suptitle("Thingi10K: ground truth / DMesh++ (official code, same 64 views) / ours v7.1 — same camera, flat shading", fontsize=11)
fig.tight_layout(rect=[0,0,1,0.985]); fig.savefig("despike/results_genus/fig_thingi10k_dmesh2_renders.png", dpi=120); print("fig B saved")
