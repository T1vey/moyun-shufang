# Full historical trajectory replay — FP32 kernel

This is offline host execution of the same frozen HLS C++ kernel, not robot motion or a board timing measurement. The native wall time must not be used as FPGA throughput.

The record contains 21,680 nodes; node 0 is the recorded home seed. All 21,679 following targets were processed in order, in 64-point batches (final batch 47 points), and each batch used the preceding accepted joint solution as seed. No batch used a fresh recorded seed.

**21,679/21,679 targets accepted by the PL algorithm model; zero CPU fallback, zero unresolved points, zero rejected batches.** All 339 calls completed. Every recorded q/position was independently checked first: all source nodes meet the original fixed-pose/model tolerances.

| Metric | Median | P95 | P99 | Maximum |
|---|---:|---:|---:|---:|
| Position error (m) | 8.59031278e-08 | 2.01885807e-07 | 2.60887683e-07 | 3.93823416e-07 |
| Orientation error (rad) | 2.75224405e-07 | 5.6305221e-07 | 7.2398232e-07 | 1.10151036e-06 |
| Largest joint change between neighbors (rad) | 0.00134432316 | 0.00236940384 | 0.0026631999 | 0.00295543671 |
| Difference from historical redundant joint solution (rad) | 0.0599075923 | 0.178517975 | 0.227101433 | 0.263921647 |

Original strict tolerance (1e-7 m / 1e-6 rad): 12,838/21,679 points. Declared FP32 offline budget (1e-5 m / 1e-4 rad): 21,679/21,679. These are different criteria and are not conflated.

All motion phases in the historical record were retained, including pen-down, pen-up/travel and transition points; phase codes and per-phase counts are preserved in summary.json. The final source attribution is the recorded controller-DH model, not a substitute URDF.

No fallback occurred in this particular trajectory. That does not establish a zero fallback rate for arbitrary reachable poses, near-singular configurations, other paper placements or other models. The tested kernel still has explicit conditioning/model/joint-limit domain restrictions.

Artifacts: rows.csv records every target, output q, error and step; calls.csv records every batch status; recorded_preflight.csv checks original input consistency; summary.json holds quantiles, model/source hashes and phase statistics. Formal hardware source was not changed.
