#!/usr/bin/env python3
"""Create numbered sample media files for DRY_RUN tests without Google Drive."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "samples"


def png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    raw = b"".join(b"\x00" + (bytes([r, g, b]) * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def jpeg() -> bytes:
    # Tiny valid 1x1 JPEG.
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706050807070709"
        "09080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c283729"
        "2c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000"
        "010501010101010100000000000000000102030405060708090a0bffc400b51000020103"
        "03020403050504040000017d01020300041105122131410613516107227114328191a108"
        "2342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445"
        "464748494a535455565758595a636465666768696a737475767778797a83848586878889"
        "8a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9"
        "cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda00080101"
        "00003f00fbdc07ffd9"
    )


def mp4() -> bytes:
    # Minimal ISO BMFF file so the selector recognizes 4.mp4 / 6.mp4.
    ftyp = b"ftypisom" + (0).to_bytes(4, "big") + b"isomiso2mp41"
    moov = b"moov"
    mdat = b"mdat" + b"\x00" * 8
    def box(payload: bytes) -> bytes:
        return (len(payload) + 4).to_bytes(4, "big") + payload
    return box(ftyp) + box(moov) + box(mdat)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    files = {
        "1.jpg": jpeg(),
        "2.jpg": jpeg(),
        "3.png": png(64, 64, (214, 122, 62)),
        "4.mp4": mp4(),
        "5.jpg": jpeg(),
        "6.mp4": mp4(),
        "7.jpg": jpeg(),
        "notes.txt": b"ignore me - unsupported",
    }
    for name, data in files.items():
        (ROOT / name).write_bytes(data)
        print(f"Wrote samples/{name} ({len(data)} bytes)")
    print("Sample Product IDs: 1,2,3,4,5,6,7. notes.txt is ignored.")


if __name__ == "__main__":
    main()
