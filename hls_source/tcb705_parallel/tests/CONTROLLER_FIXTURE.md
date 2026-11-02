# Controller-DH regression fixture

This fixture reads `build/tcb705/startup_speed_20261020/machine.json` and `nodes.json`. The machine record explicitly identifies `kinematics.source=controller_dh`, read from `r_dh_1_`, controller version 1.9.71, dated 2026-10-18. It is **not the URDF/demo model**.

The exact source SHA256 values are embedded in `controller_dh_fixture.hpp`, along with the application model-conversion source hash. The generator preserves the application's DH convention and the saved floating-point constants, including cosine-of-90-degree roundoff. It does not snap matrices or fit new geometry.

`nodes.json` stores planned Cartesian positions and SDK joint angles. Node 0's SDK joints match the recorded home joints to within 2.23e-16 rad; this establishes the replay seed without guessing or using the unrelated `q_start_rad`. Each replay chunk uses the saved preceding node's SDK-to-model joints. The SDK mapping is explicitly checked to be identity for this fixture. The 193 prefix nodes and 65 nodes from the first sufficiently long DRAW phase all pass independent FP64 FK checks against their saved positions and the machine's tool rotation before the candidate runs.

The associated historical benchmark records `physical_motion=false`. These tests are offline numerical replays using recorded controller parameters and planned nodes. They do not prove that a current controller is connected, that the historical path was physically executed, or that current calibration is correct.

## Independent test programs

- `tb_parallel_controller.cpp`: 352 targets, covering a synthetic 64-point line with 0.5 mm steps from the recorded home seed; saved nodes 1–64, 65–128, and 129–192; 64 targets from the first long DRAW run (saved node indices 4415–4478); and a synthetic 90-degree corner.
- `tb_parallel_controller_throughput.cpp`: exactly three 64-point transactions: synthetic line, saved prefix, saved DRAW trajectory. All 192 results must pass the original position/orientation tolerances.
- `controller_test_support.hpp`: standalone support so the original regression test and its include file remain untouched during an ongoing co-simulation. Pose checking uses full 4x4 matrix products with standard-library FP64 trigonometry. The old solver supplies a separate joint-solution reference.

The generator and tests neither contact the board nor send motion commands. `controller_throughput.cfg` is a new independent HLS profile; `parallel_controller_100mhz.cfg` runs the fuller regression.

## Historical iterative-candidate host result (before R6)

All 352 candidate targets and all 352 old-solver targets pass. Candidate iteration totals by case are 40, 38, 40, 40, 54, 17; old totals are 65, 66, 65, 65, 75, 34. Candidate maximum position error is below 1e-7 m and orientation error below 1e-6 rad. Detailed logs are in `build/tcb705/parallel_20261024/controller_validation`.

These host results validate numerical behavior only. Hardware throughput requires each actual RTL transaction's cycle count, and 100 MHz operation requires implementation timing evidence.

## Analytic DATAFLOW candidate (R6 and later)

The analytic SRS producer also passes all 352 targets, followed by an independent
original-model FK consumer. Its numerical iteration count is zero; the iterative
counts above do not describe this version. The controller fixture and acceptance
tolerances remain the same. Separate contract tests cover producer rejection,
consumer rejection, cancellation, prefix-only writes and bounded FIFO draining.
See the versioned host, RTL and implementation receipts rather than combining
measurements from different source snapshots.
