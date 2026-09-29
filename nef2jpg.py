#!/usr/bin/env python3
r"""
nef2jpg.py - wandelt alle .NEF-Dateien eines Ordners in JPGs um.

Die JPGs landen im Unterordner "JPG" des gewaehlten Ordners und behalten den
Dateinamen (DSC_0001.NEF -> JPG\DSC_0001.jpg). Die Aufnahmedaten (EXIF) werden
in die JPGs uebernommen, nur die umfangreiche Nikon-MakerNote nicht.

Aufruf:
    python nef2jpg.py                    Ordner per Dialog auswaehlen
    python nef2jpg.py "D:\Fotos\Urlaub"  Ordner direkt angeben

Optionen:
    --embedded    Nimmt das in der NEF eingebettete Kamera-JPG (sehr schnell,
                  sieht aus wie das JPG aus der Kamera). Ohne diese Option wird
                  die Rohdatei komplett entwickelt (langsamer, neutraler Look).
    --quality 92  JPG-Qualitaet 1-100 (nur bei kompletter Entwicklung)
    --jobs 4      Anzahl paralleler Prozesse (Standard: alle Kerne, max. 8)
    --overwrite   Vorhandene JPGs ueberschreiben (Standard: ueberspringen)

NEF-Dateien im Format "High Efficiency" (HE / HE*, z.B. von Z8, Z9, Z6III, Zf)
kann die freie Rohdaten-Bibliothek LibRaw nicht entwickeln. Fuer solche
Dateien wird automatisch das eingebettete Kamera-JPG uebernommen, das bei
diesen Kameras in voller Aufloesung vorliegt.

Benoetigt einmalig:  pip install rawpy pillow
"""
from __future__ import annotations

import argparse
import io
import multiprocessing
import os
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

try:
    import rawpy
except ImportError:  # ohne rawpy funktioniert nur der eingebettete Modus
    rawpy = None

__version__ = "1.0.0"

# EXIF-Orientation -> Pillow-Transposition (Pillow dreht gegen den Uhrzeigersinn)
ORIENTATION_TO_TRANSPOSE = {
    3: Image.Transpose.ROTATE_180,
    6: Image.Transpose.ROTATE_270,  # 90 Grad im Uhrzeigersinn
    8: Image.Transpose.ROTATE_90,   # 90 Grad gegen den Uhrzeigersinn
}
# IFD0-Tags, die ins JPG uebernommen werden: Make, Model, Software, DateTime, Artist, Copyright
COPY_IFD0_TAGS = (0x010F, 0x0110, 0x0131, 0x0132, 0x013B, 0x8298)
# Exif-IFD-Tags, die nicht uebernommen werden: MakerNote (zu gross fuer JPG), Interop-Zeiger
SKIP_EXIF_TAGS = {0x927C, 0xA005}


# ---------------------------------------------------------------------------
# NEF-Struktur (TIFF-IFDs) direkt lesen, unabhaengig von LibRaw
# ---------------------------------------------------------------------------
def scan_nef(data: bytes) -> tuple[list[tuple[int, int]], int]:
    """Sucht alle in der NEF referenzierten JPEG-Streams. Liefert [(offset, laenge), ...] und die Orientation."""
    endian = {b"MM": ">", b"II": "<"}.get(data[:2])
    if endian is None or len(data) < 8 or struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise ValueError("keine TIFF/NEF-Struktur")
    found: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    state = {"orientation": 1}

    def walk(base: int, ifd: int, endian: str, depth: int) -> None:
        pos = base + ifd
        if depth > 6 or ifd <= 0 or (base, ifd) in seen or pos + 2 > len(data):
            return
        seen.add((base, ifd))
        n = struct.unpack_from(endian + "H", data, pos)[0]
        if n == 0 or pos + 2 + 12 * n + 4 > len(data):
            return
        tags: dict[int, tuple[int, int, int]] = {}
        for i in range(n):
            entry = pos + 2 + 12 * i
            tag, typ, count = struct.unpack_from(endian + "HHI", data, entry)
            tags[tag] = (typ, count, entry + 8)

        def values(tag: int) -> list[int]:
            """SHORT/LONG/IFD-Werte eines Tags (bis 64 Stueck)."""
            if tag not in tags:
                return []
            typ, count, field = tags[tag]
            size = {3: 2, 4: 4, 13: 4}.get(typ)
            if size is None or count == 0 or count > 64:
                return []
            src = field if size * count <= 4 else base + struct.unpack_from(endian + "I", data, field)[0]
            if src + size * count > len(data):
                return []
            fmt = endian + ("H" if size == 2 else "I")
            return [struct.unpack_from(fmt, data, src + k * size)[0] for k in range(count)]

        if depth == 0 and base == 0:
            state["orientation"] = (values(0x0112) or [1])[0]
        offs, lens = values(0x0201), values(0x0202)           # JPEGInterchangeFormat (+Length)
        if offs and lens and lens[0] > 0:
            start = base + offs[0]
            if data[start:start + 2] == b"\xFF\xD8":
                found.append((start, min(lens[0], len(data) - start)))
        for sub in values(0x014A):                              # SubIFDs: hier liegt das grosse JPG
            walk(base, sub, endian, depth + 1)
        for tag in (0x8769, 0x0011):                            # Exif-IFD bzw. Nikon-PreviewIFD
            for off in values(tag)[:1]:
                walk(base, off, endian, depth + 1)
        if 0x927C in tags:                                      # MakerNote mit eigenem TIFF-Header
            typ, count, field = tags[0x927C]
            src = field if count <= 4 else base + struct.unpack_from(endian + "I", data, field)[0]
            if data[src:src + 6] == b"Nikon\x00":
                mn_base = src + 10
                mn_endian = {b"MM": ">", b"II": "<"}.get(data[mn_base:mn_base + 2])
                if mn_endian and mn_base + 8 <= len(data):
                    first = struct.unpack_from(mn_endian + "I", data, mn_base + 4)[0]
                    walk(mn_base, first, mn_endian, depth + 1)
        nxt = struct.unpack_from(endian + "I", data, pos + 2 + 12 * n)[0]
        walk(base, nxt, endian, depth + 1)

    walk(0, struct.unpack_from(endian + "I", data, 4)[0], endian, 0)
    return found, state["orientation"]


