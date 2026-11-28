"""Reconstruct the frozen JPEG files locally. No model calls. Requires pypdf for atlas pages."""
import argparse
import csv
import hashlib
import io
from pathlib import Path
from urllib.parse import urldefrag

from PIL import Image
import requests
from recognition import prepare_photo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--release", action="store_true", help="Rebuild the final 30 hawker and nutrition-panel photos")
    args = parser.parse_args()
    folder = args.destination
    folder.mkdir(parents=True, exist_ok=True)
    documents = {}
    manifest = "release_samples.csv" if args.release else "paired_samples.csv"
    with Path(__file__).with_name(manifest).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url, page = urldefrag(row["photo"])
            if url not in documents:
                response = requests.get(url, timeout=45)
                response.raise_for_status()
                documents[url] = response.content
            source = io.BytesIO(documents[url])
            if page.startswith("page="):
                from pypdf import PdfReader
                image = PdfReader(source).pages[int(page[5:]) - 1].images[0].image
            else:
                image = Image.open(source)
            buffer = io.BytesIO()
            image = image.convert("RGB")
            label = args.release and row["category"] == "label"
            if label:
                image.thumbnail((1150, 1150))
            image.save(buffer, format="JPEG", quality=93 if label else 94)
            jpeg = prepare_photo(buffer.getvalue())
            if hashlib.sha256(jpeg).hexdigest() != row["sha256"]:
                raise ValueError(f"Source or image encoder changed for {row['id']}")
            (folder / (row["id"] + ".jpg")).write_bytes(jpeg)


if __name__ == "__main__":
    main()
