# External benchmark models

Models used by competing papers (Gao, Gu et al., "Inverse Rendering for High-Genus 3D Surface Meshes from Multi-view
Images with Persistent Homology Priors", ICASSP 2026, arXiv 2601.12155).

| file | genus | V / F | source |
|---|---|---|---|
| botijo.obj | 5 | 11495 / 23006 | github.com/Submanifold/BezierGreen data/Botijo/Botijo.obj (classic AIM@Shape model) |
| heptoroid.obj | 22 | 17878 / 35840 | Princeton COS 426 meshes (heptoroid.off; C. Sequin's Heptoroid) |

Both verified closed, edge-manifold, single component; recentred to the bounding-box centre. Use with
`SHAPE_DIR=$PWD/shapes_ext SHAPES=botijo bash despike/golden_chain.sh`.