def build_exif(data: bytes) -> bytes:
    """EXIF-Block fuer das JPG aus den Metadaten der NEF, ohne MakerNote, Orientation = 1."""
    try:
        src = Image.Exif()
        src.load(data)
        exif = Image.Exif()
        for tag in COPY_IFD0_TAGS:
            if tag in src:
                exif[tag] = src[tag]
        exif_ifd = {k: v for k, v in src.get_ifd(0x8769).items() if k not in SKIP_EXIF_TAGS}
        if exif_ifd:
            exif[0x8769] = exif_ifd
        gps = src.get_ifd(0x8825)
        if gps:
            exif[0x8825] = dict(gps)
        exif[0x0112] = 1
        return exif.tobytes()
    except Exception:
        minimal = Image.Exif()
        minimal[0x0112] = 1
        return minimal.tobytes()


def with_exif(jpg: bytes, exif: bytes) -> bytes:
    """Setzt den EXIF-Block als APP1-Segment hinter den SOI-Marker, die Bilddaten bleiben unveraendert."""
    if not jpg.startswith(b"\xFF\xD8") or len(exif) + 2 > 0xFFFF:
        return jpg
    return b"\xFF\xD8\xFF\xE1" + struct.pack(">H", len(exif) + 2) + exif + jpg[2:]


def extract_embedded(data: bytes, out: Path) -> tuple[int, int]:
    """Groesstes eingebettetes JPG der NEF nach out schreiben, gedreht laut Orientation. Liefert die Pixelmasse."""
    candidates, orientation = scan_nef(data)
    if not candidates:
        raise ValueError("kein eingebettetes JPG in der NEF gefunden")
    start, length = max(candidates, key=lambda c: c[1])
    jpg = data[start:start + length]
    img = Image.open(io.BytesIO(jpg))
    exif = build_exif(data)
    transpose = ORIENTATION_TO_TRANSPOSE.get(orientation)
    if transpose is not None and (orientation == 3 or img.width > img.height):
        img = img.transpose(transpose)
        img.save(out, "JPEG", quality=95, subsampling=0, exif=exif)
    else:
        out.write_bytes(with_exif(jpg, exif))
    return img.size


def develop(data: bytes, out: Path, quality: int) -> None:
    """Komplette Rohdatenentwicklung: Demosaicing, Kamera-Weissabgleich, sRGB, 8 Bit."""
    with rawpy.imread(io.BytesIO(data)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
    Image.fromarray(rgb).save(out, "JPEG", quality=quality, subsampling=0, optimize=True, exif=build_exif(data))


def error_text(exc: BaseException) -> str:
    msg = exc.args[0] if exc.args else ""
    msg = msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg)
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def convert_one(job: Job) -> tuple[str, str, str, str]:
    """Eine Datei konvertieren. Liefert (Dateiname, Art, Detail, LibRaw-Problem).

    Art ist "entwickelt", "eingebettet" oder "fehler". Detail sind die Pixelmasse
    bzw. der Fehlertext. Fehler brechen den Gesamtlauf nicht ab.
    """
    nef, out, quality, embedded = job
    try:
        data = nef.read_bytes()
    except Exception as exc:
        return nef.name, "fehler", error_text(exc), ""
    libraw_problem = ""
    if not embedded:
        if rawpy is None:
            libraw_problem = "rawpy nicht installiert"
        else:
            try:
                develop(data, out, quality)
                return nef.name, "entwickelt", "", ""
            except rawpy.LibRawError as exc:  # z.B. HE/HE*-Dateien: "Unsupported file format"
                libraw_problem = error_text(exc)
            except Exception as exc:
                return nef.name, "fehler", error_text(exc), ""
    try:
        w, h = extract_embedded(data, out)
        return nef.name, "eingebettet", f"{w}x{h}", libraw_problem
    except Exception as exc:
        msg = error_text(exc)
        if libraw_problem:
            msg = f"LibRaw: {libraw_problem} / eingebettetes JPG: {msg}"
        return nef.name, "fehler", msg, libraw_problem


