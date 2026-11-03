"""Validate the actual ELF segments before accepting bare-metal firmware."""
from pathlib import Path
import struct


def validate_elf(path):
    data = Path(path).read_bytes()
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Expected ELF32 little-endian firmware')
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    if header[2] != 40:
        raise ValueError('Expected ARM firmware')
    segments = []
    for i in range(header[10]):
        kind, offset, address, physical, filesz, memsz, flags, align = struct.unpack_from(
            '<IIIIIIII', data, header[5] + i * header[9])
        if kind != 1 or not memsz:
            continue
        if filesz > memsz or offset + filesz > len(data):
            raise ValueError('Invalid ELF file-backed load region')
        if address != physical or not 0x01000000 <= address < address + memsz <= 0x02000000:
            raise ValueError('ELF load region is outside reserved firmware DDR')
        segments.append((address, address + memsz, flags))
    segments.sort()
    if any(a[1] > b[0] for a, b in zip(segments, segments[1:])):
        raise ValueError('Overlapping ELF load segments')
    if not any(lo <= header[4] < hi and flags & 1 for lo, hi, flags in segments):
        raise ValueError('ELF entry is outside executable load regions')
    return {'entry': header[4], 'load_regions': segments}
