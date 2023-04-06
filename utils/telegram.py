from requests import post

from .secret import apiToken, chatID

def send_to_telegram(element: dict()):
    #https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hello%20World
    message = __formating_element(element)
    apiURL = f'https://api.telegram.org/bot{apiToken}/sendMessage'

    try:
        post(apiURL, json={'chat_id': chatID, 'parse_mode': 'html', 'text': message})
    except Exception as e:
        print(e)


def __formating_element(element: dict()):
    search_term = element['search_term']
    title = element['title']
    url = element['url']
    price = element['price']
    datetime = element['datetime']
    return f'<strong>{search_term}</strong>\n<a href="{url}">{title}</a>\nPrice: ${price} mxn\nTime: {datetime}'