from requests import post

from .secret import apiToken, chatID

#https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hello%20World
apiURL = f'https://api.telegram.org/bot{apiToken}/sendMessage'

def send_new_to_telegram(element: dict):
    message = __formating_new(element)
    _send_to_telegram(message)

    

def send_price_drop_to_telegram(element: dict):
    message = __formating_price_drop(element)
    _send_to_telegram(message)


def _send_to_telegram(message):
    try:
        post(apiURL, json={'chat_id': chatID, 'parse_mode': 'html', 'text': message})
    except Exception as e:
        print(e)


def __formating_new(element: dict):
    search_term = element['search_term']
    title = element['title']
    url = element['url']
    price = element['price']
    datetime = element['datetime']
    return f'<strong>{search_term}</strong>\n<a href="{url}">{title}</a>\nPrice: ${price} mxn\nTime: {datetime}'


def __formating_price_drop(element: dict):
    if not'percent_change' in element or not element['percent_change']:
        return
    search_term = element['search_term']
    title = element['title']
    url = element['url']
    price = element['price']
    percent_change = element['percent_change']
    last_price = element['history'][0]['price']
    datetime = element['history'][0]['datetime']
    return f'<strong>Price Update</strong>\n<strong>{search_term}</strong>\n<a href="{url}">{title}</a>'\
            f'\nOld price: ${last_price}\n<strong>New Price: ${price} mxn</strong>'\
            f'\nPrice decresed by %{percent_change}\nUpated: {datetime}'