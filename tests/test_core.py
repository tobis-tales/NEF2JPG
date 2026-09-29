"""Kern-Test mit synthetischen NEF-Dateien, deren Struktur echten NEFs entspricht
(IFD0, SubIFDs mit grossem JPG, Exif-IFD, Nikon-MakerNote mit Vorschau).

Aufruf aus dem Repo-Stammverzeichnis:  python tests/test_core.py
"""
import shutil
import struct
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import rawpy  # noqa: E402
from PIL import Image  # noqa: E402

import nef2jpg  # noqa: E402
from make_fake_nef import build_nef  # noqa: E402

T = ROOT / "test_tmp_core"
CASES = {"quer_MM_o1.NEF": (">", 1), "hoch_MM_o6.NEF": (">", 6), "hoch_II_o8.nef": ("<", 8), "kopf_MM_o3.NEF": (">", 3)}


def run_cli(originals, mode_args, label):
    print(f"\n=== Lauf: {label} ===")
    r = subprocess.run([sys.executable, str(ROOT / "nef2jpg.py"), str(T), "--jobs", "2", "--overwrite", *mode_args],
                       capture_output=True, text=True, cwd=ROOT)
    print(r.stdout.strip())
    if r.stderr.strip():
        print("stderr:", r.stderr.strip())
    assert r.returncode == 2, f"Exit-Code {r.returncode}, erwartet 2 wegen zwei kaputten Dateien"
    ok = True
    for name, (endian, orientation) in CASES.items():
        out = T / "JPG" / (Path(name).stem + ".jpg")
        im = Image.open(out)
        im.load()
        ex = im.getexif()
        ifd = ex.get_ifd(0x8769)
        expect = (300, 400) if orientation in (6, 8) else (400, 300)
        lossless = None
        if orientation == 1:
            b = out.read_bytes()
            seglen = struct.unpack(">H", b[4:6])[0]
            lossless = b[4 + seglen:] == originals[name][2:]
        good = (im.size == expect and ex.get(0x0110) == "NIKON Z 9" and ex.get(0x0112) == 1
                and ifd.get(0x9003) == "2026:09:29 14:00:00" and float(ifd.get(0x829A)) == 1 / 250
                and 0x927C not in ifd and lossless in (None, True))
        ok &= good
        print(f"  {name}: {im.size} Model={ex.get(0x0110)!r} Orient={ex.get(0x0112)} Datum={ifd.get(0x9003)} "
              f"MakerNote={0x927C in ifd} verlustfrei={lossless} -> {'OK' if good else 'FALSCH'}")
    assert ok, "Ausgabe fehlerhaft"


def main():
    shutil.rmtree(T, ignore_errors=True)
    T.mkdir()
    originals = {}
    for name, (endian, orientation) in CASES.items():
        data, big = build_nef(endian, orientation)
        (T / name).write_bytes(data)
        originals[name] = big
    (T / "kaputt.NEF").write_bytes(b"MM\0\x2a" + b"\xff" * 5000)
    (T / "zufall.NEF").write_bytes(bytes(range(256)) * 20)

    try:
        with rawpy.imread(open(T / "quer_MM_o1.NEF", "rb")) as raw:
            raw.postprocess()
        print("LibRaw hat die synthetische Datei angenommen (unerwartet, Test laeuft trotzdem)")
    except rawpy.LibRawError as exc:
        print("LibRaw lehnt die synthetische NEF ab mit:", nef2jpg.error_text(exc))

    run_cli(originals, [], "Standard (LibRaw lehnt ab -> automatisch eingebettetes JPG)")
    run_cli(originals, ["--embedded"], "--embedded")

    # Entwicklungspfad mit simuliertem LibRaw: EXIF muss auch dort ankommen
    class FakeRaw:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def postprocess(self, **kw):
            assert kw == {"use_camera_wb": True, "output_bps": 8}, kw
            return np.zeros((30, 50, 3), dtype=np.uint8)

    real_rawpy = nef2jpg.rawpy
    nef2jpg.rawpy = types.SimpleNamespace(imread=lambda f: FakeRaw(), LibRawError=rawpy.LibRawError)
    try:
        out = T / "entwickelt.jpg"
        res = nef2jpg.convert_one((T / "quer_MM_o1.NEF", out, 92, False))
    finally:
        nef2jpg.rawpy = real_rawpy
    im = Image.open(out)
    ex = im.getexif()
    good = res[1] == "entwickelt" and im.size == (50, 30) and ex.get(0x0110) == "NIKON Z 9"
    print("\nEntwicklungspfad:", res, im.size, "Model =", ex.get(0x0110), "->", "OK" if good else "FALSCH")
    assert good
    print("\nKERN-TEST OK")


if __name__ == "__main__":
    main()
