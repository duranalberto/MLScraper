from bs4 import BeautifulSoup
from traceback import format_exc

from scraper.motor import Motor
from .utils import Seller


class Amazon(Motor):
    def __init__(self, search_term: str, seller: Seller = Seller.none):
        formated_title = search_term.lower().replace(" ", "+")
        url = f'https://www.amazon.com.mx/s?k={formated_title}&rh=p_6%3A{seller.value}'
        super().__init__(F'AZ {seller.name} - {search_term}', url)

    def scrape_page(self, body: dict):
        items = list()
        next_url = None

        soup = BeautifulSoup(body['content'], 'html.parser')
        root = soup.find('div', class_='s-main-slot s-result-list s-search-results sg-row')
        items_div = root.find_all('div', class_='sg-col-4-of-24 sg-col-4-of-12 s-result-item s-asin sg-col-4-of-16 sg-col s-widget-spacing-small sg-col-4-of-20')
        for item in items_div:
            args = {}
            identifier = item.attrs["data-asin"].strip()
            price = item.find('span', class_='a-offscreen', text=True)
            if(identifier and price):
                args['identifier']  = identifier
                args['url']         = f'https://www.amazon.com.mx/dp/{identifier}/'
                args['title']       = item.find('h2', class_='a-size-mini a-spacing-none a-color-base s-line-clamp-4').find('span', text=True).text
                args['price']       = float(price.text.replace("$", "").replace(",", ""))
                args['search_term'] = self.search_term
                items.append(args)
        try:
            next_a_tag = root.find('a', class_='s-pagination-item s-pagination-next s-pagination-button s-pagination-separator', href=True)
            href = next_a_tag['href']
            if href:
                next_url = f'https://www.amazon.com.mx{href}'
        except:
            #print(format_exc())
            pass
        
        return items, next_url