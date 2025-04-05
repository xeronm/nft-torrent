import requests
import os

print(os.getcwd())

url = 'https://muratov.xyz/nftorrent/nft/EQAX3cFnhW2YljjDO6ZW2NNf8dCA2XWpZQEi0h_sh4YGhXMs/torrent'
files = [
    ('files', open('../pets-memorial/assets/images/marcus-1.jpg', 'rb')), 
    ('files', open('../pets-memorial/assets/images/marcus-2.jpg', 'rb')), 
    ('files', open('../pets-memorial/assets/images/marcus-3.jpg', 'rb')), 
    ('files', open('../pets-memorial/assets/images/marcus-4.jpg', 'rb')), 
]

resp = requests.post(url=url, files=files) 
print(resp.json())