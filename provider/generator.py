from .mercado_libre.motor import MercadoLibre, Category
from scraper.motor import Motor


def get_motors() -> list[Motor]:
    return [
        MercadoLibre('fire emblem ds'),
        MercadoLibre('zelda ds'),
        MercadoLibre('pokemon ds'),
        MercadoLibre('nintendo ds', category = Category.consolas),
        MercadoLibre('nintendo switch', category = Category.consolas),
        #Manager('ps vita', category = Category.consolas),
        MercadoLibre('wii', category = Category.consolas),
        MercadoLibre('pokemon nintendo switch'),
        MercadoLibre('mario nintendo switch'),
        MercadoLibre('zelda nintendo switch'),
        MercadoLibre('smash switch'),
        MercadoLibre('joycon'),
        MercadoLibre('dock nintendo switch'),
        MercadoLibre('cargador nintendo switch'),
        MercadoLibre('animal crossing ds'),
        MercadoLibre('amiibo'),
        #Manager('jersey atlas')
        #Manager('psp', category = Category.consolas),
        #Manager('game boy', category = Category.consolas),
        #Manager('juegos ds', category = Category.videojuegos),
        #Manager('wii', category = Category.videojuegos),
        #Manager('nintendo 64', category = Category.consolas),
    ]
    