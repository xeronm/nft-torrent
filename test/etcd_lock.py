import asyncio
import etcd3
from concurrent.futures import ThreadPoolExecutor

from NFTorrent.indexer.indexdb import EtcdPoolLock

lock_name = "bot_polling"

def main():

    async def __lock():
        etcdclient = etcd3.client(
            host='172.16.1.1',
            port=2379,
            ca_cert='./ansible/inventory/certs/pgcluster/ca.crt',
            cert_cert='./ansible/inventory/certs/pgcluster/client.crt',
            cert_key='./ansible/inventory/certs/pgcluster/client.key',
            timeout=10,
        )


        async with EtcdPoolLock(lock_name, [etcdclient], ThreadPoolExecutor(max_workers=2)) as lock:
            print(f'Lock "{lock_name}" acquired')

            while True:
                await asyncio.sleep(30)
                await lock.refresh()
                print(f'Lock "{lock_name}" refreshed')


    asyncio.run(__lock())


main()