import re
import urllib.parse
from bs4 import BeautifulSoup
from scraper.motor import Motor
from .utils import Seller

class Amazon(Motor):
    DOMAIN = 'https://www.amazon.com.mx'

    def __init__(self, search_term: str, seller: Seller = Seller.none):
        self.search_term = search_term
        formatted_query = urllib.parse.quote_plus(search_term.lower())
        url = f'{self.DOMAIN}/s?k={formatted_query}{seller.filter_query}'
        super().__init__(f'AZ {seller.name} - {search_term}', url)

    def scrape_page(self, body: dict):
        items = []
        next_url = None

        content = body.get('content', '')
        soup = BeautifulSoup(content, 'lxml')
        
        # 1. Broadly find search result items.
        # The HTML uses 's-result-item' and 'data-component-type="s-search-result"'.
        items_div = soup.find_all('div', {'data-component-type': 's-search-result'})
        
        
        for item in items_div:
            asin = item.get('data-asin')
            if not asin:
                continue

            try:
                # 2. Robust Title Extraction
                # In your HTML, titles are usually in an 'h2' or a 'span' with a specific data attribute.
                # Targeting 'h2 a' is the most reliable way to get the text and link.
                title_tag = item.select_one('h2 a')
                if not title_tag:
                    # Fallback for grid views where it might be in a specific span class
                    title_tag = item.select_one('.a-size-base-plus.a-color-base.a-text-normal')
                
                if not title_tag:
                    continue
                
                title = title_tag.get_text(strip=True)

                # 3. Price Extraction
                # Targeted cleaning for Mexican Peso formatting (e.g., "$1,200.00").
                price_val = 0.0
                price_tag = item.select_one('span.a-price span.a-offscreen')
                
                if price_tag:
                    raw_price = price_tag.get_text()
                    # Remove currency symbols and commas before float conversion
                    price_str = re.sub(r'[^\d.]', '', raw_price.replace(',', ''))
                    price_val = float(price_str) if price_str else 0.0
                else:
                    # Skip items without price (like out of stock or ads without prices)
                    continue

                items.append({
                    'identifier': asin,
                    'url': f'{self.DOMAIN}/dp/{asin}/',
                    'title': title,
                    'price': price_val,
                    'search_term': self.search_term
                })

            except (ValueError, AttributeError):
                continue

        # 4. Pagination (Next Page)
        # Using the specific classes found in your HTML for the 'Next' button.
        next_tag = soup.select_one('a.s-pagination-next, span.s-pagination-next a')
        if next_tag and next_tag.get('href'):
            next_url = urllib.parse.urljoin(self.DOMAIN, next_tag['href'])
        
        return items, next_url