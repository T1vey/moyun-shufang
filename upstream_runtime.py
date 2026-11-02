"""Load byte-identical E1pco modules without its broken package __init__."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import threading

ROOT = Path(__file__).resolve().parent/'vendor/e1pco'
_loaded = None
_lock = threading.RLock()


def load_upstream():
    with _lock:
        return _load_upstream()


def _load_upstream():
    global _loaded
    if _loaded is not None:
        return _loaded
    origin = json.loads((ROOT/'ORIGIN.json').read_text(encoding='utf-8'))
    for rel, digest in origin['files'].items():
        if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() != digest:
            raise ValueError('上游原文件哈希变化：'+rel)
    # An isolated package supports relative imports. The original wrapper also
    # imports ik.utils absolutely, so alias just for its import, then restore.
    package_name = '_so101_e1pco_ik'
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT/'others/ik')]
    sys.modules[package_name] = package
    def module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        obj = importlib.util.module_from_spec(spec)
        sys.modules[name] = obj
        spec.loader.exec_module(obj)
        return obj
    utils = module(package_name+'.utils', ROOT/'others/ik/utils.py')
    robot = module(package_name+'.robot', ROOT/'others/ik/robot.py')
    old = {name: sys.modules.get(name) for name in ('ik','ik.utils')}
    try:
        sys.modules.update({'ik':package, 'ik.utils':utils})
        wrapper = module('_so101_e1pco_wrapper',ROOT/'others/hw_solver_wrapper.py')
    finally:
        for name, obj in old.items():
            if obj is None:
                sys.modules.pop(name,None)
            else:
                sys.modules[name] = obj
    _loaded = (robot, wrapper, utils)
    return _loaded
