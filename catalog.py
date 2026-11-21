import csv
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NUTRIENTS = ("kcal", "protein_g", "carb_g", "fat_g")
HPB = ("https://isomer-user-content.by.gov.sg/484/d2884b81-4dfc-4a9e-b153-1487969794d5/"
       "obesity-cpg_main_for-online-30-aug.pdf")
GYG = "https://www.guzmanygomez.com.au/wp-content/uploads/2026/11/261029_NUTRITION_ALLERGEN_GUIDE_420X297MM.pdf"
SOURCES = {
    "hpb": ("HPB · 新加坡", HPB),
    "fndds": ("USDA · 膳食调查", "https://fdc.nal.usda.gov/food-details/{code}/nutrients"),
    "sr": ("USDA · SR Legacy", "https://fdc.nal.usda.gov/food-details/{code}/nutrients"),
    "cofid": ("英国 CoFID", "https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid"),
    "tfda": ("台湾食药署", "https://data.gov.tw/dataset/8543"),
    "wafct": ("FAO/INFOODS · 西非", "https://www.fao.org/fileadmin/user_upload/faoweb/2020/WAFCT_2019.xlsx"),
    "sgstudy": ("新加坡餐食实测", "https://doi.org/10.3390/foods10071659"),
    "gyg-au": ("GYG · 澳大利亚菜单", GYG),
}


@dataclass(frozen=True, slots=True)
class Food:
    food_id: str
    name: str
    source_name: str
    aliases: tuple
    serving_g: int
    reference_g: int
    nutrients: dict
    source: str
    code: str
    portion_label: str

    @property
    def source_url(self):
        url = SOURCES[self.source][1].format(code=self.code)
        if self.source == "hpb":
            return f"{url}#page={int(self.code) + 7}"
        if self.source == "gyg-au":
            return url + ("#page=31" if self.code.startswith("mini") else "#page=17")
        return url

    @property
    def source_label(self):
        return SOURCES[self.source][0]


def normalize(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def terms(text):
    result = set()
    for word in re.findall(r"[a-z\d]+|[\u3400-\u9fff]+", text):
        if "\u3400" <= word[0] <= "\u9fff":
            result.update(word[i:i + min(2, len(word))] for i in range(max(1, len(word) - 1)))
        elif word not in {"the", "of", "with", "and", "a"}:
            result.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return result


class Catalog(dict):
    def __init__(self, foods, featured):
        super().__init__((f.food_id, f) for f in foods)
        self.featured = set(featured)
        self.exact = defaultdict(list)
        self.index = defaultdict(set)
        self.labels = {}
        for f in self.values():
            labels = tuple(dict.fromkeys(normalize(x) for x in (f.name, f.source_name, *f.aliases) if x))
            self.labels[f.food_id] = labels
            for text in labels:
                self.exact[text].append(f.food_id)
                for word in terms(text):
                    self.index[word].add(f.food_id)
        self.counts = Counter(f.source for f in self.values())

    def priority(self, key):
        return (key not in self.featured, self[key].source != "fndds", len(self[key].name), key)

    def exact_food(self, *names):
        for name in names:
            matches = self.exact.get(normalize(name), [])
            if matches:
                return min(matches, key=self.priority)
        return None

    def photo_match(self, english, chinese):
        direct = self.exact_food(english, chinese)
        if direct:
            return direct
        # Reordered names are fine. A different variety, cooking method or
        # ingredient changes the reference and needs the diner's confirmation.
        query = terms(normalize(english))
        if len(query) < 2:
            return None
        nearby = set.intersection(*(self.index.get(word, set()) for word in query))
        matches = []
        for key in nearby:
            if self[key].source == "gyg-au":
                continue
            for label in self.labels[key]:
                tokens = terms(label)
                if query <= tokens and tokens - query <= {"nfs"}:
                    matches.append(key)
                    break
        return min(matches, key=self.priority, default=None)

    def search(self, query, limit=18):
        query = normalize(query)
        if not query:
            return ()
        words = terms(query)
        hits = Counter(k for word in words for k in self.index.get(word, ()))
        if not hits and len(query) >= 2:
            hits.update(k for k, labels in self.labels.items() if any(query in label for label in labels))
        exact = set(self.exact.get(query, ()))
        for key in exact:
            hits[key] += 0
        def score(key):
            labels = self.labels[key]
            contained = [len(s) for s in labels if query in s]
            return (key not in exact, -hits[key], min(contained, default=10000), *self.priority(key))
        return tuple(sorted(hits, key=score)[:limit])

def load_foods():
    paths = (ROOT / "foods.csv", ROOT / "data/catalog.csv", ROOT / "data/aliases.csv")
    stats = [path.stat() for path in paths]
    return _read_foods(tuple((s.st_mtime_ns, s.st_size) for s in stats))


@lru_cache(maxsize=1)
def _read_foods(revision):
    with (ROOT / "data/aliases.csv").open(encoding="utf-8", newline="") as fh:
        custom = {r["food_id"]: r for r in csv.DictReader(fh)}
    foods = []
    for path in (ROOT / "foods.csv", ROOT / "data/catalog.csv"):
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                source = r.get("source", "hpb")
                code = r.get("code") or r["source_page"]
                key = r.get("food_id") or f"{'fdc' if source in ('fndds', 'sr') else source}-{code}"
                label = custom.get(key, {})
                aliases = tuple(x for s in (r["aliases"], label.get("aliases", "")) for x in s.split("|") if x)
                ref = int(r.get("reference_g") or r["serving_g"])
                portion = int(r.get("portion_g") or ref)
                foods.append(Food(key, label.get("name") or r["name"], r.get("source_name") or r["name"],
                                  aliases, portion, ref, {k: float(r[k]) for k in NUTRIENTS},
                                  source, code, r.get("portion_label", "标准一份")))
    catalog = Catalog(foods, set(custom) | {f.food_id for f in foods if f.source == "hpb"})
    if set(custom) - catalog.keys() or len(catalog) != len(foods):
        raise ValueError("食物库中存在重复或失效的条目标识。")
    return catalog
