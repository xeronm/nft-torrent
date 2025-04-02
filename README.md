TON NFT Torrent HTTP Gateway
============================

Provides following HTTP API Gateway functions:
- read NFT `individual_content` data for known NFT collections
- read/write refrenced by NFT BAG ID off-chain NFT files from Torrent maintained with TON Storage
- maintain Torrent redundacy policy
- keep storage limits by cleaning non-pinned Torrents by LRU policy 

NFT Contract example: https://github.com/xeronm/pets-memorial

Feel free to support me with TON: UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh

![Wallet UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh QR code](/assets/images/UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh.PNG "UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh")


### Getting Started

1. Build Docker image
```sh
pip intsall tox
tox -e build
tox -e image
```

2. Create user
```sh
sudo groupadd -r nftorrent --gid=9001
sudo useradd -r -g nftorrent --uid=9001 --home-dir=/home/nftorrent --shell=/sbin/nologin nftorrent
```

3. Setup application directory
- create `storage-db` path
- setup environment variables `.env`
- create `private` sub-directory, and place:
    - TON configuration, e.g. `wget https://ton.org/testnet-global-config.json`
    - create `storage.manifest` - BAG ID of the torrent to locate NFT Storage Peers
    - generate `jwt.key` - JWT secret key for Bearer Authorization

4. Run docker-compose
```sh
docker compose up -d
```

5. Create 