---
name: pynq-release-audit
description: Read-only audit of PYNQ release manifests, bit/HWH pairing and artifact hashes before deployment or publication. Use for PYNQ release packaging and evidence review across boards.
---

# PYNQ release audit

Inspect the selected release, not whichever overlay was last opened. Record board/part, ABI, clock, build ID and tool version from its manifest and associated reports.

Run `python scripts/audit_overlay.py /path/to/platform.json` relative to this skill directory. It checks explicit artifact paths and hashes recursively without loading an overlay or contacting hardware. A source-only checkout can legitimately report missing generated artifacts; label it as source-only rather than board-ready.

Read the HWH clock and register metadata alongside the manifest. Do not infer compatibility from the FPGA model alone: DDR/MIO, board wiring and register ABI must also match. Keep bit, HWH and register metadata from the same build.

Report HLS estimates, RTL simulation, routed timing/resources and board measurements separately. Attach the source file for every headline number. Compute throughput from valid points and transaction cycles; include the clock and identify whether host scheduling/cache costs were measured.

This workflow was derived from a seven-axis drawing system where RTL reached about 116k points/s while board scheduling delivered about 2k points/s, and from reports superseded by later board-deployment records. Read dated follow-up reports before stating that a version was or was not deployed.

The helper is a local consistency check, not proof of hardware correctness. Deployment or robot motion needs the user's actual task authorization and the project's hardware acceptance workflow.
