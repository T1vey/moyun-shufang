"""Build a clean runtime ZIP with hashes; include only explicitly selected files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPTS = ('sugar_theme.py', 'sugar_dialogs.py', 'bluetooth_receiver.py', 'touch_bluetooth.py', 'touch_network.py', 'touch_ui.py', 'load_platform.py', 'run_touch_gui.py', 'install_touch_desktop.py', 'doctor.py', 'run_board.py', 'verify_package.py', 'build_delivery.py',
           'check_target_overlay.py', 'benchmark_target_ik.py', 'generate_target_vectors.py',
           'benchmark_planning_pipeline.py', 'benchmark_planning_speed.py', 'arm_studio.py', 'drawing_preview_ui.py',
           'export_planner_register_map.py', 'install_planner_runtime.py', 'check_planner_overlay.py',
           'run_user_gui.py', 'user_gui_kiosk.py', 'kinematic_calibration.py',
           'kinematic_calibration_ui.py', 'identify_servo_dynamics.py', 'migrate_sugar_config.py')
DEPLOY = ('install_z20.sh', 'enable_pl.sh', 'deploy_z20.ps1', 'deploy_pynq.ps1',
          'deploy_pynq.sh', 'tunnel.ps1', 'install_planner.sh')


def selected_files(root):
    root = Path(root)
    for path in sorted(root.glob('*.py')):
        yield path.relative_to(root)
    for name in ('README.md', 'requirements-pynq.txt', 'requirements-workbench.txt',
                 'requirements-pc.txt', 'run_studio.bat', 'launch_pc.ps1', 'deploy_all.ps1'):
        yield Path(name)
    for directory in ('deploy/bluetooth', 'deploy/pynq-md0700r', 'deploy/standalone', 'hw/md0700r', 'web', 'vendor/armvision', 'vendor/e1pco', 'planner_source/r1a',
                      'planner_source/r1b', 'planner_source/config', 'config', 'examples',
                      'dependencies/pynq_wheels'):
        for path in sorted((root / directory).rglob('*')):
            if (path.is_file() and '__pycache__' not in path.parts and
                path.suffix not in ('.pyc', '.pyo') and not path.name.endswith('.local.json') and
                (directory != 'config' or path.name.endswith('.example.json') or
                 path.name in ('edition.json', 'runtime.ps.json', 'runtime.target.json'))):
                yield path.relative_to(root)
    for name in SCRIPTS:
        yield Path('scripts') / name
    for name in ('display_server.py', 'workflow.py', 'timeline.py', 'netinfo.py', 'README.md'):
        yield Path('user_gui') / name
    for path in sorted((root / 'user_gui/static').rglob('*')):
        if path.is_file():
            yield path.relative_to(root)
    # Ship a reproducible target build path; never embed a host DLL or stale .so.
    for name in ('__init__.py','geometry.py','geometry.cpp','build.py','README.md'):
        yield Path('native') / name
    for name in DEPLOY:
        yield Path('deploy') / name
    for name in ('MD0700R_STANDALONE.md', 'DELIVERY.md', 'TARGET_IK_VIVADO_2024.md', 'DEPLOYMENT.md',
                 'DRAWING_QUALITY_FIX.md', 'CLOUD_IMAGE_LIBRARY.md', 'DRAWING_PREDICTION.md',
                 'PLANNING_SPEED.md', 'PLANNER_ACCEL_IMPLEMENTATION.md', 'PLANNER_RUNTIME_DEPLOYMENT.md', 'MOTION_SMOOTHNESS.md', 'FEEDBACK_DRAWING.md', 'DRAWING_SIZE.md', 'DRAWING_ALIGNMENT.md', 'PEN_TRANSITIONS.md', 'CONTACT_PLANE.md',
                 'NEW_SUGAR_SCHEME.md', 'kinematic_calibration.md'):
        yield Path('docs') / name


def source_manifest(root=ROOT):
    """Freeze the reviewed source delivery, excluding build outputs and secrets."""
    root = Path(root).resolve()
    files = set(selected_files(root))
    for directory in ('hls_source', 'hw/target_ik', 'tests'):
        files.update(p.relative_to(root) for p in (root / directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.update(Path(p) for p in ('run_tests.ps1', 'scripts/prepare_target_2024.ps1',
                                 'scripts/export_target_register_map.py', 'scripts/package_vivado.py',
                                 'scripts/arm_studio.py', 'run_studio.bat'))
    doc = dict(schema='so101-delivery-v1', scope='REVIEWED_SOURCE_NOT_BOARD_ACCEPTANCE',
               files={rel.as_posix(): hashlib.sha256((root / rel).read_bytes()).hexdigest()
                      for rel in sorted(files)})
    (root / 'PACKAGE_MANIFEST.json').write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    return len(files)


def build(output, root=ROOT, overlay_dir=None, require_hardware=False, standalone=False,
          mode='target', platform_dir=None):
    from ik_target_contract import ABI, validate_overlay_files
    from scripts.verify_package import verify
    root, output = Path(root).resolve(), Path(output).resolve()
    if mode not in ('target', 'planner'):
        raise ValueError('mode must be target or planner')
    if mode == 'planner' and (platform_dir is None or overlay_dir is not None):
        raise ValueError('Planner delivery requires --platform-dir, never a target overlay directory')
    if mode == 'target' and platform_dir is not None:
        raise ValueError('--platform-dir requires --mode planner')
    if require_hardware and overlay_dir is None and platform_dir is None:
        raise ValueError('Final hardware delivery requires --overlay-dir with compiled artifacts')
    files = sorted(set(selected_files(root)))
    if mode == 'planner':
        # The legacy installers explicitly select target-v1 and may reprogram
        # the display platform. Do not expose those entry points in this ZIP.
        legacy_installers = {Path('deploy')/name for name in DEPLOY if name != 'install_planner.sh'}
        legacy_installers.add(Path('deploy_all.ps1'))
        files = [rel for rel in files if rel not in legacy_installers]
    with tempfile.TemporaryDirectory(prefix='so101_delivery_') as tmp:
        stage = Path(tmp) / ('so101_planner_runtime' if mode == 'planner' else 'so101_target_runtime')
        stage.mkdir()
        for rel in files:
            src = root / rel
            if not src.is_file():
                raise ValueError('Missing release source: ' + str(rel))
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == '.sh':
                dest.write_bytes(src.read_bytes().replace(b'\r\n', b'\n'))
            else:
                shutil.copy2(src, dest)
        overlay = stage / 'overlay'
        overlay.mkdir()
        state = 'SOFTWARE_READY_AWAITING_USER_BITSTREAM'
        platform_cfg = None
        if mode == 'planner':
            from platform_runtime import PLANNER_ABI, validate_manifest, accelerator_identity
            platform_source = Path(platform_dir).resolve()
            platform_cfg, bit, _, _, _, _, _ = validate_manifest(platform_source / 'platform.json')
            if accelerator_identity(platform_cfg)[0] != PLANNER_ABI:
                raise ValueError('Planner runtime requires planner accelerator ABI')
            if platform_cfg.get('display_backend') != 'pynq-mmio' or platform_cfg.get('dtbo') is not None:
                raise ValueError('Planner runtime installer requires the PYNQ MMIO display platform without DTBO')
            ABI = PLANNER_ABI
            destination = overlay / 'planner_platform'
            destination.mkdir()
            names = set(platform_cfg['files']) | {'platform.json'}
            seal = bit.with_suffix('.artifacts.json').name
            names.add(seal)
            for name in sorted(names):
                shutil.copy2(platform_source / name, destination / name)
            # Never label copied host reports as acceptance of this installation.
            state = 'PLANNER_RUNTIME_AND_PLATFORM_READY_BOARD_ACCEPTANCE_PENDING'
        elif overlay_dir is not None:
            bitfile = Path(overlay_dir) / 'drawing_target.bit'
            _, hashes = validate_overlay_files(bitfile)
            for name in hashes:
                shutil.copy2(bitfile.parent / name, overlay / name)
            (overlay / 'drawing_target.artifacts.json').write_text(
                json.dumps({'abi': ABI, 'files': hashes}, indent=2) + '\n', encoding='utf-8')
            state = 'SOFTWARE_AND_COMPILED_ARTIFACTS_READY_BOARD_ACCEPTANCE_PENDING'
        else:
            mapping = root / 'hw/target_ik/drawing_target.registers.json'
            if not mapping.is_file():
                mapping = root / 'overlay/drawing_target.registers.json'
            shutil.copy2(mapping, overlay)
        if standalone and mode == 'target':
            state = 'MD0700R_SOURCE_READY_KERNEL_PLATFORM_AND_BOARD_ACCEPTANCE_PENDING'
        release = dict(schema='so101-release-status-v1', status=state, toolchain='2024.2',
                       abi=ABI, board_acceptance='NOT_RUN', physical_calibration='USER_MACHINE_REQUIRED')
        if platform_cfg is not None:
            release.update(installer='deploy/install_planner.sh',
                           platform_manifest='overlay/planner_platform/platform.json',
                           platform_build_id=platform_cfg['build_id'], display_backend='pynq-mmio',
                           native_geometry='BUILD_ON_ARM_DURING_INSTALL', boot_files_changed=False)
        (stage / 'RELEASE_STATUS.json').write_text(json.dumps(release, indent=2) + '\n', encoding='utf-8')
        manifest = dict(schema='so101-delivery-v1', files={
            p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.rglob('*')) if p.is_file()})
        (stage / 'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        verify(stage)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent).as_posix())
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n', encoding='utf-8')
        return dict(archive=str(output), sha256=digest, files=len(manifest['files']), **release)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT / 'dist/so101_target_runtime.zip')
    p.add_argument('--overlay-dir', type=Path)
    p.add_argument('--require-hardware', action='store_true')
    p.add_argument('--standalone', action='store_true', help='Mark kernel/platform acceptance as pending')
    p.add_argument('--mode', choices=('target', 'planner'), default='target')
    p.add_argument('--platform-dir', type=Path, help='Sealed complete planner platform directory')
    p.add_argument('--source-manifest', action='store_true', help='Also freeze the reviewed source files')
    a = p.parse_args()
    if a.source_manifest:
        print('SOURCE_MANIFEST_WRITTEN files=' + str(source_manifest()))
    print(json.dumps(build(a.output, overlay_dir=a.overlay_dir, require_hardware=a.require_hardware, standalone=a.standalone,
                           mode=a.mode, platform_dir=a.platform_dir),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
