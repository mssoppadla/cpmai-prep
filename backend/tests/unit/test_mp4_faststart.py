"""mp4 faststart — moov moved in front of mdat with chunk offsets shifted."""
from __future__ import annotations

import struct
from pathlib import Path

from app.services.mp4_faststart import faststart, inspect


def atom(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), typ) + body


def stco(offsets: list[int]) -> bytes:
    return atom(b"stco", b"\0\0\0\0" + struct.pack(">I", len(offsets))
                + b"".join(struct.pack(">I", o) for o in offsets))


def co64(offsets: list[int]) -> bytes:
    return atom(b"co64", b"\0\0\0\0" + struct.pack(">I", len(offsets))
                + b"".join(struct.pack(">Q", o) for o in offsets))


def build(moov_last: bool, table, with_free: bool = True) -> tuple[bytes, list[int]]:
    """ftyp · [free] · mdat · moov  (or moov before mdat)."""
    ftyp = atom(b"ftyp", b"isom\0\0\2\0isomiso2mp41")
    free = atom(b"free", b"\0" * 24) if with_free else b""
    mdat_body = bytes(range(256)) * 4
    mdat = atom(b"mdat", mdat_body)
    mdat_off = len(ftyp) + len(free) if moov_last else None
    # chunk offsets point into mdat's body
    def moov_for(mo: int) -> bytes:
        offs = [mo + 8, mo + 8 + 300, mo + 8 + 700]
        stbl = atom(b"stbl", table(offs))
        minf = atom(b"minf", stbl)
        mdia = atom(b"mdia", atom(b"hdlr", b"\0" * 16) + minf)
        trak = atom(b"trak", atom(b"tkhd", b"\0" * 20) + mdia)
        return atom(b"moov", atom(b"mvhd", b"\0" * 24) + trak)
    if moov_last:
        moov = moov_for(mdat_off)
        data = ftyp + free + mdat + moov
        return data, [mdat_off + 8, mdat_off + 8 + 300, mdat_off + 8 + 700]
    moov = moov_for(0)  # placeholder; recompute below
    mo = len(ftyp) + len(free) + len(moov)
    moov = moov_for(mo)
    return ftyp + free + moov + mdat, [mo + 8, mo + 8 + 300, mo + 8 + 700]


def read_offsets(data: bytes, typ: bytes) -> list[int]:
    i = data.index(typ) + 4 + 4  # after type + version/flags
    n = struct.unpack(">I", data[i:i + 4])[0]
    w, fmt = (4, ">I") if typ == b"stco" else (8, ">Q")
    return [struct.unpack(fmt, data[i + 4 + k * w:i + 4 + (k + 1) * w])[0] for k in range(n)]


def test_moves_moov_first_and_shifts_stco(tmp_path: Path):
    data, old_offs = build(True, stco)
    p = tmp_path / "v.mp4"; p.write_bytes(data)
    assert inspect(p) == "needs"
    assert faststart(p) == "converted"
    out = p.read_bytes()
    assert inspect(p) == "faststart"
    # free padding dropped: new size = old - free atom
    assert len(out) == len(data) - 32
    # mdat bytes intact and moov's offsets point at the same bytes
    new_offs = read_offsets(out, b"stco")
    for o_old, o_new in zip(old_offs, new_offs):
        assert out[o_new:o_new + 16] == data[o_old:o_old + 16]
    assert not (tmp_path / "v.mp4.faststart.tmp").exists()


def test_co64_and_idempotent(tmp_path: Path):
    data, old_offs = build(True, co64, with_free=False)
    p = tmp_path / "v.mp4"; p.write_bytes(data)
    assert faststart(p) == "converted"
    out = p.read_bytes()
    new_offs = read_offsets(out, b"co64")
    assert new_offs == [o + (len(out) - len(data) + (out.index(b"mdat") - 4) - (data.index(b"mdat") - 4)) for o in old_offs] \
        or all(out[n:n + 16] == data[o:o + 16] for o, n in zip(old_offs, new_offs))
    # second run is a no-op
    assert faststart(p) == "faststart"
    assert p.read_bytes() == out


def test_already_faststart_untouched(tmp_path: Path):
    data, _ = build(False, stco)
    p = tmp_path / "ok.mp4"; p.write_bytes(data)
    assert inspect(p) == "faststart"
    assert faststart(p) == "faststart"
    assert p.read_bytes() == data


def test_non_mp4_skipped_and_untouched(tmp_path: Path):
    p = tmp_path / "x.mp4"; p.write_bytes(b"RIFF....WEBMnot really" * 10)
    assert faststart(p).startswith("skipped:")
    assert p.read_bytes() == b"RIFF....WEBMnot really" * 10
    q = tmp_path / "t.mp4"; q.write_bytes(b"\0\0\0\x08ftyp")
    assert faststart(q).startswith("skipped:")
