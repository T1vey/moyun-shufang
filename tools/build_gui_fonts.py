"""Subset the 书画 GUI fonts to the characters the screens can show.

Run after changing GUI text:  python tools/build_gui_fonts.py
Text that is not in the subset (for example characters typed on the phone)
falls back to the board's system font, so the subset only has to cover the
interface itself.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT.parent / "fonts_ofl"
OUT = ROOT / "user_gui" / "static" / "fonts"
SOURCES = ["user_gui", "tcb705", "calligraphy", "handwriting", "brush_vision", "data/calligraphy/couplets", "data/encyclopedia", "data/calligraphy/poems"]
SUFFIXES = {".py", ".js", ".html", ".css", ".json"}
TARGETS = {"brush.ttf": "MaShanZheng-Regular.ttf", "wenkai.ttf": "LXGWWenKai-Regular.ttf"}


def characters():
    chars = set(chr(i) for i in range(32, 127)) | set("，。、：；！？「」《》（）·—…０１２３４５６７８９×÷−％")
    for name in SOURCES:
        for path in (ROOT / name).rglob("*"):
            if path.suffix in SUFFIXES and "__pycache__" not in path.parts and path.is_file():
                text = path.read_text("utf-8", errors="ignore")
                chars.update(c for c in text if ord(c) > 0x2000)
    for manifest in (ROOT / "data" / "calligraphy" / "masterpieces").glob("*/manifest.json"):
        chars.update(c for c in manifest.read_text("utf-8") if ord(c) > 0x2000)
    return "".join(sorted(chars))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    text = OUT / "chars.txt"
    text.write_text(characters(), "utf-8")
    for out, source in TARGETS.items():
        subprocess.run([sys.executable, "-m", "fontTools.subset", str(FONTS / source), f"--text-file={text}",
                        f"--output-file={OUT / out}", "--layout-features=*", "--no-hinting"], check=True)
    for licence in ("OFL_LXGWWenKai.txt",):
        shutil.copy(FONTS / licence, OUT / licence)
    (OUT / "OFL_MaShanZheng.txt").write_text(
        "Ma Shan Zheng — Copyright 2018 The Ma Shan Zheng Project Authors. "
        "Licensed under the SIL Open Font License 1.1 (https://openfontlicense.org).\n", "utf-8")
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:24s} {path.stat().st_size:>9d}")


if __name__ == "__main__":
    main()
