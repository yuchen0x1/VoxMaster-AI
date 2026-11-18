"""Fetch selected VocalSet 1.1 members from the official Zenodo ZIP, checking size and CRC."""

from __future__ import annotations
import argparse
import hashlib
import io
import json
import struct
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path

RECORD = "https://zenodo.org/records/1203819"
DOWNLOAD = RECORD + "/files/VocalSet11.zip"
SIZE = 2077243579
SELECTION = {
    "VS01": "FULL/female9/scales/breathy/f9_scales_breathy_a.wav",
    "VS02": "FULL/female9/scales/belt/f9_scales_belt_a.wav",
    "VS03": "FULL/male4/scales/vocal_fry/m4_scales_vocal_fry_a.wav",
    "VS04": "FULL/female9/long_tones/messa/f9_long_messa_a.wav",
    "VS05": "FULL/female9/scales/fast_piano/f9_scales_c_fast_piano_a.wav",
    "VS06": "FULL/male4/long_tones/pp/m4_long_pp_e.wav",
    "VS07": "FULL/female9/excerpts/straight/f9_dona_straight.wav",
}


def fetch_range(start, end):
    url = DOWNLOAD + f"?download=1&range={start}-{end}"
    request = urllib.request.Request(
        url,
        headers={
            "Range": f"bytes={start}-{end}",
            "User-Agent": "VoxMaster-MC-Acceptance/0.1.1",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if (
                    response.headers.get("Content-Range")
                    != f"bytes {start}-{end}/{SIZE}"
                ):
                    raise ValueError(
                        "Unexpected byte range or archive size from Zenodo"
                    )
                data = response.read(end - start + 2)
            if len(data) != end - start + 1:
                raise ValueError("Incomplete Zenodo response")
            return data
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    central_start = SIZE - 1100000
    central = zipfile.ZipFile(io.BytesIO(fetch_range(central_start, SIZE - 1)))
    result = []
    for key, member in SELECTION.items():
        info = central.getinfo(member)
        target = args.output / (key + ".wav")
        if target.exists():
            content = target.read_bytes()
        else:
            pos = central_start + info.header_offset
            chunk = fetch_range(pos, pos + info.compress_size + 1023)
            if chunk[:4] != b"PK\x03\x04" or info.compress_type != zipfile.ZIP_DEFLATED:
                raise ValueError("Unexpected ZIP member")
            name_len, extra_len = struct.unpack_from("<HH", chunk, 26)
            if chunk[30 : 30 + name_len].decode("ascii") != member:
                raise ValueError("Unexpected member name")
            data_start = 30 + name_len + extra_len
            content = zlib.decompress(
                chunk[data_start : data_start + info.compress_size], -15
            )
        if len(content) != info.file_size or zlib.crc32(content) != info.CRC:
            raise ValueError(f"CRC mismatch: {member}")
        if not target.exists():
            with target.open("xb") as f:
                f.write(content)
        result.append(
            dict(
                id=key,
                archive_url=DOWNLOAD,
                member=member,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
                author="Julia Wilkins, Prem Seetharaman, Alison Wahl, Bryan Pardo",
                attribution="VocalSet 1.1",
                license="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            )
        )
        print(key, member, len(content), flush=True)
    (args.output / "attribution.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
