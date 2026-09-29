"""Erzeugt aus einem JPG Varianten (ohne EXIF, nur Orientation, ohne GPS, neu kodiert, ...), um auf
dem Windows-Runner einzugrenzen, was Explorer-Vorschau oder den Windows-Decoder WIC stoert.

Aufruf:  python tests/jpg_variants.py <bild.jpg> <ausgabeordner>
"""
import io
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import nef2jpg  # noqa: E402

COMMON = {0x829A, 0x829D, 0x8822, 0x8827, 0x9000, 0x9003, 0x9004, 0x9201, 0x9202, 0x9204, 0x9205, 0x9207,
          0x9208, 0x9209, 0x920A, 0xA001, 0xA002, 0xA003, 0xA402, 0xA403, 0xA405, 0xA406, 0xA431, 0xA432,
          0xA433, 0xA434}


def split(jpg: bytes) -> tuple[list[bytes], bytes]:
    """Zerlegt in (APP1-Exif-Segmente, alle uebrigen Bytes nach dem SOI-Marker)."""
    i = 2
    exif_segments: list[bytes] = []
    rest = bytearray()
    while i + 4 <= len(jpg) and jpg[i] == 0xFF and jpg[i + 1] != 0xDA:
        ln = struct.unpack(">H", jpg[i + 2:i + 4])[0]
        seg = jpg[i:i + 2 + ln]
        if jpg[i + 1] == 0xE1 and seg[4:10] == b"Exif\0\0":
            exif_segments.append(seg)
        else:
            rest += seg
        i += 2 + ln
    rest += jpg[i:]
    return exif_segments, bytes(rest)


def reencode(jpg: bytes, exif: bytes | None, subsampling: int) -> bytes:
    im = Image.open(io.BytesIO(jpg))
    im.load()
    buf = io.BytesIO()
    kwargs = {"quality": 95, "subsampling": subsampling}
    if exif:
        kwargs["exif"] = exif
    im.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(exist_ok=True)
    jpg = src.read_bytes()
    exif_segments, rest = split(jpg)
    bare = b"\xFF\xD8" + rest
    tiff = exif_segments[0][10:] if exif_segments else b""
    exif_payload = exif_segments[0][4:] if exif_segments else b""
    endian = "<" if tiff[:2] == b"II" else ">"
    minimal = b"Exif\0\0" + nef2jpg.serialize_tiff(endian, [(0x0112, 3, 1, struct.pack(endian + "H", 1))], [], [])
    jfif = b"\xFF\xE0" + struct.pack(">H", 16) + b"JFIF\0\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    skip = nef2jpg.SKIP_EXIF_TAGS
    variants = {
        "00_original": jpg,
        "01_ohne_exif": bare,
        "02_nur_orientation": nef2jpg.with_exif(bare, minimal),
        "03_jfif_vor_exif": b"\xFF\xD8" + jfif + jpg[2:],
        "04_exif_ohne_gps": nef2jpg.with_exif(bare, nef2jpg.build_exif(tiff, gps=False)),
        "05_exif_ohne_usercomment": nef2jpg.with_exif(bare, nef2jpg.build_exif(tiff, skip=skip | {0x9286})),
        "06_exif_nur_uebliche_tags": nef2jpg.with_exif(bare, nef2jpg.build_exif(tiff, keep=COMMON, gps=False)),
        "07_exif_ohne_compositeimage": nef2jpg.with_exif(bare, nef2jpg.build_exif(tiff, skip=skip | {0xA460})),
        "08_neu_kodiert_444_mit_exif": reencode(jpg, exif_payload, 0),
        "09_neu_kodiert_444_ohne_exif": reencode(jpg, None, 0),
        "10_neu_kodiert_420_mit_exif": reencode(jpg, exif_payload, 2),
    }
    for name, blob in variants.items():
        (out / f"{name}.jpg").write_bytes(blob)
    print(f"{len(variants)} Varianten von {src.name} in {out}")


if __name__ == "__main__":
    main()
