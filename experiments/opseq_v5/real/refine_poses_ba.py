"""refine_poses_ba.py <dataset_dir> : refine the ARKit-seeded COLMAP model with SIFT matches + triangulation + bundle adjustment
(v8 pose refinement, 2026-10-17). ARKit VIO drifts a few mm over a 1-2 min orbit (hull/mask consistency 0.998 on the first
40 frames, 0.98 on the last); the silhouette hull is eroded by that drift and loses thin parts (mug handle). Seeded BA keeps
every frame registered (no incremental mapping) and refines poses + focal on image features. Writes sparse/0 (backup in
sparse/arkit) and prints reprojection error / registered count."""
import sys, os, shutil, numpy as np, pycolmap
D = sys.argv[1]; img = f"{D}/images"; dbp = f"{D}/ba.db"; seed = f"{D}/sparse/arkit"
if not os.path.exists(seed): shutil.copytree(f"{D}/sparse/0", seed)
if os.path.exists(dbp): os.remove(dbp)
ro = pycolmap.ImageReaderOptions(); ro.camera_model = "SIMPLE_RADIAL"
eo = pycolmap.FeatureExtractionOptions(); eo.sift.max_num_features = int(os.environ.get("SIFT_N", "8000")); eo.sift.estimate_affine_shape = True; eo.sift.domain_size_pooling = True
pycolmap.extract_features(dbp, img, camera_mode=pycolmap.CameraMode.SINGLE, reader_options=ro, extraction_options=eo)
po = pycolmap.SequentialPairingOptions(); po.overlap = int(os.environ.get("SEQ_OVERLAP", "20"))
pycolmap.match_sequential(dbp, pairing_options=po)
if int(os.environ.get("EXHAUSTIVE", "0")): pycolmap.match_exhaustive(dbp)
# seed model: ARKit poses, image ids must match the database
db = pycolmap.Database.open(dbp); ims = {im.name: im.image_id for im in db.read_all_images()}; cam_id = db.read_all_images()[0].camera_id; db.close()
rec0 = pycolmap.Reconstruction(seed); cam0 = list(rec0.cameras.values())[0]
txt = f"{D}/ba_seed_txt"; shutil.rmtree(txt, ignore_errors=True); os.makedirs(txt)
open(f"{txt}/cameras.txt", "w").write(f"{cam_id} SIMPLE_RADIAL {cam0.width} {cam0.height} {cam0.params[0]} {cam0.params[1]} {cam0.params[2]} 0\n")
with open(f"{txt}/images.txt", "w") as fo:
    for im in rec0.images.values():
        if im.name not in ims: continue
        cfw = im.cam_from_world(); q = cfw.rotation.quat; t = cfw.translation      # pycolmap quat = (x, y, z, w)
        fo.write(f"{ims[im.name]} {q[3]} {q[0]} {q[1]} {q[2]} {t[0]} {t[1]} {t[2]} {cam_id} {im.name}\n\n")
open(f"{txt}/points3D.txt", "w").write("")
rec = pycolmap.Reconstruction(txt)
o = pycolmap.IncrementalPipelineOptions(); o.triangulation.ignore_two_view_tracks = False; o.triangulation.min_angle = 1.0
for rnd in range(int(os.environ.get("BA_ROUNDS", "3"))):
    rec = pycolmap.triangulate_points(rec, dbp, img, f"{D}/ba_r{rnd}", clear_points=True, options=o)
    bo = pycolmap.BundleAdjustmentOptions(); bo.refine_focal_length = True; bo.refine_extra_params = rnd > 0; bo.refine_principal_point = False
    pycolmap.bundle_adjustment(rec, bo)
    print(f"[ba] round {rnd}: {rec.num_points3D()} points, reproj {rec.compute_mean_reprojection_error():.2f} px, focal {list(rec.cameras.values())[0].params[0]:.1f}, registered {sum(im.has_pose for im in rec.images.values())}/{len(rec.images)}", flush=True)
# pose change vs ARKit
dR, dt = [], []
for im in rec.images.values():
    if not im.has_pose or im.name not in {i.name for i in rec0.images.values()}: continue
    i0 = [i for i in rec0.images.values() if i.name == im.name][0]
    R0 = i0.cam_from_world().rotation.matrix(); t0 = i0.cam_from_world().translation; R1 = im.cam_from_world().rotation.matrix(); t1 = im.cam_from_world().translation
    dR.append(np.degrees(np.arccos(np.clip((np.trace(R0.T @ R1) - 1) / 2, -1, 1)))); dt.append(np.linalg.norm((-R0.T @ t0) - (-R1.T @ t1)))
print(f"[ba] pose change vs ARKit: rotation median {np.median(dR):.3f} deg (max {np.max(dR):.2f}), centre median {np.median(dt)*1000:.1f} mm (max {np.max(dt)*1000:.1f})")
out = f"{D}/sparse/0"; shutil.rmtree(out); os.makedirs(out); rec.write(out); print(f"[ba] wrote {out} (ARKit backup in {seed})")
