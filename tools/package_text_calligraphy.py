"""Create an auditable update archive; does not connect to a board or deploy."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES='''
calligraphy/__init__.py
calligraphy/presets.py
calligraphy/library.py
calligraphy/curves.py
calligraphy/execution.py
calligraphy/glyph_store.py
calligraphy/text_layout.py
calligraphy/composer.py
tcb705/workbench.py
tcb705/planner.py
tcb705/artifact.py
user_gui/workflow.py
user_gui/text_workflow.py
user_gui/display_server.py
user_gui/static/mobile.html
user_gui/static/text-writing.css
user_gui/static/text-writing.js
user_gui/static/desktop.html
user_gui/static/desktop.js
tests/__init__.py
tests/test_text_calligraphy.py
tests/test_glyph_library_integrity.py
tests/test_calligraphy.py
tests/test_calligraphy_speed.py
tests/test_calligraphy_home.py
tests/test_calligraphy_stop_workflow.py
tests/test_user_gui_workflow.py
tests/test_user_gui_gallery.py
tests/test_tcb705_web.py
tests/test_tcb705_sdk.py
tools/build_glyph_library.py
tools/audit_glyph_library.py
tools/verify_text_library.py
tools/smoke_text_http.py
tools/package_text_calligraphy.py
docs/3500字库扩展_使用与验证_20261022.md
'''.split()


def main():
    paths=FILES+[p.relative_to(ROOT).as_posix() for p in (ROOT/'data/calligraphy').rglob('*') if p.is_file()]
    paths += ['reports/text_calligraphy_3500_20261022/'+name for name in (
        'regression.txt','regression-delta.txt','library-audit.json',
        'native-verification.json','native-glyph-verification.json')]
    if any('machine.json' in p or p.endswith(('.bit','.hwh')) or 'secrets' in p.lower() for p in paths):
        raise ValueError('Machine config, FPGA files and secrets must not be packaged')
    files=[dict(path=p,bytes=(ROOT/p).stat().st_size,sha256=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()) for p in paths]
    library=json.loads((ROOT/'data/calligraphy/manifest.json').read_text(encoding='utf-8'))
    manifest=dict(release='text-calligraphy-3500-20261022',target='existing ZYNQArm installation',
                  library_version=library['version'],count=library['count'],
                  installed_on_board=False,files=files)
    out=ROOT/'dist/text_calligraphy_3500_20261022.zip';out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(ROOT/p,p)
        z.writestr('TEXT_UPDATE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        for f in files:assert hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256']
    print(json.dumps(dict(file=str(out),entries=len(files),bytes=out.stat().st_size),ensure_ascii=False))


if __name__=='__main__':main()
