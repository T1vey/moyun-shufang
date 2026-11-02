# Optional FP64 planning kernels

`geometry.cpp` implements bounded batches of generic five-joint FK and geometric
measurements. `Model.pose_many` and smooth motion's `_measure_rows` call it when a
matching library is present. It never opens hardware, quantizes servo counts or
changes the authoritative NumPy FP64 Horner samples. It is not a full native
PlanSession or a PL kernel.

Build directly on the target ARM Linux environment with `python3 native/build.py
--cxx g++`. Cross compilation is supported with `--cxx arm-linux-gnueabihf-g++
--platform linux --output native/build/libso101_geometry.so`; use the target
sysroot/toolchain. The build disables fast math, reassociation and FP contraction.
Deploy both the library and its `.json` build manifest with these sources.
The host DLL is not an ARM artifact and must never be copied as one.

Loading checks the ABI, FP64 rounding environment, source digest and binary digest.
Missing or mismatched libraries fall back to NumPy. `SO101_NATIVE_GEOMETRY=off`
forces the original path; `SO101_NATIVE_LIBRARY` selects a matching library.
`native.geometry.status()` reports the actual selection. Restart after rebuilding.

Run `python -m unittest discover -s tests -p test_native_geometry.py -v` after
building. Acceptance includes calibrated arbitrary axes, zero/tiny segments,
multiple batches, unchanged authoritative Horner outputs and the frozen face
plan's exact commands/counts/probe coverage. Desktop results do not establish
ARM throughput or board acceptance.
