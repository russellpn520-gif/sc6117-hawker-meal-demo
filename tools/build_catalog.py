"""Build the bundled food table from official files listed in data/SOURCES.md."""
import argparse
import csv
import io
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

FIELDS = "source code name aliases reference_g kcal protein_g carb_g fat_g portion_g portion_label".split()


def number(value):
    """A blank, trace or unavailable observation is not a numeric zero."""
    try:
        value = float(str(value).strip().strip("[]"))
        return value if math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


def row(source, code, name, macros, aliases="", reference=100, portion=100, label=""):
    values = [number(v) for v in macros]
    if None in values:
        return None
    return dict(zip(FIELDS, [source, code, " ".join(name.split()), " ".join(aliases.split()), reference,
                             *(f"{v:.5f}".rstrip("0").rstrip(".") for v in values),
                             portion, label]))


def archived_csv(archive, suffix):
    name = next(n for n in archive.namelist() if n.endswith(suffix))
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def usda(path, source):
    with ZipFile(path) as archive:
        # The Survey CSV uses nutrient numbers, SR Legacy uses FDC nutrient IDs.
        columns = ("208", "203", "205", "204") if source == "fndds" else ("1008", "1003", "1005", "1004")
        nutrients = defaultdict(dict)
        for r in archived_csv(archive, "/food_nutrient.csv"):
            if r["nutrient_id"] in columns:
                nutrients[r["fdc_id"]][r["nutrient_id"]] = r["amount"]
        portions = {}
        for r in archived_csv(archive, "/food_portion.csv"):
            weight = number(r["gram_weight"])
            if source != "fndds" or not weight or not 1 <= weight <= 3000:
                continue
            desc = r["portion_description"].strip()
            if not desc or "quantity not specified" in desc.lower():
                continue
            rank = int(r["seq_num"])
            if r["fdc_id"] not in portions or rank < portions[r["fdc_id"]][0]:
                portions[r["fdc_id"]] = (rank, round(weight), desc)
        for r in archived_csv(archive, "/food.csv"):
            code = r["fdc_id"]
            _, grams, label = portions.get(code, (0, 100, ""))
            yield row(source, code, r["description"], [nutrients[code].get(k) for k in columns],
                      portion=grams, label=label)


def workbook(path, source):
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = "1.3 Proximates" if source == "cofid" else "03 NV_sum_39 (per 100g EP)"
        for r in book[sheet].values:
            if source == "cofid" and re.fullmatch(r"\d+-\d+", str(r[0])):
                yield row(source, r[0], r[1], [r[i] for i in (12, 9, 11, 10)])
            elif source == "wafct" and re.fullmatch(r"\d+_\d+", str(r[0])):
                yield row(source, r[0], r[1], [r[i] for i in (7, 9, 11, 10)], aliases=r[2] or "")
    finally:
        book.close()


def taiwan(path):
    from opencc import OpenCC
    simplify = OpenCC("t2s").convert
    foods = {}
    columns = ("熱量", "粗蛋白", "總碳水化合物", "粗脂肪")
    with ZipFile(path) as archive:
        for r in archived_csv(archive, ".csv"):
            if r["分析項"] not in columns or r["含量單位"].strip().lower() != ("kcal" if r["分析項"] == columns[0] else "g"):
                continue
            code = r["整合編號"]
            if code not in foods:
                names = [r["樣品名稱"], *re.split("[,;，；、]", r["俗名"]), *r["樣品英文名稱"].split(";")]
                aliases = dict.fromkeys(n.strip() for name in names for n in (name, simplify(name)) if n.strip())
                foods[code] = (simplify(r["樣品名稱"]), "|".join(aliases), {})
            foods[code][2][r["分析項"]] = r["每100克含量"]
    for code, (name, aliases, values) in foods.items():
        yield row("tfda", code, name, [values.get(k) for k in columns], aliases)


def hawker(path):
    for table in ET.parse(path).findall(".//table-wrap")[:3]:
        for r in table.findall(".//tbody/tr"):
            cells = ["".join(c.itertext()).strip() for c in r]
            name = cells[0]
            grams, kj, protein, fat, carb = (float(v.split("±")[0].strip()) for v in cells[1:])
            code = re.sub("[^a-z0-9]+", "-", name.lower()).strip("-")
            yield row("sgstudy", code, name, [kj / 4.184, protein, carb, fat],
                      portion=round(grams), label="研究样本一份")


def gyg(path):
    import pymupdf
    with pymupdf.open(path) as pdf:
        for page, heading, size in [(17, "BOWL", "regular"), (31, "MINI BOWL", "mini")]:
            lines = [s.strip() for s in pdf[page - 1].get_text().splitlines()]
            lines = lines[lines.index(heading):]
            pos = lines.index("(mg)") + 1
            while pos < len(lines) and lines[pos].startswith("Mild "):
                name = lines[pos]
                values = [float(x) for x in lines[pos + 1:pos + 11]]
                grams, _, kcal, protein, fat, _, carb, *_ = values
                code = size + "-" + re.sub("[^a-z0-9]+", "-", name.casefold()).strip("-")
                yield row("gyg-au", code, f"GYG Australia {size} burrito bowl, {name}",
                          [kcal, protein, carb, fat], reference=int(grams), portion=int(grams),
                          label="澳大利亚菜单一份")
                pos += 11


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()
    d = args.input_dir
    groups = [usda(d/"fndds.zip", "fndds"), usda(d/"sr.zip", "sr"), workbook(d/"uk.xlsx", "cofid"),
              taiwan(d/"tw.csv"), workbook(d/"wa.xlsx", "wafct"), hawker(d/"hawker.xml"), gyg(d/"261029.pdf")]
    records = [r for group in groups for r in group if r]
    assert len({(r["source"], r["code"]) for r in records}) == len(records)
    with args.output_csv.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda r: (r["source"], r["code"])))
    print(Counter(r["source"] for r in records))


if __name__ == "__main__":
    main()
