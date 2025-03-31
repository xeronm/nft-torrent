TON NFT Torrent HTTP Gateway
============================

Provides following HTTP API Gateway functions:
- read NFT `individual_content` data for known NFT collections
- read/write refrenced by NFT BAG ID off-chain NFT files from Torrent maintained with TON Storage
- maintain Torrent redundacy policy
- keep storage limits by cleaning non-pinned Torrents by LRU policy 



### Getting Started

1. Build Docker image
```sh
$ pip intsall tox
$ tox -e image
```

2. Create user
```sh
$ sudo groupadd -r nftorrent --gid=9001
$ sudo useradd -r -g nftorrent --uid=9001 --home-dir=/home/nftorrent --shell=/sbin/nologin nftorrent
```

3. Setup application directory
- create `private` sub-directory, and place:
    - TON configuration, e.g. `wget https://ton.org/testnet-global-config.json`
    - `storage.manifest` with BAG ID
- setup environment variables `.env`

