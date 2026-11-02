"""Package the actual created Vivado project and its relative HLS IP repository."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-root', type=Path, default=Path('C:/fpga_build/so101_target_2024_1003'))
    p.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'dist/so101_vivado_2024.zip')
    a = p.parse_args(); root = a.build_root.resolve()
    required = ['vivado/so101_target_ik.xpr', 'hls_final/hls/impl/ip/component.xml',
                'src/ps7_board.tcl', 'export/drawing_target.registers.json']
    if any(not (root / name).is_file() for name in required):
        raise ValueError('Missing created target Vivado project or packaged IP')
    files = set(root / name for name in required)
    for directory in ('vivado/so101_target_ik.srcs', 'vivado/so101_target_ik.gen',
                      'vivado/so101_target_ik.hw', 'hls_final/hls/impl/ip', 'src'):
        files.update(p for p in (root / directory).rglob('*') if p.is_file()
                     and '.Xil' not in p.parts and p.suffix not in ('.log', '.jou', '.str'))
    files.add(root / 'vivado/recreate_bd.tcl')
    files = sorted(files)
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'so101_target_2024/'
    with zipfile.ZipFile(a.output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, prefix + path.relative_to(root).as_posix())
        z.writestr(prefix + 'FPGA_FILES_SHA256.json', json.dumps(manifest, indent=2) + '\n')
        z.writestr(prefix + 'vivado/so101_target_ik.ip_user_files/', b'')
        z.writestr(prefix + 'OPEN_PROJECT.txt',
                   'Extract to an ASCII path. Open vivado/so101_target_ik.xpr in Vivado 2024.2.\n'
                   'Keep hls_final/hls/impl/ip next to vivado as packaged.\n'
                   'Run synthesis, implementation and bitstream yourself. No board programming performed.\n'
                   'After successful bitstream generation, source ../src/export_after_bitstream.tcl.\n')
    digest = hashlib.sha256(a.output.read_bytes()).hexdigest()
    a.output.with_suffix(a.output.suffix + '.sha256').write_text(digest + '  ' + a.output.name + '\n', encoding='utf-8')
    print(json.dumps(dict(archive=str(a.output),files=len(files),sha256=digest),indent=2))


if __name__ == '__main__':
    main()
