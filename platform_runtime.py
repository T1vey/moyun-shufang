"""Identity checks for a single Linux display + IK platform per boot.

Application restart must never reprogram the FPGA or reset display clocks.
The root-owned boot receipt is written only by scripts/load_platform.py.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import xml.etree.ElementTree as ET

READY = '/run/so101-platform/ready.json'
BOOT_ID = '/proc/sys/kernel/random/boot_id'
TARGET_ABI = 'so101-ik-target-v1'
PLANNER_ABI = 'so101-planner-accel-v2'
TCB_ABI = 'tcb705-planner-accel-v1'
TCB_FP32_ABI = 'tcb705-planner-fp32-v2'


def accelerator_identity(cfg):
    """Old manifests remain target-only; v2 requires an explicit sealed identity."""
    abi = cfg.get('accelerator_abi', TARGET_ABI)
    if abi not in (TARGET_ABI, PLANNER_ABI, TCB_ABI, TCB_FP32_ABI):
        raise ValueError('Unsupported platform accelerator ABI')
    ip = cfg.get('ip_name', 'z20_ik_target_0' if abi == TARGET_ABI else None)
    if not isinstance(ip, str) or not ip:
        raise ValueError('Planner platform requires an explicit ip_name')
    return abi, ip


def display_backend(cfg):
    backend = cfg.get('display_backend', 'kernel-drm')
    if backend not in ('kernel-drm', 'pynq-mmio'):
        raise ValueError('Unsupported platform display backend')
    return backend


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def target_address(bitfile, ip_name):
    tree = ET.parse(Path(bitfile).with_suffix('.hwh')).getroot()
    ranges = {(int(m.get('BASEVALUE'), 0), int(m.get('HIGHVALUE'), 0))
              for m in tree.iter('MEMRANGE') if m.get('INSTANCE') == ip_name}
    if len(ranges) != 1:
        raise ValueError('Expected one unambiguous IK address window')
    base, high = ranges.pop()
    if base != 0x40000000 or high - base + 1 != 65536:
        raise ValueError('Fused platform must preserve IK at 0x40000000 / 64K')
    return base, high - base + 1


def validate_manifest(path, kernel_release=None):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8'))
    if cfg.get('schema') != 'so101-platform-v1' or not isinstance(cfg.get('build_id'), str) or not cfg['build_id']:
        raise ValueError('Invalid platform manifest identity')
    if cfg.get('display') != 'md0700r-1024x600':
        raise ValueError('This platform release targets MD0700R 1024x600')
    files = cfg.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Platform files are not sealed')
    for name, expected in files.items():
        rel = Path(name)
        candidate = (path.parent / rel).resolve()
        if rel.is_absolute() or rel.name != name or candidate.parent != path.parent:
            raise ValueError('Platform artifacts must be direct children of their release')
        if not isinstance(expected, str) or digest(candidate) != expected:
            raise ValueError('Platform file hash mismatch: ' + name)
    display = display_backend(cfg)
    for key in (('bitfile', 'dtbo') if display == 'kernel-drm' else ('bitfile',)):
        value = cfg.get(key)
        if not isinstance(value, str) or value not in files or Path(value).name != value:
            raise ValueError('Artifact reference must name a sealed file: ' + key)
    bit = path.parent / cfg['bitfile']
    if cfg.get('ge_pl') is not None:
        from tcb705.ge_pl_contract import validate_hwh as validate_ge_pl
        if cfg['ge_pl'] != validate_ge_pl(bit.with_suffix('.hwh')) or 'ge_pl.dtbo' not in files:
            raise ValueError('GE_PL manifest differs from hardware or lacks sealed DTBO')
    dtbo = path.parent / cfg['dtbo'] if display == 'kernel-drm' else None
    required = {bit.name, bit.with_suffix('.hwh').name,
                bit.with_suffix('.registers.json').name}
    if dtbo is not None:
        required.add(dtbo.name)
        if dtbo.suffix != '.dtbo':
            raise ValueError('Kernel display requires a dtbo artifact')
    if bit.suffix != '.bit' or not required.issubset(files):
        raise ValueError('Manifest requires sealed bit, hwh and registers')
    if display == 'pynq-mmio':
        from md0700r_contract import expected_contract, validate_hwh
        if (cfg.get('dtbo') is not None or cfg.get('kernel_release') is not None
                or cfg.get('touch_backend') != 'gt911-pl-gpio'
                or cfg.get('display_contract') != expected_contract()):
            raise ValueError('Userspace display requires the explicit PL register contract and no DTBO')
        validate_hwh(bit.with_suffix('.hwh'))
    elif kernel_release is not None and cfg.get('kernel_release') != kernel_release:
        raise ValueError('Platform kernel release does not match running kernel')
    abi, ip = accelerator_identity(cfg)
    if abi in (TCB_ABI,TCB_FP32_ABI):
        from tcb705.accel_contract import validate_overlay_files,clock_hz
        if cfg.get('accelerator_clock_hz')!=clock_hz(bit.with_suffix('.hwh')):
            raise ValueError('Seven-axis manifest clock differs from HWH')
    elif abi == PLANNER_ABI:
        from planner_accel_contract import validate_overlay_files
    else:
        from ik_target_contract import validate_overlay_files
    registers, hashes = validate_overlay_files(bit, ip)
    if abi in (TCB_ABI,TCB_FP32_ABI) and registers.get('abi')!=abi:
        raise ValueError('Seven-axis manifest identity differs from register map')
    base, size = target_address(bit, ip)
    if cfg.get('lineart') is not None:
        from lineart_contract import validate_manifest_section
        validate_manifest_section(cfg,path.parent,bit)
    if cfg.get('vision') is not None:
        from brush_vision.hardware import validate_manifest_section as validate_vision
        validate_vision(cfg,path.parent,bit)
    if cfg.get('audio') is not None:
        from audio_player.hardware import validate_manifest_section as validate_audio
        validate_audio(cfg,path.parent,bit)
    return cfg, bit, dtbo, registers, hashes, base, size


def validate_attached(bitfile, ip_name, hashes, manifest, ready=READY,
                      boot_id_path=BOOT_ID, kernel_release=None):
    if not manifest:
        raise ValueError('attach requires --platform-manifest; automatic download is disabled')
    cfg, bit, _, _, sealed, base, size = validate_manifest(manifest, kernel_release)
    abi, ip = accelerator_identity(cfg)
    if bit != Path(bitfile).resolve() or ip != ip_name or sealed != hashes:
        raise ValueError('Application overlay differs from loaded platform')
    receipt = Path(ready)
    info = receipt.stat()
    if hasattr(os, 'geteuid') and (info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise ValueError('Platform receipt must be root-owned and not publicly writable')
    loaded = json.loads(receipt.read_text(encoding='utf-8'))
    expected = dict(schema='so101-platform-ready-v1', boot_id=Path(boot_id_path).read_text().strip(),
                    build_id=cfg['build_id'], manifest_sha256=digest(manifest),
                    artifact_hashes=hashes, ip_name=ip_name, base=base, size=size,
                    self_test='PASS')
    if abi in (PLANNER_ABI,TCB_ABI,TCB_FP32_ABI):
        expected['accelerator_abi'] = abi
    if loaded != expected:
        raise ValueError('Platform not ready for this boot/release; start platform service in maintenance mode')
    return base, size
