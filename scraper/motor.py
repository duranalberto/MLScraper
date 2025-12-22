import asyncio
from abc import ABC, abstractmethod
from aiohttp import ClientSession, ClientTimeout, ClientError
from json import dumps as json_dumps
from typing import Optional, Tuple, List, Callable, Any
from traceback import format_exc

from .stream import Stream
from .article import Article
from .status import Status

from utils.file_manager import read_json_file, write_in_file
from utils.headers import get_random_header

class Motor(ABC):
    def __init__(self, search_term: str, url: str, debug: bool = True):
        self.search_term = search_term
        self.url = url
        self.file_name = f"{search_term}.json"
        self.active = Stream(Status.active)
        self.finished = Stream(Status.finished)
        self.debug = debug
        
        # Load existing state
        self.load_from_file()

    async def _fetch(self, session: ClientSession, url: str, retries: int = 3) -> Optional[str]:
        """
        Helper: Fetches URL with retries and exponential backoff.
        Returns HTML string or None if failed.
        """
        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    elif resp.status in {404, 403, 500}:
                        # Stop retrying on fatal errors if necessary, 
                        # or continue if you want to force through 500s
                        if self.debug:
                            print(f"Status {resp.status} for {url}")
            except (ClientError, asyncio.TimeoutError):
                pass
            
            # Exponential backoff (0.5s, 1s, 2s...)
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
        
        return None

    async def scrape(self, caller: Optional[Callable] = None, silent: bool = False):
        """Scrapes the target URL and handles pagination and updates."""
        results = []
        current_url = self.url
        
        # Increased timeout for slower connections
        timeout = ClientTimeout(total=45)
        
        try:
            current_headers = get_random_header()
            async with ClientSession(headers=current_headers, timeout=timeout) as session:
                while current_url:
                    # 1. Reliable Fetch
                    html_content = await self._fetch(session, current_url)
                    
                    if not html_content:
                        if self.debug: print(f"Failed to fetch content for: {current_url}")
                        break

                    # 2. Scrape Page (Protected)
                    try:
                        body = {'content': html_content, 'url': current_url}
                        # Unpack safely
                        scrape_result = self.scrape_page(body)
                        items, next_page_url = scrape_result
                    except Exception as e:
                        print(f"Error parsing {current_url}: {e}")
                        if self.debug: print(format_exc())
                        break

                    # 3. Handle Empty/None Items safely (Your specific request)
                    if items is None:
                        items = []

                    if not silent:
                        print(f'Scraping {self.search_term} | Found: {len(items)} | Next: {"Yes" if next_page_url else "No"}')
                        if self.debug and len(items) > 0:
                            print(items[0]) # Print first item only to reduce noise
                    
                    # 4. Process Items
                    for item in items:
                        article, is_new, is_updated = self.save(item)
                        
                        if self.is_article(article):
                            results.append(article)
                            
                            # Broadcast updates
                            if caller and (is_new or is_updated):
                                b_type = 'new_element' if is_new else 'is_updated'
                                try:
                                    await caller(broadcast_type=b_type, element=article.dump())
                                except Exception:
                                    # Don't let a broadcast failure stop the scraper
                                    pass
                        current_url = next_page_url
                    else:
                        current_url = None

            # -------------------------------------------------
            # POST-PROCESSING
            # -------------------------------------------------
            if results or (not results and self.active.get_list()):
                if not silent:
                    print(f'Total articles recorded for {self.search_term}: {len(results)}')
                
                # Identify and move articles that are no longer present in the scrape
                deleted_articles = self.active - results
                for deleted in deleted_articles:
                    self.save(deleted, to_status=Status.finished)
                
                await self.save_to_file()
                
        except Exception:
            print(f"Scrape for {self.search_term} crashed critically!")
            if self.debug:
                print(format_exc())

    @abstractmethod
    def scrape_page(self, body: dict) -> Tuple[List[Any], Optional[str]]:
        """Must return a list of items and the URL for the next page (or None)."""
        pass

    def save(self, item: Any, to_status: Status = Status.none, at_beginning: bool = True) -> Tuple[Optional[Article], bool, bool]:
        """Handles the logic of moving articles between active and finished streams."""
        is_new = False
        is_updated = False
        
        # Robust check if item is already an object or raw dict
        article = item if self.is_article(item) else self.create_article(item)

        if not article:
            return None, False, False

        # Determine target status
        target_status = to_status if to_status != Status.none else (article.status or Status.active)

        if target_status == Status.active:
            # Check if it was previously 'finished'
            previously_finished = self.finished.delete(article)
            
            # If it's not in active, it's new
            if article not in self.active and previously_finished is None:
                self.active.add(article, at_beginning)
                is_new = True
            else:
                # Update existing data
                existing = previously_finished or article
                updated_article = self.active.update(existing)
                
                # Ensure update returned valid object
                if self.is_article(updated_article):
                    article = updated_article
                    is_updated = True
                    
        elif target_status == Status.finished:
            removed = self.active.delete(article)
            self.finished.add(removed or article)

        return article, is_new, is_updated

    def is_article(self, obj: Any) -> bool:
        return isinstance(obj, Article)

    def create_article(self, data: dict) -> Optional[Article]:
        try:
            return Article.create(data)
        except Exception:
            return None

    def load_from_file(self):
        """Initializes streams from local JSON storage."""
        json_array = read_json_file(self.file_name)
        if not json_array:
            return
            
        for data in json_array:
            if isinstance(data, dict):
                data['search_term'] = self.search_term
                self.save(data, at_beginning=False)

    async def save_to_file(self):
        """Persists all streams to disk."""
        self.active.order_by_time()
        self.finished.order_by_time()
        
        all_data = [a.dump() for a in self.get_all()]
        await write_in_file(self.file_name, json_dumps(all_data, indent=2))

    def get_all(self) -> Stream:
        return self.active + self.finished

    def print_compare(self):
        print(f'\nSummary for: {self.search_term}')
        print(f'Total in storage: {len(self.get_all())}')
        print(f'Currently Active: {len(self.active.get_list())}')
        print(f'Currently Finished: {len(self.finished.get_list())}')