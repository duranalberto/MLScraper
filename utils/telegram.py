from requests import post

from .secret import apiToken, chatID

# https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hello%20World
apiURL = f'https://api.telegram.org/bot{apiToken}/sendMessage'

def send_new_to_telegram(element: dict):
    """Send notification for new item listing."""
    message = __format_new_item(element)
    _send_to_telegram(message)

    
def send_price_drop_to_telegram(element: dict):
    """Send notification for price drop."""
    message = __format_price_drop(element)
    if message:  # Only send if message was formatted successfully
        _send_to_telegram(message)


def _send_to_telegram(message: str):
    """Send formatted message to Telegram chat."""
    try:
        response = post(
            apiURL, 
            json={
                'chat_id': chatID, 
                'parse_mode': 'html', 
                'text': message,
                'disable_web_page_preview': False
            }
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Error sending Telegram message: {e}")


def __format_new_item(element: dict) -> str:
    """Format new item notification with appealing styling."""
    search_term = element.get('search_term', 'New Item')
    title = element.get('title', 'Untitled')
    url = element.get('url', '')
    price = element.get('price', 0)
    datetime = element.get('datetime', 'Unknown')
    
    return (
        f"🆕 <b>NEW LISTING</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 <b>{search_term}</b>\n\n"
        f"<a href=\"{url}\">{title}</a>\n\n"
        f"💰 <b>${price:,.2f} MXN</b>\n"
        f"🕒 {datetime}"
    )


def __format_price_drop(element: dict) -> str:
    """Format price drop notification with appealing styling."""
    if 'percent_change' not in element or not element['percent_change']:
        return None
    
    search_term = element.get('search_term', 'Item')
    title = element.get('title', 'Untitled')
    url = element.get('url', '')
    price = element.get('price', 0)
    percent_change = abs(element.get('percent_change', 0))
    
    history = element.get('history', [{}])
    last_price = history[0].get('price', 0) if history else 0
    datetime = history[0].get('datetime', 'Unknown') if history else 'Unknown'
    
    savings = last_price - price
    
    return (
        f"🔥 <b>PRICE DROP ALERT!</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 <b>{search_term}</b>\n\n"
        f"<a href=\"{url}\">{title}</a>\n\n"
        f"<s>${last_price:,.2f}</s> ➜ <b>${price:,.2f} MXN</b>\n"
        f"💸 Save ${savings:,.2f} ({percent_change:.1f}% OFF)\n\n"
        f"🕒 Updated: {datetime}"
    )