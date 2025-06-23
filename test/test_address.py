import base64
import binascii
import unittest

from NFTorrent.blockchain.address import adnl_id_decode, adnl_id_encode


class TestAdnl(unittest.TestCase):
    AndlId2Base64 = "kGYfhI+5d44+27ZKj3Z0nAwTtV3alffz+d32DMx9vGk="
    AdnlId2Encoded = "wigmh4er64xpdr63o3evd3wosoaye5vlxnjl57t7ho7mdgmpw6gtm3v"

    def test_adnl_encode(self):
        adnl_id = binascii.unhexlify("3D94F73794CA3C511C486574BB55A5B7F4F747A4E2ACA618479A77BC841111D1")
        adnl_enc = adnl_id_encode(adnl_id)
        self.assertEqual(adnl_enc, "u6zj5zxstfdyui4jbsxjo2vuw37j52hutrkzjqyi6nhppeecei5cjex")
        self.assertEqual(adnl_id_decode(adnl_enc), adnl_id)

        adnl_id = base64.b64decode("kGYfhI+5d44+27ZKj3Z0nAwTtV3alffz+d32DMx9vGk=")
        adnl_enc = adnl_id_encode(adnl_id)
        self.assertEqual(adnl_enc, "wigmh4er64xpdr63o3evd3wosoaye5vlxnjl57t7ho7mdgmpw6gtm3v")
