"""Baut NEF-aehnliche TIFF-Dateien: IFD0 + SubIFDs (grosses JPG), Exif-IFD, Nikon-MakerNote mit Vorschau."""
import io, struct
from PIL import Image

def make_jpeg(w, h, color):
    b = io.BytesIO(); Image.new("RGB", (w, h), color).save(b, "JPEG", quality=90); return b.getvalue()

def build_nef(E, orientation, big=(400, 300), small=(160, 120)):
    def pack(typ, val):
        if typ == 2: return val.encode("ascii") + b"\0"
        if typ == 7: return val
        if typ == 3: return b"".join(struct.pack(E + "H", v) for v in val)
        if typ in (4, 13): return b"".join(struct.pack(E + "I", v) for v in val)
        if typ == 5: return b"".join(struct.pack(E + "II", n, d) for n, d in val)
        raise ValueError(typ)
    def count(typ, val):
        return len(pack(typ, val)) if typ in (2, 7) else len(val)
    def write_ifd(buf, entries, nxt=0):
        n = len(entries); ifd_off = len(buf); data_off = ifd_off + 2 + 12 * n + 4
        body = bytearray(struct.pack(E + "H", n)); extra = bytearray()
        for tag, typ, val in sorted(entries):
            p = pack(typ, val)
            if len(p) <= 4:
                field = p.ljust(4, b"\0")
            else:
                field = struct.pack(E + "I", data_off + len(extra)); extra += p
                if len(extra) % 2: extra += b"\0"
            body += struct.pack(E + "HHI", tag, typ, count(typ, val)) + field
        body += struct.pack(E + "I", nxt)
        buf += body + extra
        return ifd_off
    header = b"MM\0\x2a\0\0\0\0" if E == ">" else b"II\x2a\0\0\0\0\0"
    big_jpg, small_jpg = make_jpeg(*big, "red"), make_jpeg(*small, "blue")

    mnt = bytearray(header); small_off = len(mnt); mnt += small_jpg
    if len(mnt) % 2: mnt += b"\0"
    prev_ifd = write_ifd(mnt, [(0x0201, 4, [small_off]), (0x0202, 4, [len(small_jpg)])])
    mn_ifd = write_ifd(mnt, [(0x0001, 7, b"0211"), (0x0011, 4, [prev_ifd])])
    struct.pack_into(E + "I", mnt, 4, mn_ifd)
    makernote = b"Nikon\0\x02\x11\0\0" + bytes(mnt)

    buf = bytearray(header); big_off = len(buf); buf += big_jpg
    if len(buf) % 2: buf += b"\0"
    raw_off = len(buf); buf += b"\0" * 64
    exif_ifd = write_ifd(buf, [(0x829A, 5, [(1, 250)]), (0x829D, 5, [(28, 10)]), (0x8827, 3, [400]),
                               (0x9000, 7, b"0232"), (0x9003, 2, "2026:09:29 14:00:00"),
                               (0x920A, 5, [(50, 1)]), (0x927C, 7, makernote)])
    sub0 = write_ifd(buf, [(0x00FE, 4, [1]), (0x0100, 4, [big[0]]), (0x0101, 4, [big[1]]), (0x0103, 3, [6]),
                           (0x0201, 4, [big_off]), (0x0202, 4, [len(big_jpg)])])
    sub1 = write_ifd(buf, [(0x00FE, 4, [0]), (0x0100, 4, [8]), (0x0101, 4, [8]), (0x0103, 3, [34713]),
                           (0x0111, 4, [raw_off]), (0x0117, 4, [64])])
    ifd0 = write_ifd(buf, [(0x00FE, 4, [1]), (0x010F, 2, "NIKON CORPORATION"), (0x0110, 2, "NIKON Z 9"),
                           (0x0112, 3, [orientation]), (0x0131, 2, "Ver.05.00"), (0x0132, 2, "2026:09:29 14:00:00"),
                           (0x014A, 4, [sub0, sub1]), (0x8769, 4, [exif_ifd])])
    struct.pack_into(E + "I", buf, 4, ifd0)
    return bytes(buf), big_jpg
