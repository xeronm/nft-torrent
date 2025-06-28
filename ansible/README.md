### Activate SSH key

```sh
ssh-agent bash
ssh-add ~/.ssh/<private key>
```

### Setup Inventory and Variables

#### Generate password and secrets

- pg passwords: `openssl rand -base64 18`
- secrets (JWT key, IPFS Cluster): `openssl rand -hex 32`

#### Generate Self-signed Certificates for PG-Cluster

```sh
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=Patroni Root CA"
```

#### Setup Inventory

```yaml
# ./inventory/production.yaml
nftorrents:
  hosts:
    n01.s.petsmem.site:
      ansible_host: 80.249.146.167
```

#### Setup Group Variables

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
    NFTORRENT_VERSION: 0.2.1
    HTTP_TWA_DOMAINS: ton-connect.github.io, petsmem.site
    HTTP_ALLOW_ORIGINS: http://localhost:9000, https://petsmem.site
  ton_config: https://ton.org/testnet-global-config.json
  jwt_key: <32byte hexencoded JWT secret>
  ipfs:
    peerstore:
      - <IPFS bootstrap peer record 1>
      - <IPFS bootstrap peer record 2>
website:
  package: <pet-memorial-miniapp build package>
```

### Deploy
```sh
ansible-playbook -i ./inventory/production.yaml nftorrents.yaml
```

Check Geo-routing
```sh
curl -i https://www.petsmem.site/ --resolve www.petsmem.site:443:45.144.222.100
```


### Certificates Master-host Setup

Configure Master-Host and obtain ceritificate

Setup properly:
  - DNS Credentials `/etc/letsencrypt/<plugin>.ini`;
  - Deploy hook `/etc/letsencrypt/renewal/<domain>`;

```sh
pip3 install ansible certbot
certbot certonly -a dns -d <domain> -d *.<domain> --dns-propagation-seconds 300
certbot renew --dry-run
```
