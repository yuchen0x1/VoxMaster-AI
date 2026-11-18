"""Fetch the public HQ previews selected in sources.json and verify their exact bytes."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def fetch_all(folder):
    folder.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(
        Path(__file__).with_name("sources.json").read_text(encoding="utf-8")
    )

    def fetch(item):
        target = folder / item["file"]
        if target.exists():
            data = target.read_bytes()
        else:
            with urllib.request.urlopen(item["download"], timeout=60) as response:
                data = response.read(12 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Unexpected preview digest for {item['id']}")
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(data)
        print(item["id"], len(data), flush=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, [item for item in catalog if item["id"].startswith("FS")]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    fetch_all(parser.parse_args().output)
