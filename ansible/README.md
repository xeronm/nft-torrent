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
    NFTORRENT_VERSION: 0.2.2
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

```ini
dns_username=<username>
dns_password=<password>
```

  - Deploy hook `/etc/letsencrypt/renewal/<domain>`;

```conf
...
deploy_hook = /root/nft-torrent/ansible/deploy_pushcert.sh
```

```sh
pip3 install ansible certbot certbot-regru
certbot certonly -a dns -d <domain> -d *.<domain> --dns-propagation-seconds 300
certbot renew --dry-run
```


### Appendix A. SELinux enabling

Edit `/etc/selinux/config` and set `SELINUX=enforcing`

Update loader args

```sh
grubby --update-kernel ALL --remove-args selinux
```

Note: If you are switching from a disabled or permissive state to enforcing, you might need to relabel the file system during the reboot. This can be done by creating an empty file named .autorelabel in the root directory (/) before rebooting. This will trigger a full relabeling of the file system on the next boot.


### Appendix B. Etcd oeprations

1. Member list - `/etc/etcd/etcdctl.sh member list --write-out=table`
2. Member remove - `/etc/etcd/etcdctl.sh member remove <node-id>`
3. Member add - `/etc/etcd/etcdctl.sh  member add <node-name> --peer-urls=<advertise-peer-urls>`
4. Endpoint status - `/etc/etcd/etcdctl.sh --endpoints=<extra-enpoints>  endpoint status --write-out=table`
5. Endpoint health - `/etc/etcd/etcdctl.sh --endpoints=<extra-enpoints>  endpoint health --write-out=table`

### Appendix C. PG Cluster operations

1. Patroni status - `patronictl -c /etc/patroni/patroni.yaml list`