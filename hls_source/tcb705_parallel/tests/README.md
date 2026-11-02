# Parallel seven-axis kernel validation

These test files do not connect to a controller, write a bitstream, or modify the production planner. They call only the candidate C/HLS top function `tcb_planner_parallel`.

## Inputs and independent checks

Add the existing `../../tcb705/vectors.txt` as a testbench data file. Its IK tolerances are **1e-7 m position and 1e-6 rad orientation**. They are not relaxed for the parallel implementation. The reference chain uses the previous FP64 solver; output poses are additionally evaluated using an independent FP64, standard-trigonometric, full-4x4-matrix implementation. Seven-axis joint solutions need not be bit-identical, so joint differences from the previous solver are reported separately from pose acceptance.

`tb_parallel.cpp` covers the original two points; a 64-point 0.5 mm straight line; a 32-point 0.4 mm circular arc; a 16-point 0.5 mm vertical lift; 32 reproducible, randomized FK poses; ABI/model/metadata/bounds guards; NaN/Inf; cancellation with current and stale generation IDs; and unreachable targets. Any IK row declared successful by the candidate must pass the independent original tolerance and joint-limit checks. Adjacent accepted solutions must stay within the production 0.12 rad joint-step ceiling. `PARTIAL` is accepted only as a correctly marked CPU fallback, not as a successfully computed point.

The FK random test requires translation and rotation-matrix entry differences no greater than 1e-9. This candidate retains FP64 arithmetic. The production host's FP64 verification remains necessary.

To validate the testbench against the original implementation, compile with `TCB_TEST_BASELINE` defined, link the unchanged original `tcb_planner_accel.cpp`, and add `baseline_adapter.cpp`. Do not add that adapter to the candidate HLS build.

`tb_parallel_stress.cpp` is an additional host-only test: 128 reproducible random starting poses, each followed by eight distinct 0.2 mm targets, for 1,024 attempted points. Targets keep the seed's orientation and alternate Cartesian axes, direction, and small curves. It uses the same strict independent acceptance checks and reports old/new accepted coverage, fallback batches, pose errors, and joint discontinuity. It does not replace the real-path RTL throughput benchmark.

`tb_parallel_predictor.cpp` validates the optional smooth-path quadratic initial guess against 90-degree and 180-degree turns, repeated targets, alternating 0.2/0.8 mm steps, zigzags, a 5 mm jump, points just inside/outside the spacing guard, and a NaN following eight valid targets. It independently reconstructs the documented initial-guess rules and checks zero-iteration outputs exactly. Every zero-iteration success still passes the independent FP64 pose test. All test logs separate accepted points needing zero, one, or multiple iterations; header iteration totals must equal the sum of row statistics.

## Throughput measurement

`tb_parallel_throughput.cpp` is a **single 64-point transaction**, every target advances by 0.5 mm. It requires all 64 results to pass the original FP64 checks; repeated identical points and rejected candidates do not count.

At 100 MHz:

`valid_points_per_second = 64 * 100000000 / transaction_cycles`

Therefore **greater than 100,000 valid points/s requires fewer than 64,000 transaction cycles**, inclusive of configuration, AXI transfer, and result writes. Use RTL co-simulation cycles, and then post-route timing/board measurement. C simulation wall time is not hardware throughput. A 10 ns HLS clock constraint is a request, not proof of 100 MHz timing closure.

If the full suite reports PARTIAL but otherwise passes, report the verified coverage and fallback count. Do not claim the throughput target has been met. No test authorizes installing the candidate or issuing robot motion.