Job = tuple[Path, Path, int, bool]  # (NEF, Ziel-JPG, Qualitaet, eingebettet?)


def find_nefs(folder: Path) -> list[Path]:
    """Alle .NEF-Dateien direkt im Ordner, sortiert, Endung egal ob gross oder klein geschrieben."""
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".nef")


def collect_jobs(folder: Path, quality: int, embedded: bool, overwrite: bool) -> tuple[list[Job], int, list[Path]]:
    """Auftraege fuer den Ordner: (Auftraege, Anzahl uebersprungen, alle gefundenen NEFs)."""
    nefs = find_nefs(folder)
    out_dir = folder / "JPG"
    jobs: list[Job] = []
    skipped = 0
    for nef in nefs:
        out = out_dir / (nef.stem + ".jpg")
        if out.exists() and not overwrite:
            skipped += 1
            continue
        jobs.append((nef, out, quality, embedded))
    return jobs, skipped, nefs


def choose_folder() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    chosen = filedialog.askdirectory(title="Ordner mit NEF-Dateien auswaehlen")
    root.destroy()
    return Path(chosen) if chosen else None


def show_summary(text: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("nef2jpg", text)
    root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="NEF -> JPG in den Unterordner JPG")
    parser.add_argument("folder", nargs="?", help="Ordner mit NEF-Dateien (ohne Angabe: Dialog)")
    parser.add_argument("--embedded", action="store_true", help="eingebettetes Kamera-JPG nutzen (schnell)")
    parser.add_argument("--quality", type=int, default=92, help="JPG-Qualitaet 1-100 (Standard 92)")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 1, 8), help="parallele Prozesse")
    parser.add_argument("--overwrite", action="store_true", help="vorhandene JPGs ueberschreiben")
    opts = parser.parse_args()

    interactive = opts.folder is None
    folder = choose_folder() if interactive else Path(opts.folder)
    if folder is None:
        print("Abgebrochen.")
        return 1
    if not folder.is_dir():
        print(f"Kein Ordner: {folder}")
        return 1

    jobs, skipped, nefs = collect_jobs(folder, opts.quality, opts.embedded, opts.overwrite)
    if not nefs:
        msg = f"Keine .NEF-Dateien in {folder}"
        print(msg)
        if interactive:
            show_summary(msg)
        return 1

    out_dir = folder / "JPG"
    out_dir.mkdir(exist_ok=True)

    mode = "eingebettetes Kamera-JPG" if opts.embedded else "komplette Entwicklung"
    print(f"{len(nefs)} NEF-Dateien in {folder}  ->  {out_dir}")
    print(f"Modus: {mode}, {opts.jobs} parallele Prozesse, {skipped} bereits vorhanden (uebersprungen)")

    counts = {"entwickelt": 0, "eingebettet": 0, "fehler": 0}
    errors: list[str] = []
    libraw_problems: dict[str, int] = {}
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, opts.jobs)) as pool:
        futures = [pool.submit(convert_one, job) for job in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            name, kind, detail, libraw_problem = fut.result()
            counts[kind] += 1
            if libraw_problem:
                libraw_problems[libraw_problem] = libraw_problems.get(libraw_problem, 0) + 1
            if kind == "fehler":
                print(f"[{i}/{len(jobs)}] {name} ... FEHLER")
                errors.append(f"{name}: {detail}")
            elif kind == "eingebettet":
                print(f"[{i}/{len(jobs)}] {name} ... ok (eingebettetes Kamera-JPG, {detail})")
            else:
                print(f"[{i}/{len(jobs)}] {name} ... ok")
    elapsed = time.perf_counter() - start

    lines = [f"{counts['entwickelt']} entwickelt, {counts['eingebettet']} eingebettetes Kamera-JPG, "
             f"{counts['fehler']} Fehler, {skipped} uebersprungen, {elapsed:.1f} s"]
    for problem, n in libraw_problems.items():
        lines.append(f"Hinweis: {n} Dateien konnte LibRaw nicht entwickeln ({problem}).")
        lines.append("Das ist typisch fuer NEFs im HE/HE*-Format. Dafuer wurde das eingebettete Kamera-JPG uebernommen.")
    lines.extend("  " + e for e in errors)
    print("\n".join(lines))
    if interactive:
        show_summary("\n".join(lines))
    return 2 if errors else 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # noetig fuer eine PyInstaller-EXE unter Windows
    sys.exit(main())
