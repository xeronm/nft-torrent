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

#### OpenDKIM Certificates

```sh
opendkim-genkey -b 2048 -h rsa-sha256 -r -s mail -d petsmem.site -v -D ./files/certs/opendkim/<domain>
```


#### Setup Inventory

```yaml
# ./inventory/main.yaml
nftorrents:
  hosts:
    n01-ru-petsmem:
      ansible_host: 45.144.222.100
    n01-eu-petsmem:
      ansible_host: 45.139.77.63
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
    NFTORRENT_VERSION: 0.2.3
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
ansible-playbook -i ./inventory nftorrents.yaml
```

Check Geo-routing
```sh
curl -i https://www.petsmem.site/ --resolve www.petsmem.site:443:45.144.222.100
```


### Certificates Master-host Setup

#### Setup ansible on Master-host

1. Clone repo

```sh
sudo pip3 install ansible
sudo git clone https://github.com/xeronm/nft-torrent.git /root
sudo mkdir -p /root/nft-torrent/ansible/inventory
sudo mkdir -p /root/nft-torrent/ansible/group_vars
```

2. Setup inventory

```yaml
# /root/nft-torrent/ansible/inventory/main.yaml
nftorrents:
  hosts:
    n01-ru-petsmem:
      ansible_host: 45.144.222.100
    n01-eu-petsmem:
      ansible_host: 45.139.77.63
```

```yaml
# /root/nft-torrent/ansible/group_vars/nftorrents.yaml
geoip:
  account_id: <account>
  license_key: <key>
  db_url: https://download.maxmind.com/geoip/databases/GeoLite2-Country/download?suffix=tar.gz
  sha_url: https://download.maxmind.com/geoip/databases/GeoLite2-Country/download?suffix=tar.gz.sha256
  local_path: ./geoipdb
  local_db: ./geoipdb/GeoLite2-Country.mmdb.tar.gz
```

3. Add SSH private key for deploy

```sh
sudo vi ~/.ssh/certbot_ansible_key
sudo chmod 0600 ~/.ssh/certbot_ansible_key
```

4. Test connection

```sh
sudo ansible -i ./nft-torrent/ansible/inventory all -m ansible.builtin.ping --private-key ~/.ssh/certbot_ansible_key
```

#### Configure Master-Host and obtain ceritificate

1. Setup DNS Credentials `/etc/letsencrypt/<plugin>.ini`;

```ini
dns_username=<username>
dns_password=<password>
```

2. Obtain certificate for the first time
```sh
sudo pip3 install certbot certbot-regru
sudo certbot certonly -a dns -d <domain> -d *.<domain> --dns-propagation-seconds 300
sudo certbot renew --dry-run
```

3. Setup Deploy hook `/etc/letsencrypt/renewal/<domain>`;

```conf
deploy_hook = /root/nft-torrent/ansible/deploy_pushcert.sh
```

4. Test hook

```sh
sudo RENEWED_LINEAGE=/etc/letsencrypt/live/<domain> /root/nft-torrent/ansible/deploy_pushcert.sh
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


### Appendix D. Enabling swap

1. Create and enable swapfile

```sh
sudo dd if=/dev/zero of=/swapfile count=1024 bs=1MiB
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

2. Add to `/etc/fstab` for persistense

```
/swapfile   swap    swap    sw  0   0
```

3. Edit `sysctl.conf`

```
vm.swappiness = 10
vm.vfs_cache_pressure = 80
```


### Appendix E. Test mailing system

```sh
echo "This is test for end user" | mail -s "Test subject" xeronm@gmail.com
echo "This is test for admin" | mail -s "Test subject" admin@petsmem.site
```