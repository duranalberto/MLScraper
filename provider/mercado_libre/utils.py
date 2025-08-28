import re
from enum import Enum

_urls = {
    # Standard article base
    'article_prefix': 'https://articulo.mercadolibre.com.mx/',
    # Catalog item base
    'catalog_prefix': 'https://www.mercadolibre.com.mx/up/',
    'url_search': 'https://listado.mercadolibre.com.mx|0|/usado/|1|_NoIndex_True'
}

class Category(Enum):
    none = ''
    consolas = '/consolas-videojuegos/consolas'
    videojuegos = '/consolas-videojuegos/videojuegos'
    consolas_videojuegos = '/consolas-videojuegos'
    deportes_jersey = '/deportes-fitness/futbol'
    iphone_trece_pro_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-13-pro_NoIndex_True'
    iphone_once_pro_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-11-pro_NoIndex_True'
    iphone_se_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-se_NoIndex_True'
    apple_official = 'https://listado.mercadolibre.com.mx/_CustId_527927603_BRAND_9344_NoIndex_True' 

def get_identifier(url: str) -> str:
    if not url:
        return ''
    
    # regex finds MLM-123456789 or MLMU123456789
    match = re.search(r'(MLM-?\d+|MLMU\d+)', url)
    if match:
        return match.group(1)
    
    return url 

def construct_url_from_identifier(identifier: str) -> str:
    """
    Constructs the URL based on the ID type.
    MLMU (Catalog) -> https://www.mercadolibre.com.mx/up/MLMU...
    MLM (Standard) -> https://articulo.mercadolibre.com.mx/MLM...
    """
    if not identifier:
        return ''
    
    if identifier.startswith('MLMU'):
        return f"{_urls['catalog_prefix']}{identifier}"
    
    return f"{_urls['article_prefix']}{identifier}"

def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    # Check if category is one of the hardcoded URLs
    hardcoded_categories = [
        Category.apple_official, 
        Category.iphone_trece_pro_usado, 
        Category.iphone_once_pro_usado, 
        Category.iphone_se_usado
    ]
    
    if category in hardcoded_categories:
        return category.value
        
    url = _urls['url_search'].replace('|0|', category.value)
    return url.replace('|1|', search_term.replace(' ', '-'))