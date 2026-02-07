TON NFT Torrent HTTP Gateway
============================
![Pets Memorial banner](/assets/images/git-readme-banner.png "Pets Memorial")

HTTP API gateway for accessing and managing off-chain NFT content in the TON ecosystem.

Provides following HTTP API Gateway feratures:
* Retrieve NFT `individual_content` metadata for supported collections
* Read and write off-chain files referenced by NFT IPFS URIs
* Store and distribute content with IPFS-backed storage
* Maintain off-chain data redundancy, availability, and pinning policies for reliable persistence
* NFT metadata indexing
* telegram bot


Parts of the LiteServer communication layer are derived from the
[ton-http-api](https://github.com/toncenter/ton-http-api) project, with substantial refactoring and improvements tailored to this gateway’s architecture and workload.


NFTorrent Application Architecture:

![NFTorrent Application Architecture](./assets/images/NFTorrent-Architecture.png "NFTorrent Application Architecture").

---

**Mainnet Website:** [https://petsmem.site](https://petsmem.site)

**Mainnet Contract:** [EQBSsYn6y560LVuVf3UYOnKUfH7Fexfk4iXtkA2TPl-CUsa6](https://tonviewer.com/EQBSsYn6y560LVuVf3UYOnKUfH7Fexfk4iXtkA2TPl-CUsa6)

**Testnet Contract:** [EQD7HAmDSSxSXJNhAWod8suE-_W0iwlC9o_OUR76kXo3jrtD](https://testnet.tonviewer.com/EQD7HAmDSSxSXJNhAWod8suE-_W0iwlC9o_OUR76kXo3jrtD)

**Collection on Getgems:** [@petsmem](https://getgems.io/petsmem)

**Docker Image:** [dtec/nft-torrent](https://hub.docker.com/r/dtec/nft-torrent)

---

**Linked repositories:**
- [Pets Memorial NFT Collection on TON](https://github.com/xeronm/pets-memorial)
- [Pets Memorial Web/Mini-App](https://github.com/noobel/pets-memorial-miniapp)

---


Feel free to support me with TON: `UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh`

![Wallet UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh QR code](/assets/images/UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh.PNG "UQDJJHWJKrt7ZKiRzXz2TpzJMxJ5RrWffTqXL8769EXa_2bh")


### Getting Started

#### Build Docker image
```sh
pip intsall tox tox-docker
tox -e build
tox -e image
```

#### Deploy via Docker Compose

1. Create user
```sh
sudo groupadd -r nftorrent --gid=9001
sudo useradd -r -g nftorrent --uid=9001 --home-dir=/home/nftorrent --shell=/sbin/nologin nftorrent
```

2. Setup application directory
- create `ton_keystore` path
- create `storage-db` or `ipfs-db` path
- create `uploads` temporary path `mkdir /tmp/uploads`
- setup environment variables `.env`
- create `private` sub-directory, and place:
    - TON configuration, e.g. `wget https://ton.org/testnet-global-config.json`
    - generate `jwt.key` - JWT secret key for Bearer Authorization
    - TON Storage: create `storage.manifest` - BAG ID of the torrent to locate NFT Storage Peers


3. Run docker-compose
```sh
docker compose up -d
```

### Annex A. Localization

```sh
pybabel extract -F babel.cfg -o NFTorrent/locales/messages.pot .
pybabel update -i NFTorrent/locales/messages.pot -d NFTorrent/locales -l ru
pybabel compile -d NFTorrent/locales
```