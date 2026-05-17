import re
import unicodedata
import urllib.parse

from .options import Category

_BASE_SEARCH_URL = "https://listado.mercadolibre.com.mx"


def _slugify(term: str) -> str:
    term = unicodedata.normalize("NFKD", term or "")
    term = term.encode("ascii", "ignore").decode("ascii")
    term = term.lower().strip()
    term = re.sub(r"[^a-z0-9]+", "-", term)
    return re.sub(r"-+", "-", term).strip("-")


def get_identifier(url: str) -> str:
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)

    wid = qs.get("wid", [""])[0]
    if wid:
        return wid

    match = re.search(r"/up/(MLMU\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"/p/(MLM\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"(MLM-?\d+|MLMU\d+)", url)
    if match:
        return match.group(1)

    return url


def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    hardcoded_categories = {
        Category.iphone_trece_pro_usado,
        Category.iphone_once_pro_usado,
        Category.iphone_se_usado,
    }

    if category in hardcoded_categories:
        return category.value

    slug = _slugify(search_term)

    if category == Category.apple_official:
        path = f"{slug}_{category.value}"
        return f"{_BASE_SEARCH_URL}/{path}?sb=seller_id#D[A:{slug}]"

    if category == Category.none:
        return f"{_BASE_SEARCH_URL}/{slug}_NoIndex_True"

    category_path = category.value.rstrip("/")
    return f"{_BASE_SEARCH_URL}{category_path}/{slug}_NoIndex_True"
