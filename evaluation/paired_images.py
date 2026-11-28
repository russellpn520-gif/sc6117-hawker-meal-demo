"""Reconstruct the frozen JPEG files locally. No model calls. Requires pypdf for atlas pages."""
import argparse
import csv
import hashlib
import io
from pathlib import Path
from urllib.parse import urldefrag

from PIL import Image
import requests
from pypdf import PdfReader
from recognition import prepare_photo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    folder = parser.parse_args().destination
    folder.mkdir(parents=True, exist_ok=True)
    documents = {}
    with Path(__file__).with_name("paired_samples.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url, page = urldefrag(row["photo"])
            if url not in documents:
                response = requests.get(url, timeout=45)
                response.raise_for_status()
                documents[url] = response.content
            source = io.BytesIO(documents[url])
            if page.startswith("page="):
                image = PdfReader(source).pages[int(page[5:]) - 1].images[0].image
            else:
                image = Image.open(source)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=94)
            jpeg = prepare_photo(buffer.getvalue())
            if hashlib.sha256(jpeg).hexdigest() != row["sha256"]:
                raise ValueError(f"Source or image encoder changed for {row['id']}")
            (folder / (row["id"] + ".jpg")).write_bytes(jpeg)


if __name__ == "__main__":
    main()
