"""Identity gates shared by the userspace display and touch services."""
from pathlib import Path
import platform

from platform_runtime import (READY, accelerator_identity, digest, display_backend,
                              validate_attached, validate_manifest)
from md0700r_contract import expected_contract, validate_hwh

LEGACY_BIT_SHA256 = 'dfc12ba5cc20d1c113fa5a6f80f00d5cf009c324888c72654b6781d7323f179e'


def resolve_display(runtime, manifest=None, ready=READY):
    """Validate every artifact before either service opens hardware registers."""
    if manifest is not None:
        cfg, bit, _, _, hashes, _, _ = validate_manifest(manifest, platform.release())
        if display_backend(cfg) != 'pynq-mmio':
            raise ValueError('Userspace display requires a pynq-mmio platform')
        abi, ip = accelerator_identity(cfg)
        validate_attached(bit, ip, hashes, manifest, ready, kernel_release=platform.release())
        return dict(bitfile=str(bit), hashes=hashes, bit_sha256=hashes[bit.name], abi=abi,
                    manifest_sha256=digest(manifest), build_id=cfg['build_id'],
                    contract=cfg['display_contract'])
    # Retain the previously verified target-only service while migrating boards.
    from ik_target_contract import validate_overlay_files
    bit = Path(runtime) / 'overlay/drawing_target.bit'
    _, hashes = validate_overlay_files(bit)
    if hashes[bit.name] != LEGACY_BIT_SHA256:
        raise ValueError('A different display bitstream requires a platform manifest')
    validate_hwh(bit.with_suffix('.hwh'))
    return dict(bitfile=str(bit), hashes=hashes, bit_sha256=LEGACY_BIT_SHA256,
                abi='so101-ik-target-v1', manifest_sha256=None, build_id=None,
                contract=expected_contract())


def validate_health(state, identity):
    metrics = state.get('ik_metrics', {})
    if (metrics.get('faulted') is not False or metrics.get('abi') != identity['abi']
            or metrics.get('artifact_hashes') != identity['hashes']):
        raise ValueError('Workbench accelerator identity does not match display platform')
    if identity['manifest_sha256'] is not None and metrics.get('pl_load_policy') != 'attach':
        raise ValueError('Sealed display platform requires an attached backend')


def display_ready(status, identity):
    return (status.get('status') == 'RUNNING'
            and status.get('hardware_frames_verified') is True
            and status.get('bit_sha256') == identity['bit_sha256']
            and (identity['manifest_sha256'] is None
                 or status.get('manifest_sha256') == identity['manifest_sha256']))
