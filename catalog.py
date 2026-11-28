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


def mixed_soy_ginger_sauce(english, chinese):
    return (("酱油" in chinese and "姜油" in chinese)
            or bool(re.search(r"\bsoy\b.*\bginger\b|\bginger\b.*\bsoy\b", english, flags=re.I))
            and bool(re.search(r"\b(?:sauce|dressing|oil)\b", english, flags=re.I)))


# These descriptions add a serving vessel, garnish, shape or uncertain variety.
# Restrict the allowed qualifiers so a sauce or oil cannot be silently stripped.
def prepared_photo_reference(english, chinese):
    en, zh = normalize(english), normalize(chinese)
    herbs = r"(?:cilantro|coriander|scallions?|spring onions?)"
    if (re.fullmatch(r"(?:clear soup|clear broth)(?: (?:small|medium|large) bowl| with " + herbs
                     + r"(?:(?: and | )" + herbs + r")*)?", en)
            or re.fullmatch(r"清汤 (?:小碗|中碗|大碗|(?:带|加)?(?:香菜|葱花?|芫荽)(?: (?:香菜|葱花?|芫荽))*)", zh)):
        return "fdc-2707132"
    if re.fullmatch(r"(?:blanched|boiled) (?:leafy greens|greens)(?: (?:gai lan|chinese broccoli|style|like))*", en):
        if not re.search(r"炒|酱|酥|油|汁", zh):
            return "fdc-2709593"
    if re.fullmatch(r"(?:poached|boiled) chicken (?:breast thigh|breast or thigh)(?: sliced)?", en):
        return "boiled-chicken"
    return None


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
        # Prefer a curated exact local name to incidental synonyms in source
        # tables (including animal and produce names that share a translation).
        if mixed_soy_ginger_sauce(english, chinese):
            return None
        local = self.exact_food(chinese)
        if local in self.featured:
            return local
        direct = self.exact_food(english, chinese)
        if direct:
            return direct
        # Slicing changes the shape of an identified meat, but not its recipe.
        # Only reuse a curated equivalent. Preserve cooking, sauces and oil.
        base = re.sub(r"(肉)[片块丁]$|[（(]切[片块丁][)）]$", r"\1", chinese.strip())
        if base and base != chinese.strip():
            key = self.exact_food(base)
            if key in self.featured:
                return key
        if key := prepared_photo_reference(english, chinese):
            return key
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

    def photo_suggestions(self, english, chinese):
        """Short, user-confirmed alternatives, without unrelated search hits."""
        if mixed_soy_ginger_sauce(english, chinese):
            return []
        if direct := self.photo_match(english, chinese):
            return [direct]
        if chinese.strip() in {"酱油汁", "醬油汁"}:
            return ["fdc-2707442", "fdc-2707148"]
        candidates = {}
        for name in (chinese, english):
            query = normalize(name)
            for key in self.search(query, 12):
                if self[key].source == "gyg-au":
                    continue
                for label in self.labels[key]:
                    # A candidate name must actually occur in the description;
                    # overlapping on a common word like "rice" is insufficient.
                    if len(label) < 2:
                        continue
                    if re.search(r"[\u3400-\u9fff]", label):
                        related = label in query
                    else:
                        related = f" {label} " in f" {query} "
                    if related:
                        score = len(label) / len(query)
                        candidates[key] = max(score, candidates.get(key, 0))
        return sorted(candidates, key=lambda k: (-candidates[k], self.priority(k)))[:3]

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
