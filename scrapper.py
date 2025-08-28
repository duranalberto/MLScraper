import asyncio
import logging
from json import dumps as json_dumps
from time import time
from typing import Optional, Callable, Any

from provider.generator import get_motors
from scraper.motor import Motor
from utils.telegram import send_new_to_telegram, send_price_drop_to_telegram

# Setup basic logging for visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Scrapper:
    def __init__(self, caller: Optional[Callable] = None):
        self.sleep_time = 400
        self.motors: list[Motor] = get_motors()
        self.caller = caller

    def get_list(self) -> list[dict]:
        """Returns a snapshot of current active elements."""
        return [
            {'title': motor.search_term, 'elements': motor.active.get_list()} 
            for motor in self.motors
        ]

    async def run(self):
        """Main loop for the scraper."""
        logging.info("Scraper service started.")
        while True:
            start_time = time()
            
            try:
                # Run all motor scrapes concurrently
                tasks = [
                    motor.scrape(caller=self._broadcast, silent=True) 
                    for motor in self.motors
                ]
                await asyncio.gather(*tasks)
                
                duration = time() - start_time
                status_msg = f"Scraping cycle finished in {duration:.2f} seconds."
                logging.info(status_msg)
                await self._broadcast_scrape_finished(status_msg)
                
            except Exception as e:
                logging.error(f"Error during scraping cycle: {e}")

            await asyncio.sleep(self.sleep_time)

    async def _broadcast(self, broadcast_type: str, element: dict, msj: str = '', broadcast: bool = False):
        """Routes broadcast events to specific handlers."""
        if broadcast:
            return
            
        if broadcast_type == 'new_element':
            await self._broadcast_new_element(element)
        elif broadcast_type == 'is_updated':
            await self._broadcast_is_updated(element)

    async def _broadcast_new_element(self, element: dict):
        """Handles notification for brand new elements found."""
        response = {'message': 'new element', 'payload': element}
        send_new_to_telegram(element)
        if self.caller:
            await self.caller(json_dumps(response))

    def _parse_price(self, price_val: Any) -> float:
        """Helper to safely convert price strings/numbers to float."""
        if isinstance(price_val, (int, float)):
            return float(price_val)
        if isinstance(price_val, str):
            return float(price_val.replace(',', ''))
        return 0.0

    async def _broadcast_is_updated(self, element: dict):
        """Logic to handle price drops or data updates."""
        history = element.get('history', [])
        
        if not history or 'price' not in history[0]:
            return

        last_value = self._parse_price(history[0]['price'])
        new_value = self._parse_price(element.get('price', 0))

        if last_value <= 0:
            return

        percent_change = ((new_value - last_value) / abs(last_value)) * 100

        # Notify only if price dropped by 14% or more
        if percent_change <= -14:
            element['percent_change'] = f"{abs(percent_change):.2f}"
            logging.info(f"PRICE DROP: {element['title']} ({element['percent_change']}%) - {element.get('url')}")
            
            send_price_drop_to_telegram(element)
            
            if self.caller:
                await self.caller(json_dumps({'message': 'price drop', 'payload': element}))

    async def _broadcast_scrape_finished(self, status_text: str):
        """Notifies caller that a full cycle is complete."""
        if self.caller:
            response = {'message': 'scrape status', 'payload': status_text}
            await self.caller(json_dumps(response))


if __name__ == '__main__':
    scraper = Scrapper()
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        logging.info("Scraper stopped by user.")