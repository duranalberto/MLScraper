import asyncio
import json
import time
import requests

from secret import apiToken, chatID
from manager import Manager
from models.Category import Category


class Scrapper:
    def __init__(self, caller = None):
        self.sleep_time = 30
        self.managers = [
            Manager('fire emblem ds'),
            Manager('animal crossing ds'),
            Manager('pokemon ds'),
            Manager('zelda ds'),
            Manager('nintendo ds', category = Category.consolas),
            Manager('ps vita', category = Category.consolas),
            Manager('psp', category = Category.consolas),
            Manager('game boy', category = Category.consolas),
            Manager('wii', category = Category.consolas),
            #Manager('juegos ds', category = Category.videojuegos),
            #Manager('pokemon nintendo switch'),
            #Manager('wii', category = Category.videojuegos),
            #Manager('nintendo switch', category = Category.consolas),
            #Manager('nintendo 64', category = Category.consolas),
        ]      
        self.caller = caller  


    def get_list(self):
        return [{'title':element.search_term,'elements':element.active.get_list()} for element in self.managers]


    async def scrape(self):
        while True:
            start_time = time.time()
            tasks = []

            for manager in self.managers:
                task = asyncio.create_task(manager.scrape(caller = self.broadcast_new_element, silent = True))
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            time_difference = time.time() - start_time
            await self.broadcast_scrape_finished(f'Scraping time: %.2f seconds.' % time_difference)
            await asyncio.sleep(self.sleep_time)
    

    async def broadcast_new_element(self, element):
        response = {
            'message': 'new element',
            'payload': element
        }
        self.send_to_telegram(element)
        if self.caller is not None:
            await self.caller(json.dumps(response))

    
    async def broadcast_scrape_finished(self, element: str):
        response = {
            'message': 'scrape status',
            'payload': element
        }
        if self.caller is not None:
            await self.caller(json.dumps(response))


    def send_to_telegram(self, element):
        #https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hello%20World
        message = self.__formating_element(element)
        apiURL = f'https://api.telegram.org/bot{apiToken}/sendMessage'

        try:
            requests.post(apiURL, json={'chat_id': chatID, 'parse_mode': 'html', 'text': message})
        except Exception as e:
            print(e)
    
    def __formating_element(self, element):
        search_term = element['search_term']
        title = element['title']
        url = element['url']
        price = element['price']
        datetime = element['datetime']
        return f'<strong>{search_term}</strong>\n<a href="{url}">{title}</a>\nPrice: ${price} mxn\nTime: {datetime}'


if __name__ == '__main__':
    scraper = Scrapper()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(scraper.scrape())
    except KeyboardInterrupt:
        pass