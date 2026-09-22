"""MP4 "faststart": move the ``moov`` index atom in front of ``mdat``.

Why: browsers cannot start playing an MP4 until they have the ``moov``
atom (the index of every sample). Encoders and phone cameras write it
LAST, so a player has to fetch to the end of the file before the first
frame shows — for hour-long lectures that is the "video takes forever
to load" complaint (prod, 2026-09-22: the intro clip was
``ftyp · free · mdat(22 MB) · moov``). With ``moov`` first, playback
begins after the first few hundred KB and seeking is a range request.

Pure Python (the backend image has no ffmpeg), same algorithm as
qt-faststart: rewrite the top-level atom order, drop top-level ``free``
padding, and shift every chunk offset (``stco`` / ``co64``) inside
``moov`` by the number of bytes that now precede ``mdat``.

Safety (CLAUDE.md rule 10 — stage → verify → swap): the new file is
written next to the original, re-parsed and size-checked, and only then
``os.replace``d over the original. Anything unexpected returns a
``skipped:`` status and leaves the original byte-for-byte untouched.
"""
from __future__ import annotations

import logging
import os
import struct
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".m4a"}
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta"}
_COPY_CHUNK = 4 * 1024 * 1024


@dataclass
class Atom:
    offset: int
    size: int          # full atom size incl. header
    type: bytes
    header: int        # 8 or 16 (64-bit size)


class NotMp4(Exception):
    pass


def _read_atoms(f, start: int, end: int) -> list[Atom]:
    """Top-level atoms in [start, end)."""
    out: list[Atom] = []
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size, typ = struct.unpack(">I4s", hdr)
        header = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                raise NotMp4("truncated 64-bit atom")
            size = struct.unpack(">Q", ext)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            raise NotMp4(f"bad atom size {size} at {pos}")
        out.append(Atom(pos, size, typ, header))
        pos += size
    return out


def _walk_child_atoms(buf: bytes, start: int, end: int):
    """Yield (offset, size, type, header) for atoms inside buf[start:end]."""
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise NotMp4(f"bad child atom at {pos}")
        yield pos, size, typ, header
        pos += size


def _shift_chunk_offsets(moov: bytearray, delta: int) -> int:
    """Add ``delta`` to every stco/co64 entry inside the moov atom.
    Returns the number of tables patched. Raises NotMp4 on a 32-bit
    overflow (would need a co64 upgrade — not attempted)."""
    patched = 0

    def visit(start: int, end: int):
        nonlocal patched
        for pos, size, typ, header in _walk_child_atoms(moov, start, end):
            body = pos + header
            if typ in _CONTAINERS:
                visit(body, pos + size)
            elif typ in (b"stco", b"co64"):
                # version(1) flags(3) count(4) then entries
                count = struct.unpack(">I", moov[body + 4:body + 8])[0]
                p = body + 8
                if typ == b"stco":
                    for _ in range(count):
                        v = struct.unpack(">I", moov[p:p + 4])[0] + delta
                        if v < 0 or v > 0xFFFFFFFF:
                            raise NotMp4("stco offset overflow after shift")
                        moov[p:p + 4] = struct.pack(">I", v)
                        p += 4
                else:
                    for _ in range(count):
                        v = struct.unpack(">Q", moov[p:p + 8])[0] + delta
                        if v < 0:
                            raise NotMp4("co64 offset underflow after shift")
                        moov[p:p + 8] = struct.pack(">Q", v)
                        p += 8
                patched += 1

    visit(0, len(moov))
    return patched


def inspect(path: Path) -> str:
    """'faststart' | 'needs' | 'skipped:<reason>' — never modifies."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            atoms = _read_atoms(f, 0, size)
    except (OSError, NotMp4, struct.error) as e:
        return f"skipped:{e}"
    types = [a.type for a in atoms]
    if b"ftyp" not in types or b"moov" not in types or b"mdat" not in types:
        return "skipped:not an mp4 (no ftyp/moov/mdat)"
    if types.index(b"moov") < types.index(b"mdat"):
        return "faststart"
    return "needs"


def faststart(path: Path) -> str:
    """Rewrite ``path`` with moov before mdat when needed.

    Returns 'converted', 'faststart' (already fine) or 'skipped:<reason>'.
    The original is replaced atomically only after the staged file
    re-parses with moov first and the expected size.
    """
    status = inspect(path)
    if status != "needs":
        return status
    tmp = path.with_name(path.name + ".faststart.tmp")
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            atoms = _read_atoms(f, 0, size)
            moov_atom = next(a for a in atoms if a.type == b"moov")
            mdat_atom = next(a for a in atoms if a.type == b"mdat")
            f.seek(moov_atom.offset)
            moov = bytearray(f.read(moov_atom.size))
            if len(moov) != moov_atom.size:
                raise NotMp4("truncated moov")
            if b"cmov" in moov:
                raise NotMp4("compressed moov (cmov) not supported")

            # New order: everything before mdat (minus free/moov), moov,
            # then the rest (minus free/moov). Top-level free padding is
            # dropped — that is what qt-faststart does too.
            before = [a for a in atoms if a.offset < mdat_atom.offset
                      and a.type not in (b"free", b"moov")]
            after = [a for a in atoms if a.offset >= mdat_atom.offset
                     and a.type not in (b"free", b"moov")]
            new_mdat_offset = sum(a.size for a in before) + moov_atom.size
            delta = new_mdat_offset - mdat_atom.offset
            _shift_chunk_offsets(moov, delta)
            expected = sum(a.size for a in before + after) + moov_atom.size

            with tmp.open("wb") as out:
                def copy(a: Atom):
                    f.seek(a.offset)
                    left = a.size
                    while left > 0:
                        chunk = f.read(min(_COPY_CHUNK, left))
                        if not chunk:
                            raise NotMp4("short read while copying")
                        out.write(chunk)
                        left -= len(chunk)
                for a in before:
                    copy(a)
                out.write(moov)
                for a in after:
                    copy(a)
                out.flush()
                os.fsync(out.fileno())

        # verify the staged file before touching the original
        if tmp.stat().st_size != expected:
            raise NotMp4(f"staged size {tmp.stat().st_size} != expected {expected}")
        if inspect(tmp) != "faststart":
            raise NotMp4("staged file does not parse as faststart")
        with tmp.open("rb") as f2:
            new_atoms = _read_atoms(f2, 0, expected)
            new_mdat = next(a for a in new_atoms if a.type == b"mdat")
            if new_mdat.offset != new_mdat_offset:
                raise NotMp4("mdat landed at an unexpected offset")
        os.replace(tmp, path)
        return "converted"
    except (OSError, NotMp4, struct.error, StopIteration) as e:
        log.warning("faststart skipped for %s: %s", path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"skipped:{e}"


def is_video_path(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTS
