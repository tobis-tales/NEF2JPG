"""Prueft im CI-Build, ob der Konverter gueltige, ausreichend grosse JPGs mit EXIF-Daten erzeugt hat."""
import argparse
import sys
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--min", type=int, default=1000, help="kleinste zulaessige Kantenlaenge in Pixeln")
parser.add_argument("files", nargs="+")
opts = parser.parse_args()

failed = False
for arg in opts.files:
    path = Path(arg)
    if not path.is_file():
        print(f"{path}: FEHLT")
        failed = True
        continue
    Image.open(path).verify()  # Dateistruktur pruefen
    im = Image.open(path)
    exif = im.getexif()
    model = exif.get(0x0110)
    date = exif.get_ifd(0x8769).get(0x9003)
    ok = im.format == "JPEG" and min(im.size) >= opts.min and bool(model)
    print(f"{path}: {im.format} {im.size[0]}x{im.size[1]} Kamera={model!r} Aufnahme={date!r} "
          f"{'ok' if ok else 'ZU KLEIN, KEIN JPEG ODER OHNE EXIF'}")
    failed |= not ok
sys.exit(1 if failed else 0)
