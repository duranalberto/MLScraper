from bs4 import BeautifulSoup
from scraper.motor import Motor
from .utils import Category, get_identifier, construct_url_from_identifier, construct_search_url

class MercadoLibre(Motor):
    def __init__(self, search_term: str, category: Category = Category.consolas_videojuegos):
        super().__init__(search_term, construct_search_url(search_term, category))

    def scrape_page(self, body):
        items = list()
        next_url = None
        soup = BeautifulSoup(body['content'], 'html.parser')
        
        # Look for the main results container
        root = soup.find("section", class_="ui-search-results")
        if not root:
            return items, None

        # ML uses 'ui-search-layout__item' for search result cards
        item_li = root.find_all("li", class_="ui-search-layout__item")
        
        for item in item_li:
            try:
                # In your HTML, the title is inside an <a> tag
                # which is inside a wrapper (often h2 or div)
                link_tag = item.find("a", href=True)
                if not link_tag: continue
                
                raw_url = link_tag['href']
                identifier = get_identifier(raw_url)
                
                # If we couldn't find a clean ID, we skip or use raw URL to avoid broken prefixes
                if not identifier or identifier.startswith('http'):
                    clean_url = raw_url
                else:
                    clean_url = construct_url_from_identifier(identifier)

                # Price extraction
                price_span = item.find("span", class_="andes-money-amount__fraction")
                
                args = {
                    'identifier': identifier,
                    'title': link_tag.get_text(strip=True),
                    'price': price_span.get_text(strip=True) if price_span else "0",
                    'search_term': self.search_term,
                    'url': clean_url
                }
                items.append(args)
            except Exception as e:
                if self.debug: print(f"Error parsing item: {e}")
                continue

        # Pagination handling
        try:
            next_a = root.find("a", class_="andes-pagination__link", attrs={"title": "Siguiente"})
            if not next_a:
                # Fallback for different pagination classes
                next_li = root.find("li", class_="andes-pagination__button--next")
                if next_li: next_a = next_li.find("a", href=True)
            
            if next_a:
                next_url = next_a['href']
        except:
            pass
        
        return items, next_url