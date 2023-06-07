from .mercado_libre.motor import MercadoLibre as ML, Category
from .palacio_de_hierro.motor import PalacioDeHierro as PH
from .liverpool.motor import Liverpool as LV
from scraper.motor import Motor


def get_motors() -> list[Motor]:
    return [
        ML('fire emblem'),
        ML('zelda ds'),
        ML('pokemon ds'),
        ML('nintendo ds', category = Category.consolas),
        ML('nintendo switch', category = Category.consolas),
        ML('lote juegos nintendo ds', category = Category.videojuegos),
        ML('lote ps4', category = Category.videojuegos),
        #ML('xenoblade switch', category = Category.videojuegos),
        ML('lote juegos nintendo switch', category = Category.videojuegos),
        ML('wii', category = Category.consolas),
        ML('pokemon nintendo switch'),
        ML('mario nintendo switch'),
        ML('zelda nintendo switch'),
        #ML('smash switch'),
        #ML('joycon'),
        #ML('dock nintendo switch'),
        #ML('cargador nintendo switch'),
        #ML('animal crossing ds'),
        ML('amiibo'),
        #ML('apple', category=Category.apple_official),
        ML('atlas', category=Category.deportes_jersey),
        #ML('ps vita', category = Category.consolas),
        #ML('psp', category = Category.consolas),
        ML('game boy', category = Category.consolas),
        #ML('juegos ds', category = Category.videojuegos),
        #ML('wii', category = Category.videojuegos),
        #ML('nintendo 64', category = Category.consolas),
        #PH(search_term = 'PH Computadoras', url ='https://www.elpalaciodehierro.com/electronica/computadoras/'),
        #PH(search_term = 'PH Videojuegos', url ='https://www.elpalaciodehierro.com/videojuegos/'),
        #PH(search_term = 'PH TV y Videos', url ='https://www.elpalaciodehierro.com/electronica/tv-video/'),
        #PH(search_term = 'PH Electrodomestios', url ='https://www.elpalaciodehierro.com/hogar/electrodomesticos/'),
        #PH(search_term = 'PH Celulares', url ='https://www.elpalaciodehierro.com/electronica/celulares/'),
        #PH(search_term = 'PH Tablets', url ='https://www.elpalaciodehierro.com/electronica/tablets/'),
        #PH(search_term = 'PH Audio', url ='https://www.elpalaciodehierro.com/electronica/audio/'),
        #PH(search_term = 'PH Camaras', url ='https://www.elpalaciodehierro.com/electronica/camaras/'),
        #PH(search_term = 'PH Instrumentos Musicales', url ='https://www.elpalaciodehierro.com/electronica/instrumentos-musicales/'),

        #LV(search_term = 'LV Celulares', url = 'https://www.liverpool.com.mx/tienda/Celulares/N-Z6GQrU4fZmxjTFXt9XTtjEVNIqwseF0ax1%2Fc4tPD6RI%3D'),
        #LV(search_term = 'LV Pantallas', url = 'https://www.liverpool.com.mx/tienda/Pantallas/N-Z6GQrU4fZmxjTFXt9XTtjOJ1pgsv3ORca6us58D3tcWUJ8Sz5xDngrfcZXSEmwVj'),
        #LV(search_term = 'LV Laptops', url = 'https://www.liverpool.com.mx/tienda/Laptops/N-Z6GQrU4fZmxjTFXt9XTtjADb51HPoq41uykVTx%2F8p7q4Lv5kmJ%2FB7n9SHDZAiZOr'),
        #LV(search_term = 'LV Tablets', url = 'https://www.liverpool.com.mx/tienda/Tablets/N-Z6GQrU4fZmxjTFXt9XTtjLBjV%2BmEL2zQn91638D96w4%3D'),
        #LV(search_term = 'LV Refrigeradores', url = 'https://www.liverpool.com.mx/tienda/Refrigeradores/N-Z6GQrU4fZmxjTFXt9XTtjKRm72EgKt7htgGCzKPWCVUuQ7CfeC6BdqAAyDrwfI%2FQ'),
        #LV(search_term = 'LV Lavadoras', url = 'https://www.liverpool.com.mx/tienda/Lavadoras/N-Z6GQrU4fZmxjTFXt9XTtjIsatM4%2F%2BXtT1xpWTV8Ce9pFejoKIubh5lKg%2Bkb6zYFt'),
        #LV(search_term = 'LV Cafeteras', url = 'https://www.liverpool.com.mx/tienda/Cafeteras%20y%20Molinos/N-Z6GQrU4fZmxjTFXt9XTtjMGMg%2BPbTviv0GV7AiYl%2FeJFejoKIubh5lKg%2Bkb6zYFt'),
        #LV(search_term = 'LV Juegos Nintendo', url = 'https://www.liverpool.com.mx/tienda/Juegos/N-Z6GQrU4fZmxjTFXt9XTtjEMtiDHLusAuxLK0y30fWRU5PhnhiYjJElHuz9EseRgf')
    ]
    
def _get_motors() -> list[Motor]:
    return [
        #LV(search_term = 'LV Pantallas', url = 'https://www.liverpool.com.mx/tienda/Pantallas/N-Z6GQrU4fZmxjTFXt9XTtjOJ1pgsv3ORca6us58D3tcWUJ8Sz5xDngrfcZXSEmwVj'),
        #ML('amiibo'),
        #ML('lote juegos nintendo ds', category = Category.videojuegos),
        #ML('lote juegos nintendo switch', category = Category.videojuegos)
    ]