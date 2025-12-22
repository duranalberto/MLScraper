import random

# Curated list of modern User-Agents (Chrome, Firefox, Safari on Windows/Mac/Linux)
USER_AGENTS = [
    # Windows Chrome
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'platform': '"Windows"',
        'sec_ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
    },
    # Windows Firefox
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'platform': '"Windows"',
        'sec_ua': None  # Firefox doesn't always send sec-ch-ua
    },
    # Mac Chrome
    {
        'ua': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'platform': '"macOS"',
        'sec_ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
    },
    # Mac Safari
    {
        'ua': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'platform': '"macOS"',
        'sec_ua': None
    },
    # Linux Chrome
    {
        'ua': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'platform': '"Linux"',
        'sec_ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
    }
]

def get_random_header() -> dict:
    """Generates a coherent random header set."""
    profile = random.choice(USER_AGENTS)
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': profile['ua'],
    }

    # Add Sec-CH-UA headers if the browser supports them (mostly Chromium based)
    if profile['sec_ua']:
        headers['Sec-CH-UA'] = profile['sec_ua']
        headers['Sec-CH-UA-Mobile'] = '?0'
        headers['Sec-CH-UA-Platform'] = profile['platform']

    return headers