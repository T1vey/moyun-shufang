"""Read-only upstream ET oracle, loaded without the broken package __init__.

No upstream file is copied or changed. This executes et.py directly; it does
not reproduce the original complete HLS/wrapper iteration. See source ledger.
"""
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("R1A_UPSTREAM_DIR", ROOT.parent / "snapshot_20260924_023154_3218/reference/upstream"))


def chain():
    spec = importlib.util.spec_from_file_location("frozen_upstream_et", UPSTREAM / "others/ik/et.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    et = module.ET
    # Independently transcribed from the active chain in robot.py, not from
    # our model JSON. SI constants and full ordering are intentional.
    return (et.tx(.0612) * et.tz(.0598) * et.Rz()
            * et.tx(.02943) * et.tz(.05504) * et.Ry()
            * et.tx(.02798) * et.tz(.1127) * et.Ry()
            * et.tx(.15504) * et.tz(.00519) * et.Ry()
            * et.tx(.0593) * et.tz(.00996) * et.Rx())
