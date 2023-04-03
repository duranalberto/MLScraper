from json import load as json_load

data_path = './data/'

def write_in_file_old(file_name: str, content: str):
    if file_name and content:
        with open(data_path + file_name, 'w') as file:
            file.write(content)

async def write_in_file(file_name: str, content: str):
    if file_name and content:
        with open(data_path + file_name, 'w') as file:
            file.write(content)

def read_json_file(file_name: str) -> list:
    data = ''
    try:
        with open(data_path + file_name) as file:
            data = json_load(file)
    except FileNotFoundError:
        print('File does not exist: ' + data_path + file_name)
    return data