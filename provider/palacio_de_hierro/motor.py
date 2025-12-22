import json
import uuid
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
from scraper.motor import Motor


class PalacioDeHierro(Motor):
    BASE_DOMAIN = "https://www.elpalaciodehierro.com"
    CONSTRUCTOR_ENDPOINT = "https://ac.cnstrc.com/search"

    def __init__(self, search_term: str, url: str):
        super().__init__(search_term, url)
        self.client_id = str(uuid.uuid4())
        self.session_id = 1
        
        # IMPROVEMENT: Use a Session object for connection pooling (Keep-Alive)
        # This makes subsequent requests to the same domain significantly faster.
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    # -------------------------------------------------
    # HTTP
    # -------------------------------------------------
    def download(self, url: str) -> dict:
        # IMPROVEMENT: Use self.session instead of generic requests
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return {"url": url, "content": r.text}

    # -------------------------------------------------
    # ENTRY POINT
    # -------------------------------------------------
    def scrape_page(self, body: dict):
        parsed = urllib.parse.urlparse(body.get("url", ""))
        soup = BeautifulSoup(body.get("content", ""), "lxml")

        # Both Search and Category pages follow the exact same API logic
        # We route them to a unified processor to reduce code duplication.
        return self._process_grid_page(soup, parsed)

    # -------------------------------------------------
    # UNIFIED GRID LOGIC
    # -------------------------------------------------
    def _process_grid_page(self, soup, parsed):
        current_page = self._extract_current_page(parsed)
        
        # Extract config with safety checks
        api_key, page_size, depth = self._extract_constructor_config(soup)
        
        # If we can't find an API key, we can't fetch items. Return empty.
        if not api_key:
            return [], None

        offset = (current_page - 1) * page_size

        response = self._fetch_constructor_results(
            api_key=api_key,
            offset=offset,
            page_size=page_size,
            depth=depth,
        )

        items = self._extract_items(response)

        # Pagination Logic
        has_next = len(items) > 0
        next_url = None
        
        if has_next:
            next_url = self._build_next_url(parsed, current_page + 1)

        return items, next_url

    # -------------------------------------------------
    # CONSTRUCTOR FETCH
    # -------------------------------------------------
    def _fetch_constructor_results(self, api_key, offset, page_size, depth):
        current_page = (offset // page_size) + 1

        params = {
            "c": "ciojs-client-2.62.4",
            "key": api_key,
            "i": self.client_id,
            "s": self.session_id,
            "page": current_page,
            "num_results_per_page": page_size,
            "fmt_options[groups_max_depth]": depth,
            "_dt": int(time.time() * 1000),
        }

        clean_query = self.search_term.replace("PH ", "")
        safe_query = urllib.parse.quote(clean_query)
        
        url = (
            f"{self.CONSTRUCTOR_ENDPOINT}/{safe_query}?"
            f"{urllib.parse.urlencode(params)}"
        )
        
        # print(f"Fetching API: {url}") # Commented out to reduce I/O noise

        try:
            # Reusing the download method which now uses the persistent session
            response_data = self.download(url)["content"]
            data = json.loads(response_data)
            return data.get("response", {})
        except Exception:
            return {}

    # -------------------------------------------------
    # ITEM EXTRACTION
    # -------------------------------------------------
    def _extract_items(self, response):
        items = []
        # Safety: Ensure 'results' is a list, even if API returns None or dict
        results = response.get("results", [])
        if not isinstance(results, list):
            return items

        for r in results:
            d = r.get("data", {})
            
            product_url = d.get("url") or ""
            if product_url and product_url.startswith("/"):
                product_url = f"{self.BASE_DOMAIN}{product_url}"

            try:
                raw_price = d.get("price") or 0
                price_val = float(raw_price)
            except (ValueError, TypeError):
                price_val = 0.0

            # Identifier fallback to prevent errors if 'id' is missing
            identifier = d.get("id") or (r.get("matched_terms") and r.get("matched_terms")[0]) or str(uuid.uuid4())

            items.append({
                "identifier": identifier,
                "url": product_url,
                "title": r.get("value"),
                "price": price_val,
                "search_term": self.search_term,
            })

        return items

    # -------------------------------------------------
    # HTML CONFIG (IMPROVED SAFETY)
    # -------------------------------------------------
    def _extract_constructor_config(self, soup):
        api_key = None
        
        # IMPROVEMENT: Safety check. If select_one returns None, .get() would crash.
        controller = soup.select_one("div[data-js-constructor-controller]")
        if controller:
            api_key = controller.get("data-api-key")

        page_size = 28
        depth = 5

        config = soup.select_one('section[data-component="search/ConstructorSearch"]')

        if config and config.has_attr("data-component-options"):
            try:
                opts = json.loads(config["data-component-options"])
                page_size = opts.get("pageSize", page_size)
                depth = opts.get("groupsMaxDepth", depth)
            except Exception:
                pass

        return api_key, page_size, depth

    # -------------------------------------------------
    # PAGE STATE
    # -------------------------------------------------
    def _extract_current_page(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        if "params" in qs:
            try:
                params = json.loads(urllib.parse.unquote(qs["params"][0]))
                return int(params.get("page", 1))
            except Exception:
                pass
        return 1

    def _build_next_url(self, parsed, next_page):
        qs = urllib.parse.parse_qs(parsed.query)
        qs['params'] = [json.dumps({'page': next_page})]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))