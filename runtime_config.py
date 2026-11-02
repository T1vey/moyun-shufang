"""Explicit board launch profiles; a missing FPGA never selects PS silently."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def board_arguments(profile, root=ROOT):
    root = Path(root).resolve()
    profile = Path(profile)
    if not profile.is_absolute():
        profile = root / profile
    cfg = json.loads(profile.read_text(encoding='utf-8'))
    allowed = {'schema', 'ik_engine', 'pl_mode', 'overlay', 'ip_name', 'port', 'note',
               'pl_load_policy','platform_manifest','platform_ready','cloud_config','secrets_file'}
    if not isinstance(cfg, dict) or cfg.get('schema') != 'so101-runtime-v1' or set(cfg) - allowed:
        raise ValueError('Invalid runtime profile')
    if cfg.get('ik_engine') != 'wls' or cfg.get('pl_mode') not in ('ps', 'target', 'planner'):
        raise ValueError('Delivery profiles support wls + ps/target/planner')
    port = cfg.get('port', 8765)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Invalid board port')
    args = ['--ik-engine', 'wls', '--port', str(port)]
    policy=cfg.get('pl_load_policy','download')
    if policy not in ('download','attach') or (policy=='attach' and cfg['pl_mode'] not in ('target','planner')):
        raise ValueError('Invalid PL load policy')
    if policy=='attach' and not cfg.get('platform_manifest'):
        raise ValueError('attach requires platform_manifest')
    args += ['--pl-load-policy',policy]
    for key in ('platform_manifest','platform_ready','cloud_config','secrets_file'):
        if cfg.get(key):
            value=Path(cfg[key]);value=value if value.is_absolute() else root/value
            args += ['--'+key.replace('_','-'),str(value.resolve())]
    if cfg['pl_mode'] in ('target','planner'):
        if cfg['pl_mode'] == 'planner':
            from planner_accel_contract import validate_overlay_files
            default_ip = 'planner_accel_v2_0'
        else:
            from ik_target_contract import validate_overlay_files
            default_ip = 'z20_ik_target_0'
        overlay = Path(cfg['overlay'])
        if not overlay.is_absolute():
            overlay = root / overlay
        ip = cfg.get('ip_name', default_ip)
        validate_overlay_files(overlay, ip)
        args += ['--pl-mode', cfg['pl_mode'], '--overlay', str(overlay.resolve()), '--ip-name', ip]
    elif cfg.get('overlay') or cfg.get('ip_name'):
        raise ValueError('PS profile must not specify an overlay')
    return args
