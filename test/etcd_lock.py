import asyncio
from concurrent.futures import ThreadPoolExecutor

import etcd3

from NFTorrent.indexer.indexdb import EtcdPoolLock

lock_name = "mylock-123"


def main():

    async def __lock():
        etcdclient = etcd3.client(
            host="172.16.1.1",
            port=2379,
            ca_cert="./ansible/inventory/certs/pgcluster/ca.crt",
            cert_cert="./ansible/inventory/certs/pgcluster/client.crt",
            cert_key="./ansible/inventory/certs/pgcluster/client.key",
            timeout=10,
        )

        async with EtcdPoolLock(lock_name, [etcdclient], ThreadPoolExecutor(max_workers=2), lock_ttl=10) as lock:
            print(f'Lock "{lock_name}" acquired, uuid: {lock._lock.ttl}')

            lease_info = await lock.lease_info()
            await asyncio.sleep(5)
            await lock.refresh()
            print(f'!!! Lock "{lock_name}" refreshed')
            await asyncio.sleep(15)
            await lock.refresh_loop()

    asyncio.run(__lock())


main()
