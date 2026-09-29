"""Erzeugt aus einer NEF viele JPG-Varianten mit unterschiedlichem EXIF-Block, um mit
tests/check_windows.ps1 einzugrenzen, welchen Eintrag der Windows-Decoder (WIC) ablehnt.

Aufruf:  python tests/exif_variants.py <datei.NEF> <ausgabeordner>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import ExifTags, Image  # noqa: E402

import nef2jpg  # noqa: E402

COMMON = {0x829A, 0x829D, 0x8822, 0x8827, 0x9000, 0x9003, 0x9004, 0x9201, 0x9202, 0x9204, 0x9205, 0x9207,
          0x9208, 0x9209, 0x920A, 0xA001, 0xA002, 0xA003, 0xA402, 0xA403, 0xA405, 0xA406, 0xA431, 0xA432,
          0xA433, 0xA434}


def main() -> None:
    nef, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(exist_ok=True)
    data = nef.read_bytes()
    candidates, _ = nef2jpg.scan_nef(data)
    start, length = max(candidates, key=lambda c: c[1])
    jpg = data[start:start + length]
    src = Image.Exif()
    src.load(data)
    exif_tags = sorted(k for k in src.get_ifd(0x8769) if k not in nef2jpg.SKIP_EXIF_TAGS)
    print("Exif-IFD-Tags in der NEF:", ", ".join(f"{t:#06x}" for t in exif_tags))

    variants = {
        "00_ohne_exif": None,
        "01_baseline": dict(),
        "02_ohne_gps": dict(gps=False),
        "04_nur_orientation": dict(keep=set(), gps=False),
        "05_nur_uebliche_tags": dict(keep=COMMON, gps=False),
        "06_nur_uebliche_tags_mit_gps": dict(keep=COMMON, gps=True),
    }
    for tag in exif_tags:
        name = ExifTags.TAGS.get(tag, "unbekannt")
        variants[f"ohne_{tag:04x}_{name}"] = dict(skip=nef2jpg.SKIP_EXIF_TAGS | {tag})
    for name, kwargs in variants.items():
        blob = jpg if kwargs is None else nef2jpg.with_exif(jpg, nef2jpg.build_exif(data, **kwargs))
        (out_dir / f"{name}.jpg").write_bytes(blob)
    print(f"{len(variants)} Varianten in {out_dir}")


if __name__ == "__main__":
    main()
