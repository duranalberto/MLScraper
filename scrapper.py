import asyncio
from json import dumps as json_dumps
from time import time
from requests import post

from provider.generator import get_motors
from scraper.motor import Motor

from utils.secret import apiToken, chatID

class Scrapper:
    def __init__(self, caller = None):
        self.sleep_time = 50
        self.motors: list[Motor] = get_motors()
        self.caller = caller

    def get_list(self):
        return [{'title':element.search_term,'elements':element.active.get_list()} for element in self.motors]


    async def run(self):
        while True:
            start_time = time()
            tasks = []

            for motor in self.motors:
                task = asyncio.create_task(motor.scrape(caller = self.broadcast_new_element, silent = True))
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            time_difference = time() - start_time
            await self.broadcast_scrape_finished(f'Scraping time: %.2f seconds.' % time_difference)
            await asyncio.sleep(self.sleep_time)


    async def broadcast_new_element(self, element):
        response = {
            'message': 'new element',
            'payload': element
        }
        self.send_to_telegram(element)
        if self.caller is not None:
            await self.caller(json_dumps(response))


    async def broadcast_scrape_finished(self, element: str):
        response = {
            'message': 'scrape status',
            'payload': element
        }
        if self.caller is not None:
            await self.caller(json_dumps(response))


    def send_to_telegram(self, element):
        #https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hello%20World
        message = self.__formating_element(element)
        apiURL = f'https://api.telegram.org/bot{apiToken}/sendMessage'

        try:
            post(apiURL, json={'chat_id': chatID, 'parse_mode': 'html', 'text': message})
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
        loop.run_until_complete(scraper.run())
    except KeyboardInterrupt:
        pass