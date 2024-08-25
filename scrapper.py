import asyncio
from json import dumps as json_dumps
from time import time

from provider.generator import get_motors
from scraper.motor import Motor
from utils.telegram import send_new_to_telegram, send_price_drop_to_telegram

class Scrapper:
    def __init__(self, caller = None):
        self.sleep_time = 900
        self.motors: list[Motor] = get_motors()
        self.caller = caller

    def get_list(self):
        return [{'title':element.search_term,'elements':element.active.get_list()} for element in self.motors]


    async def run(self):
        while True:
            start_time = time()
            tasks = []

            for motor in self.motors:
                task = asyncio.create_task(motor.scrape(caller = self._broadcast, silent = True))
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            time_difference = time() - start_time
            await self._broadcast_scrape_finished(f'Scraping time: %.2f seconds.' % time_difference)
            await asyncio.sleep(self.sleep_time)


    async def _broadcast(self, broadcast_type: str, element: dict, msj: str = ''):
        if False:
            return
        if broadcast_type == 'new_element':
            await self._broadcast_new_element(element)
        elif broadcast_type == 'is_updated':
            await self._broadcast_is_updated(element)

    async def _broadcast_new_element(self, element: dict):
        response = {
            'message': 'new element',
            'payload': element
        }
        send_new_to_telegram(element)
        if self.caller:
            await self.caller(json_dumps(response))


    #TODO Simplify the element dict
    async def _broadcast_is_updated(self, element: dict):
        if('history' not in element):
            print(str(element))
        if(not 'price' in element['history'][0]):
            return

        last_value = element['history'][0]['price']
        if isinstance(last_value, str):
            last_value = float(last_value.replace(',', ''))

        new_value = element['price']
        if isinstance(new_value, str):
            new_value = float(new_value.replace(',', ''))

        percent_change = ((new_value - last_value) / abs(last_value)) * 100

        if percent_change <= -14:
            element['percent_change'] = format(abs(percent_change),'.2f')
            print(element['url'] + '\nPrice of ' + element['title'] + ' - ' +  ' decresed by: ' + element['percent_change'])
            send_price_drop_to_telegram(element)


    async def _broadcast_scrape_finished(self, element: str):
        response = {
            'message': 'scrape status',
            'payload': element
        }
        if self.caller:
            await self.caller(json_dumps(response))


if __name__ == '__main__':
    scraper = Scrapper()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(scraper.run())
    except KeyboardInterrupt:
        pass