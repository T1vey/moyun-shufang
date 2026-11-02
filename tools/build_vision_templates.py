"""Build data/vision/templates_v1.bin (+ .json) from the 3500-character glyph library."""
import argparse
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calligraphy import glyph_store            # noqa: E402
from brush_vision import templates             # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT / 'data/vision/templates_v3.bin')
    ap.add_argument('--centreline', action='store_true', help='v1 brush rendering of the centrelines (obsolete)')
    ap.add_argument('--limit', type=int, default=0, help='first N characters only (testing)')
    a = ap.parse_args()
    chars = glyph_store.manifest()['characters']
    if a.limit:
        chars = chars[:a.limit]
    started = time.perf_counter()
    build = (lambda ch, out, progress: templates.build(ch, glyph_store.glyph, out, progress)) if a.centreline \
        else templates.build_outlines
    meta = build(chars, a.output,
                           progress=lambda i, n: print(f'{i}/{n} {time.perf_counter() - started:.0f}s', flush=True))
    print('TEMPLATES', meta['count'], meta['sha256'], meta['calibration'])


if __name__ == '__main__':
    main()
