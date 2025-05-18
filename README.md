TON NFT Torrent HTTP Gateway
============================

Provides following HTTP API Gateway functions:
- read NFT `individual_content` data for known NFT collections
- read/write refrenced by NFT BAG ID off-chain NFT files from Torrent maintained with TON Storage and/or IPFS
- TON Storage: maintain Torrent redundacy policy
- TON Storage: keep storage limits by cleaning non-pinned Torrents by LRU policy

NFT Contract example: https://github.com/xeronm/pets-memorial

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

#### Deploy via Ansible

1. Activate SSH key

```sh
ssh-agent bash
ssh-add ~/.ssh/<private key>
```

2. Setup Inventory and Global Vars

```yaml
# ./inventory/production.yaml
nftorrents:
  hosts:
    n01.s.petsmem.site:
      ansible_host: 80.249.146.167
```


```yaml
# ./group_vars/all.yaml
oam:
  user: nftorrent
  group: nftorrent
  comment: NF Torrent
  uid: 9001
  gid: 9001
  sshkey: <ssh-rsa>
  telegraf:
    influxdb:
      token: <InfluxDB Output Token>
      urls:
        - <InfluxDB Output URLs>
      bucket: petsmem
      organization: petsmem
```

```yaml
# ./group_vars/nftorrents.yaml
nftorrent:
  collections:
    - address: EQCq3q4Oi6nxLGA399SXlUv6XR8sAECm_TPIl-kZRY6rvIvc
      image: './assets/images/collection-3.webp'
  environment:
    IPFS_CLUSTER_SECRET: <32byte hexencoded cluster secret>
    IPFS_CLUSTER_PEERNAME: "{{ inventory_hostname }}"
    NFTORRENT_VERSION: 0.2.0
    HTTP_TWA_DOMAINS: ton-connect.github.io, petsmem.site
    HTTP_ALLOW_ORIGINS: http://localhost:9000, https://petsmem.site
  ton_config: https://ton.org/testnet-global-config.json
  jwt_key: <32byte hexencoded JWT secret>
  ipfs:
    peerstore:
      - <IPFS bootstrap peer record 1>
      - <IPFS bootstrap peer record 2>
website:
  html: <pet-memorial-miniapp build path>
```

3. Deploy
```sh
ansible-playbook -i ./inventory/production.yaml nftorrents.yaml
```