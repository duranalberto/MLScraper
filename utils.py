from models.Category import Category
import json

data_path = './data/'

url_article_prefix = 'https://articulo.mercadolibre.com.mx/'
url_search = 'https://listado.mercadolibre.com.mx/consolas-videojuegos/|0|usado/|1|_NoIndex_True'

def write_in_file_old(file_name: str, content: str):
    if file_name and content:
        with open(data_path + file_name, 'w') as file:
            file.write(content)

async def write_in_file(file_name: str, content: str):
    if file_name and content:
        with open(data_path + file_name, 'w') as file:
            file.write(content)

def read_json_file(file_name: str) -> list:
    data = ''
    try:
        with open(data_path + file_name) as file:
            data = json.load(file)
    except FileNotFoundError:
        print('File does not exist: ' + data_path + file_name)
    return data

def get_identifier(url: str) -> str:
    if not url:
        return ''
    if url.startswith(url_article_prefix):
        url = url[len(url_article_prefix):]
    pre_url = url[:url.find('-') + 1]
    post_url = url[len(pre_url):]
    return pre_url + post_url[:post_url.find('-')]

def construct_url_from_identifier(identifier: str) -> str:
    return url_article_prefix + identifier

def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    url = url_search.replace('|0|', category.value + '/' if category is not Category.none else '')
    return url.replace('|1|', search_term.replace(' ', '-'))
