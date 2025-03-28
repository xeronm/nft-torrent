import requests
import os

print(os.getcwd())

url = 'http://127.0.0.1:8000/nft/EQD0r2Bq3wcO-_5oGtoawhc9D9lytRjt9w66QlODIQPyG5-U/torrent'
files = [
    ('files', open('../pets-memorial/assets/images/marcus-1.jpg', 'rb')), 
    ('files', open('../pets-memorial/assets/images/marcus-2.jpg', 'rb')), 
    ('files', open('../pets-memorial/assets/images/marcus-3.jpg', 'rb')), 
]

resp = requests.post(url=url, files=files) 
print(resp.json())