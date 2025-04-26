import unittest

from NFTorrent.storage import (TonStorageCli, TonStorageCliSettings,
                               TonStorageLru, parse_bag_id)


def settings(test_case: str):
    return TonStorageCliSettings(
        storage_cli_binary='./test/storage-daemon-cli',
        storage_daemon_addr=test_case,
        storage_db_path="/storage-db",
        request_timeout=0.1,
        manifest_bag_id='A8C27C0AF2BB3A3077330F1857C3130F6EBEEE5BD5347A18F1A4CCD30D4F5F82',
        storage_public_addr='192.168.1.10'
    )


class TestTonStorageCli(unittest.TestCase):

    def test_parse_bag_id(self):
        base64 = '9w0vdYfb39CSjhlnoLJ4PsOr1jhGrsOwVbRwWu90KHE='
        hex = 'F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'

        self.assertEqual(parse_bag_id(bytes.fromhex(hex)), hex)
        self.assertEqual(parse_bag_id(hex), hex)
        self.assertEqual(parse_bag_id(base64), hex)
        self.assertEqual(parse_bag_id(int(hex, 16)), hex)
        try:
            parse_bag_id('9w0vdYfb39CSjhlnoLJ4PsOr1jhGrsOwVbRwWu90KHE+++=')
        except Exception as E:
            self.assertIsInstance(E, ValueError)

    def test_open_error(self):
        cli = TonStorageCli(1, settings('err1'))
        self.assertFalse(cli.open())
        self.assertFalse(cli.is_alive())

    def test_open_timeout(self):
        cli = TonStorageCli(1, settings('err2'))
        self.assertFalse(cli.open())
        self.assertFalse(cli.is_alive())

    def test_open(self):
        cli = TonStorageCli(1, settings('connect'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_list(self):
        cli = TonStorageCli(1, settings('list'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_list()
        self.assertEqual(result, {
            '@type': 'storage.daemon.torrentList',
            'torrents': [
                {
                    '@type': 'storage.daemon.torrent',
                    'hash': 'qMJ8CvK7OjB3Mw8YV8MTD26+7lvVNHoY8aTM0w1PX4I=',
                    'flags': 3,
                    'total_size': '52',
                    'description': '4c48d157-56fc-5487-b8a5-2e331c2e7e11',
                    'files_count': '1',
                    'included_size': '52',
                    'dir_name': '',
                    'downloaded_size': '52',
                    'added_at': 1742716306,
                    'root_dir': '/storage-db/torrent/torrent-files/A8C27C0AF2BB3A3077330F1857C3130F6EBEEE5BD5347A18F1A4CCD30D4F5F82',  # noqa: E501
                    'active_download': True,
                    'active_upload': True,
                    'completed': True,
                    'download_speed': 0.0,
                    'upload_speed': 0.0,
                    'fatal_error': ''}
                ]
            })
        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_add(self):
        cli = TonStorageCli(1, settings('add'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
        self.assertEqual(result, {
            '@type': 'storage.daemon.torrentFull',
            'torrent': {
                '@type': 'storage.daemon.torrent',
                'hash': '9w0vdYfb39CSjhlnoLJ4PsOr1jhGrsOwVbRwWu90KHE=',
                'total_size': '0',
                'description': '',
                'files_count': '0',
                'included_size': '0',
                'dir_name': '',
                'downloaded_size': '0',
                'added_at': 1742742578,
                'root_dir': '/storage-db/torrent/torrent-files/F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871',  # noqa: E501
                'active_download': True,
                'active_upload': True,
                'completed': False,
                'download_speed': 0.0,
                'upload_speed': 0.0,
                'fatal_error': ''
            },
            'files': []
        })

        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_add_duplicate(self):
        cli = TonStorageCli(1, settings('adderr'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
        self.assertEqual(result, {'error': 'Query error: Cannot add torrent: duplicate hash F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'})  # noqa: E501
        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_get_peers(self):
        cli = TonStorageCli(1, settings('get-peers'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_get_peers('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
        self.assertEqual(result, {
            '@type': 'storage.daemon.peerList',
            'peers': [
                {
                    '@type': 'storage.daemon.peer',
                    'adnl_id': 'kGYfhI+5d44+27ZKj3Z0nAwTtV3alffz+d32DMx9vGk=',
                    'ip_str': '82.148.29.191:3333',
                    'download_speed': 0.0,
                    'upload_speed': 0.0,
                    'ready_parts': '13'
                }
            ],
            'download_speed': 0.0,
            'upload_speed': 0.0,
            'total_parts': '13'
        })

        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_remove(self):
        cli = TonStorageCli(1, settings('remove'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
        self.assertEqual(result, {'message': 'Success'})

        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_remove_not_exists(self):
        cli = TonStorageCli(1, settings('removeerr'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
        self.assertEqual(result, {'error': 'Query error: No such torrent'})

        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_create(self):
        cli = TonStorageCli(1, settings('create'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_create("C:/Work/ton-storage/file1.txt",
                                {"nft_address": "kQDggbH8_-FjQOjYgh96uSlZpImO02o9cBberv3BQRfcw7mH"},
                                copy=True, check_existance=False)
        self.assertEqual(result, {
            '@type': 'storage.daemon.torrentFull',
            'torrent': {
                '@type': 'storage.daemon.torrent',
                'hash': 'D65uMOy1/Z0xC6lB3osgq2txYSN9Cy08tx8nyJXAFEk=',
                'flags': 3,
                'total_size': '61',
                'description': '{"nft_address": "kQDggbH8_-FjQOjYgh96uSlZpImO02o9cBberv3BQRfcw7mH"}',
                'files_count': '1',
                'included_size': '61',
                'dir_name': '',
                'downloaded_size': '61',
                'added_at': 1742743853,
                'root_dir': '/storage-db/torrent/torrent-files/0FAE6E30ECB5FD9D310BA941DE8B20AB6B7161237D0B2D3CB71F27C895C01449',  # noqa: E501
                'active_download': False,
                'active_upload': True,
                'completed': True,
                'download_speed': 0.0,
                'upload_speed': 0.0,
                'fatal_error': ''
            },
            'files': [
                {
                    '@type': 'storage.daemon.fileInfo',
                    'name': 'file1.txt',
                    'size': '4',
                    'priority': 1,
                    'downloaded_size': '4'
                }
            ]
        })
        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())

    def test_create_exists(self):
        cli = TonStorageCli(1, settings('createerr'))
        self.assertTrue(cli.open())
        self.assertTrue(cli.is_alive())

        result = cli.cmd_create("C:/Work/ton-storage/file1.txt",
                                {"nft_address": "kQDggbH8_-FjQOjYgh96uSlZpImO02o9cBberv3BQRfcw7mH"},
                                copy=True, check_existance=False)
        self.assertEqual(result, {
            'error': 'Query error: File "C:\\Work\\ton-storage\\file10.txt" can\'t be opened for reading for stat'
        })
        self.assertTrue(cli.is_alive())

        cli.close()
        self.assertFalse(cli.is_alive())


class TestTonStorageLru(unittest.TestCase):

    def test_iterator(self):
        lru = TonStorageLru()
        lru.upsert(1, 10)
        lru.upsert(2, 20)
        lru.upsert(3, 30)
        lru.upsert(4, 40)
        self.assertEqual(list(lru), [(1, 10), (2, 20), (3, 30), (4, 40)])

        it = iter(lru)
        self.assertEqual(next(it), (1, 10))

        lru.remove(2)
        self.assertEqual(next(it), (3, 30))

        lru.remove(4)
        try:
            next(it)
            self.assertTrue(False)
        except Exception as E:
            self.assertIsInstance(E, StopIteration)

    def test_lru(self):
        lru = TonStorageLru()

        lru.remove(1)
        self.assertEqual(lru.size, 0)

        lru.upsert(1, 10)
        self.assertEqual(lru.size, 1)
        self.assertEqual(list(lru), [(1, 10)])

        lru.upsert(2, 20)
        self.assertEqual(lru.size, 2)
        self.assertEqual(list(lru), [(1, 10), (2, 20)])

        lru.upsert(3, 30)
        self.assertEqual(lru.size, 3)
        self.assertEqual(list(lru), [(1, 10), (2, 20), (3, 30)])

        lru.upsert(3, 31)
        self.assertEqual(lru.size, 3)
        self.assertEqual(list(lru), [(1, 10), (2, 20), (3, 31)])

        lru.upsert(1, 11)
        self.assertEqual(lru.size, 3)
        self.assertEqual(list(lru), [(2, 20), (3, 31), (1, 11)])

        lru.upsert(3, 32)
        self.assertEqual(lru.size, 3)
        self.assertEqual(list(lru), [(2, 20), (1, 11), (3, 32)])

        lru.remove(1)
        self.assertEqual(lru.size, 2)
        self.assertEqual(list(lru), [(2, 20), (3, 32)])

        lru.remove(2)
        self.assertEqual(lru.size, 1)
        self.assertEqual(list(lru), [(3, 32)])

        self.assertEqual(lru.upsert_back(3, 33), False)
        self.assertEqual(lru.size, 1)
        self.assertEqual(list(lru), [(3, 32)])

        self.assertEqual(lru.upsert_back(4, 40), True)
        self.assertEqual(lru.size, 2)
        self.assertEqual(list(lru), [(4, 40), (3, 32)])

        lru.remove_back()
        self.assertEqual(lru.size, 1)
        self.assertEqual(list(lru), [(3, 32)])

        lru.remove(3)
        self.assertEqual(lru.size, 0)
        self.assertEqual(list(lru), [])
