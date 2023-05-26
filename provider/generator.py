from .mercado_libre.motor import MercadoLibre as ML, Category
from scraper.motor import Motor


def get_motors() -> list[Motor]:
    return [
        #ML('fire emblem ds'),
        ML('zelda ds'),
        ML('pokemon ds'),
        ML('nintendo ds', category = Category.consolas),
        ML('nintendo switch', category = Category.consolas),
        ML('lote juegos nintendo ds', category = Category.videojuegos),
        ML('lote juegos nintendo switch', category = Category.videojuegos),
        #ML('wii', category = Category.consolas),
        ML('pokemon nintendo switch'),
        #ML('mario nintendo switch'),
        #ML('zelda nintendo switch'),
        #ML('smash switch'),
        #ML('joycon'),
        #ML('dock nintendo switch'),
        #ML('cargador nintendo switch'),
        ML('animal crossing ds'),
        ML('amiibo'),
        ML('atlas', category=Category.deportes_jersey),
        #ML('ps vita', category = Category.consolas),
        #ML('jersey atlas')
        #ML('psp', category = Category.consolas),
        #ML('game boy', category = Category.consolas),
        #ML('juegos ds', category = Category.videojuegos),
        #ML('wii', category = Category.videojuegos),
        #ML('nintendo 64', category = Category.consolas),
    ]
    
def _get_motors() -> list[Motor]:
    return [
        ML('amiibo'),
        #ML('lote juegos nintendo ds', category = Category.videojuegos),
        #ML('lote juegos nintendo switch', category = Category.videojuegos)
    ]