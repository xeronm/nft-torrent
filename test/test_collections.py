import unittest
from dataclasses import asdict

from tonpy.types import CellSlice

from NFTorrent.collections import PetMemoryNftContent, PetsCollectionInfo


class TestPetMemoryNftContent(unittest.TestCase):

    def test_collection_info(self):
        stack = [
            ["num", "0x2faf080"],
            ["num", "0x17d7840"],
            ["num", "0x2faf080"],
            ["num", "0x98ff19ed"],
            ["num", "0x36a6196d"],
            ["num", "0x62590080"],
            ["num", "0x1"],
            [
                "cell",
                {
                    "bytes": "te6cckEBAQEAGwAAMmh0dHBzOi8vcy5wZXRzbWVtLnNpdGUvYy///xQz",
                    "object": {
                        "data": {"b64": "aHR0cHM6Ly9zLnBldHNtZW0uc2l0ZS9jLw==", "len": 200},
                        "refs": [],
                        "special": False,
                    },
                },
            ],
        ]
        info = PetsCollectionInfo.from_tvm(stack)
        self.assertEqual(
            asdict(info),
            {
                "fee_storage": 0.05,
                "fee_class_a": 0.025,
                "fee_class_b": 0.05,
                "balance": 2.566855149,
                "balance_class_a": 0.916855149,
                "balance_class_b": 1.65,
                "fb_mode": 1,
                "fb_uri": "https://s.petsmem.site/c/",
                "minter": None
            },
        )

        stack2 = [
            [
                "cell",
                {
                    "bytes": "te6cckEBAQEAJAAAQ4AFLnPmwnbNoHULKyClAwao/XFezTimbOpgQmwTvV33ilDfQtHL",
                    "object": {
                        "data": {"b64": "gAUuc+bCds2gdQsrIKUDBqj9cV7NOKZs6mBCbBO9XfeKQA==", "len": 267},
                        "refs": [],
                        "special": False,
                    },
                },
            ],
            ["num", "0x2faf080"],
            ["num", "0x17d7840"],
            ["num", "0x2faf080"],
            ["num", "0x13cf0b7f2"],
            ["num", "0x52fdf8b2"],
            ["num", "0xe9f2bf40"],
            ["num", "0x5"],
            [
                "cell",
                {
                    "bytes": "te6cckEBAQEAGwAAMmh0dHBzOi8vcy5wZXRzbWVtLnNpdGUvYy///xQz",
                    "object": {
                        "data": {"b64": "aHR0cHM6Ly9zLnBldHNtZW0uc2l0ZS9jLw==", "len": 200},
                        "refs": [],
                        "special": False,
                    },
                },
            ],
        ]
        info2 = PetsCollectionInfo.from_tvm(stack2)
        self.assertEqual(
            asdict(info2),
            {
                "fee_storage": 0.05,
                "fee_class_a": 0.025,
                "fee_class_b": 0.05,
                "balance": 5.317375986,
                "balance_class_a": 1.392375986,
                "balance_class_b": 3.925,
                "fb_mode": 5,
                "fb_uri": "https://s.petsmem.site/c/",
                "minter": "EQApc582E7ZtA6hZWQUoGDVH64r2acUzZ1MCE2Cd6u-8Ug4Y"
            },
        )

    def test_content_image_url(self):
        content_boc = "te6cckECEAEAA6QAAQABAwEiAgMEAAxNYXJjdXMCIsjY0oAhsjdwzQAAAAAgJBEVBQYDCdqDZH2gBwgJABBOaWJlbHVuZwAgS3Jhc25vZGFyIDM1MDAyMACKaHR0cHM6Ly9zLmdldGdlbXMuaW8vbmZ0L2MvNjczOGU2MzMwMTAyZGM2ZmRlYmE5ZjI3LzEwMDAwMDAvbWV0YS5qc29uAf5IZSBhcHBlYXJlZCBpbiBvdXIgbGl2ZXMgb24gMDgvMTkvMjAyMy4gV2Ugbm90aWNlZCBoaW0gYSB3ZWVrIGVhcmxpZXIsIG9uIHRoZSB3YXkgdG8gdGhlIGd5bS4gQSBiaWcsIGdyYXkgY2F0LCB0aGluIGFzIGEgc2tlbGV0CgEBoA8B/m9uLCB3YXMgcnVubmluZyBvdXQgb2YgYW4gYWJhbmRvbmVkIHByaXZhdGUgaG91c2UsIGxvb2tlZCBhdCBwZW9wbGUgd2l0aCBwaWVyY2luZyBlbWVyYWxkIGV5ZXMsIGFuZCBzY3JlYW1lZC4gV2UgdHJpZWQgdG8gZmVlZCALAf5oaW0sIGJ1dCB0aGF0IGRheSBJIHJlYWxpemVkIHRoYXQgaWYgaGUgZGlkIG5vdCBydW4gb3V0IGF0IHNvbWUgZGF5LCBJIHdvdWxkIG5vdCBiZSBhYmxlIHRvIGZvcmdpdmUgbXlzZWxmLiBBbiBob3VyIGxhdGVyLCBteSB3DAH+aWZlIGFuZCBJIGNhdWdodCBoaW0uCkl0IHdhcyBhIGZvcm1lciBkb21lc3RpYywgbmV1dGVyZWQgY2F0LCAxMC0xMiB5ZWFycyBvbGQsIHdpdGggQ0tELiBUaGVuIHRoZXJlIHdlcmUgMTUgbW9udGhzIG9mIHN0cnVnZ2xlIA0B/mFuZCBqb3kgb2YgbGlmZSwgdXBzIGFuZCBkb3ducywgYW5kIGRvemVucyBvZiB2aXNpdHMgdG8gdmV0cy4gU2V2ZXJhbCB0aW1lcyB3ZSB0aG91Z2h0IHRoYXQgaGUgd291bGRuJ3QgZ2V0IG91dCwgYnV0IGhlIGhhZCBhbiAOAHRpcm9uIHdpbGwgdG8gbGl2ZS4gSG93ZXZlciwgb24gMTEvMTUvMjAyNCwgaGUgcGFzc2VkIGF3YXkuAIpodHRwczovL3MuZ2V0Z2Vtcy5pby9uZnQvYy82NzM4ZTYzMzAxMDJkYzZmZGViYTlmMjcvMTAwMDAwMC9pbWFnZS5wbme4+uMy"  # noqa: E501
        content = PetMemoryNftContent.from_tvm(CellSlice(content_boc))
        self.assertEqual(
            asdict(content),
            {
                "imm_data": {
                    "species": 2,
                    "name": "Marcus",
                    "sex": 0,
                    "country_code": "RU",
                    "birth_date": "*",
                    "death_date": "2024-11-15",
                    "species_name": None,
                    "breed": "Nibelung",
                    "lang": "EN",
                    "geo_point": {"is_south": False, "latitude": 45.04627346992493, "longitude": 38.98168087005615},
                    "location": "Krasnodar 350020",
                },
                "data": {
                    "uri": "https://s.getgems.io/nft/c/6738e6330102dc6fdeba9f27/1000000/meta.json",
                    "description": "He appeared in our lives on 08/19/2023. We noticed him a week earlier, on the way to the gym. A big, gray cat, thin as a skeleton, was running out of an abandoned private house, looked at people with piercing emerald eyes, and screamed. We tried to feed him, but that day I realized that if he did not run out at some day, I would not be able to forgive myself. An hour later, my wife and I caught him.\nIt was a former domestic, neutered cat, 10-12 years old, with CKD. Then there were 15 months of struggle and joy of life, ups and downs, and dozens of visits to vets. Several times we thought that he wouldn't get out, but he had an iron will to live. However, on 11/15/2024, he passed away.",
                    "image": "https://s.getgems.io/nft/c/6738e6330102dc6fdeba9f27/1000000/image.png",
                    "image_data": None,
                },
                "fee_due_time": 1779274230,
            },
        )

    def test_content_image_onchain(self):
        content_boc = "te6cckECRQEAHp8AAQABAwEiAgMEAAxNYXJjdXMCIsjY0oAhsjdwzQAAAAAgJBEVBQYCCVqDZDmgBwgAEE5pYmVsdW5nACBLcmFzbm9kYXIgMzUwMDIwAf5IZSBhcHBlYXJlZCBpbiBvdXIgbGl2ZXMgb24gMDgvMTkvMjAyMy4gV2Ugbm90aWNlZCBoaW0gYSB3ZWVrIGVhcmxpZXIsIG9uIHRoZSB3YXkgdG8gdGhlIGd5bS4gQSBiaWcsIGdyYXkgY2F0LCB0aGluIGFzIGEgc2tlbGV0CQEBYA4B/m9uLCB3YXMgcnVubmluZyBvdXQgb2YgYW4gYWJhbmRvbmVkIHByaXZhdGUgaG91c2UsIGxvb2tlZCBhdCBwZW9wbGUgd2l0aCBwaWVyY2luZyBlbWVyYWxkIGV5ZXMsIGFuZCBzY3JlYW1lZC4gV2UgdHJpZWQgdG8gZmVlZCAKAf5oaW0sIGJ1dCB0aGF0IGRheSBJIHJlYWxpemVkIHRoYXQgaWYgaGUgZGlkIG5vdCBydW4gb3V0IGF0IHNvbWUgZGF5LCBJIHdvdWxkIG5vdCBiZSBhYmxlIHRvIGZvcmdpdmUgbXlzZWxmLiBBbiBob3VyIGxhdGVyLCBteSB3CwH+aWZlIGFuZCBJIGNhdWdodCBoaW0uCkl0IHdhcyBhIGZvcm1lciBkb21lc3RpYywgbmV1dGVyZWQgY2F0LCAxMC0xMiB5ZWFycyBvbGQsIHdpdGggQ0tELiBUaGVuIHRoZXJlIHdlcmUgMTUgbW9udGhzIG9mIHN0cnVnZ2xlIAwB/mFuZCBqb3kgb2YgbGlmZSwgdXBzIGFuZCBkb3ducywgYW5kIGRvemVucyBvZiB2aXNpdHMgdG8gdmV0cy4gU2V2ZXJhbCB0aW1lcyB3ZSB0aG91Z2h0IHRoYXQgaGUgd291bGRuJ3QgZ2V0IG91dCwgYnV0IGhlIGhhZCBhbiANAHRpcm9uIHdpbGwgdG8gbGl2ZS4gSG93ZXZlciwgb24gMTEvMTUvMjAyNCwgaGUgcGFzc2VkIGF3YXkuAf4A/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAsICAoIBwsKCQoNDAsNERwSEQ8PESIZGhQcKSQrKigkJyctMkA3LTA9MCcnOEw5PUNFSElIKzZPVU5GVEBHSEX/2wBDAQwNDREPESESEiFFLicuRUVFRUVFRUVFRUVFRUVFRUVFDwH+RUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUX/wAARCAEAAQADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkRAB/qEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ucRAf7o6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNEEgH+RUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDg1SpVSlRamC8UxBMB/kYTio5mES5PWrLYRCx6CsueQyMSfwpiIJJGdsk0wk048nAq1aafLdOABgdyahspIonNN5rql8OQFRlznvUsXh+2jbcctjsaVykjjiG9DTSTXdvp9qy4MQrOutAt5ATEdp9KVyrHJ5NJV+7057SRRIeCePekU7eNoK/3TTAo0VYUAf4nhAHmRZ2Hgj0qvgigQlJS5opiEq1F9wVWxVqIfIKTHEdRilxRSLGP92oank+7UNMQlJS0YpAJjNOC5qe3spLjkcL61fTTVXHzc0mxpXM+O3LHnpVr7OFGFWtKCxUcnJFWhEiDhRWTmbKBkxadJJy3yj3q0thEg5y36VfxxTNrFQH+yEiONnx1I6D6mp5mwaSK3lqowqgfQVC61cZeKhdaLhYI1qbFNQcU8napJ6Cu04iley/8sx+NUUjaZ9qjNLdy8s3cmptNlCKzd6mTsVFXNC10cYBfk+grRt7WUEKkZUewq/ogVly4yx55raCKOgArnlJm8YmOsbRjDjBp+BirVxYB/nHuUsOoqgJCOtUpEuISLioG4BqwxDDrWfqM3kWcr55xgfWl1H0OZvrk3l7I+flU7VHsKgKnFKq4Ap4GeK1JIVby3+b7p4Ip0kAyR6UkyYpwJZVb1GDQwSKz257VCUZetXzTGUGlcOUp856VbiHyCmmJetSR8LTBKwtJTqMUhkUXAf4v3ahqaXpUNMQlLRTlXNIDQ02Xgoa3IoEwGxk1zdufLmU11EHMa/SsamhtSXcdt9Ka4wKmxTWANYI3YzbwKfJLJIgQnCDooGBQBSlad2TYrstQstXGWoWWmmJojUVDdtti2jqasCqN448zHpXoo84yLxsvj0q1p67k/GqE53SEGAH++9a2jx7yo96xmbQOotCYShXsK3YZRIoIP1rFjXAqzbymJxzwazlG6Li7MtXTbD7GsyT7xxWpcASRE1kseeag06iHNZOuuRaon998f1rVJrF1xsvAn+8f5VUdxS2MYDPFBBHNPA5oPvWxmMfLLg023ILNGe/zD/P+elPJxxUDEhkB/o4ZeCDmgC6YxmmNEO1WiqyRJInRxkVCRUbDK7RYGaYg+WrD/dqBelNCFpKdSUxkMtRVLL1qI0yWJUyLgU2Nc81JSY0hV++v1rqLU/uV+lcsp+YfWrs+pO0Pkw5AxhmrOceYuMlEvX+spATFbgSSDqew/wAayjdXErb5ZWJ7c4waAf5TI4D1xUjR7RVRio7EuUpas2dIunnjZJDuZP4j3BrUxWNoa/LM3uo/nW5t6Vz1PiOinsRMvFQstWmWomWoTLZSzxWTdyZdjWizDafmIPris57OR8nzY9vrzn8q9J3PNSMxx81b/h+PPNYz2swyShI9a6Dw+pWLDAispGsTfUcUGwH+GlA4prVI7FuCbchRutULhdsppyuUbIpLhg43d6iSLiyEtWLrXMkGe4YfyrWY1ka0wCQnPIY/lShuVLYyzkUFuORn6Uzfu7ULls4NbmNxGYHp1qJzkU6VT3H41Fkjg0CNDTZt0TwsfunK/Q9atvEMViwSGObdnoprVW6DAA9eKhwB/houLXUhmXbxUC9KnlO5jUAGOKaTBtXFoo6UlMCCU81GoLNgVP5Zkf271LHBjJ7mgnqMVQABSHnPYDqTU0hSMZY/gKqlmkbkYXsKSQ2x33+EyB69zU8cYXGBTEwOvNWUPHT8qYkhQKY/3TzUhbjmi3ha7u4oEBYyMBgdcd6RRs4dAf6bbmCwjLcNId5/p+laijim3MZTapXbjt6VIBxXHJ31OqKtoRsKjYVOwqMrUlMwpTgYqqzfnUsrc1Xc16h5pIs5xg9alhv2i4U4I7VQZqYX9fzov3C1tjcXW5R/CCamTXlP+sQj6VzZkPrzSecc5NS0irs61NQgmHytzTvN3dDXHgH+JhiOVNWoNQkjOGORUShfYtT7nQbs1i67IAsa985FXIr6ORc7sVh6lN5ty21y4HTNRCNmVOWhCWAwe3rTgwU59abGwdSCMGoxlSVNamRO8mRyMiq7nPNP3cYNJwVIPWgZFtIzg8jn6iran3qJVxsPqD/WpE7UAO3HNJu5pzCmlR8B/uPegQFjShhTduc0pXGKBjt4UHFMErk+mf0pcDGTSKwA3H0oAZIfm55P8qEUk5JoC7juPrxT9pHrSETxgdqnDYHOKpgkc4/M0vnsOgAoKuWm6c9K2fC0f2e7F+65CNhQe/rXPwiS4lWNcFmOAK7G2gW2t0hTogx9awqy5Ua048wgAf7N3xN9lmjtrm2ZSX6gVk1FN9ypxWEnfU3graDTTCKlNMNQaM5J25qBjSls0xjzXqHmDWqNqcxqNqQxCaZmlNN71IEsTHoac/FNTpTXbJxVXAekhHeoJ9rSErkE0/G0ZJxTdpY5PSpG9gjzjnqO4oYnOaTG08dKcOTj1piDrj8qIQH+esZPFOSPOKtpFlaBldISVUVIsIXH0qbzEXHrUSzb32+1AAVHJqPI7+uKssBhgBkrgfjVTcNxDdjTAcCA2O1S7N3T0qD1q5bnIzilYRTfuKjYFSB7bquPDiYD1NOubbMuQOP8KdgKcZ5BwBjuatRtkdBn0qtjHPSpI+tIC4kJJyIB/iTk0yWNBnKg1IsojX1NVZpC3B4yaRSZt6JZBF+1OuC3EY9B61sVnaaVW2QPIuccKGz+f+FaIORkVwz1kdkFZDJvuVYFQMNxxUw6VPQpbi000+hlG0etIo4ZtrDP3W746VESehpe3XNRt7flXpnmAxxUbNj6UFqbn8qQxC1NOaUjAf40lIBysw6cinBu+OaaoOc089KBgPU8mnbs+1NGfWnj3ANMQmzNPEagZIFAOOi1LFFLc3EUCLh5WCjPvSAYJgvYmpUuFPHSu4sdAt7OADy1Zx1kYck1lCO01eSWJYR8oJVx1IzjNNNvUiUkjl5zg5zkHkUkA/fE457VZvrF7RtjJAH+ElD91v6VVVijn3HApFotKQpbH3UHX1JquoUyEnrmlZuAvYfMT6mhBtBJ6/1poCLdu3/WrsJKWrMBz1FUEGBn86tebtttveqQFh5ALqLHO7pVsgSAkfdHArKDEEMcnauBVqBmkAMjbU7CmIjuLdt3yiociIdea1R5ci4TmqV1biUB/lfnUZoaAgDttzjmpLFHmuAQRx3I4qvgvwzYHoK0rFVjKlRWU3ZFwV2dBB5ioAWU/RT/AI1MM96ijPyCpK4GdyAf6z8KmFQIf3h+lTCmwQ8U+Rg2ABwBj/H9aYKWpKOBJqJvepzHg4fcPoKQwq3CyqT6MMV6R5pVam1LLE8Zwy4mAf4qI0gG0ZooxQA9FLc9qe3oBSR7scCh8560DEHBqRaaiFj6VN5TAUxCoQOOnvWlpMqxa1Yyy42rMFJ9jxn9ay9pqxhZI8Z+bHSk9Rnqd9bNLbzwxna7KwB9M9Ky/D/h9tPiaa6AEpXbtBzgVS0bxnA0McGqkx3CDb5uPlf3Poa2JwH+7jxLo8FuXmvYWGPuKwYn8BzTUrLU5505PRHMeJbVYtPkkPBZwVH4/wCFciVG7dWnrniBtaufkUpApyAeprMY8VKN4q0bCgliBjPOakbAwo4wKZDgN81SsuXdiO1UhkCAE9OtSLCWwOwp8KZjB79KuRoFXd0FUSx1ppNxeN5duigB/mezMela9v4Utzcrb3d2ftTruEQGTj8eK7DRdOjtLGMYG/blj6k9a5y4tb1PHSFFaTeyuCBwI+AfwA4qkro55VHzWRnat4Xm0qBrq3JkiTlxjayj144NZgnEsWHAOR9K9YmWPyJPMAKbTuHtjmvK7m3RZHVPlXOR7Z5xU7M0py4pAf5ldmY6jfwAPY1ctOAM44qu6kGprPcxI7VlUWh0Q3Ogt23Rips1Ts2+TFWhXHLc7EKh/fH6VOKqp/x8H6VZFAJkgoNIKU1LKucituo6lj9eKGhTHCgH1IzURBPLDn3NALA8fzFekeaE0myIhlB9MdKy25NaE4ypz39KoFMGkxjMKgH+U9UA60ZxSgmkMkA4p6Ipb5hTVBx0/OnHigCwqBe1ObBFLGQyDNOZeOOfrQBRZir4o3Ecg06ZecEVFxjvQIspKrjEqK496mDWm3H2aPd6mqIA6805mUfdAB9aAJdRnicRiKFFJHzbeOlQDOBUL53Z6mpA3AoHclQhee9TW8iSOysB/isee1Vc01R84NNbiZsRoMbcfKaWQqqLEThmIAP41FDIeh/Oi6yzxEfw8itCT0Twzrlvqtkke8Lcxrh4yefqPauhUDHBryeFbVmE0G6GVQPmjOCD7fpVqTULqX/W31xMoGNnnFFP1x1qU2kZSoqTvc6rxHrcSJJZW8g3Y/0iQHgsAf6NfTPqemK4KW582SSTbwx4B7Dt+lTTfvFAmkRI15WKEcD/ABPuaqO6OQqcKKPM0ilFWQjYYZFXLBD5ZJx17GquFx0/StG2AjtQzcZ6VlV+E3pfET2bfOwq9WZbN+/z61p9a5JHXEZGP9Ib6VaFV0GJT9KtyXEkwUSNnb046U+hLQH+N9RopTQKDUMo4NmY/wDLRz+NCu2eWJ/GmcnOOaeq85ZgPxr0jzxzsccZNV2BNWWGelQP6ZpARbQOvJp6rjk0dOgxR+NSMlBqORsdacsigdfzpj4Pf8aBjoboxcFcqferkdzHIOOM9jWXs98VLGIh94t+X/1xQCbNJo1YdKqyRi4B/sp4H51Pb7cfK+Qe3P8Aiamkibr1pXHYz8445H40m0sCVB4pJyd5HGB3xRGxVh/Q1QhjCmjgc1K33ulM4ZvlpCFXmnYxUkaAj5SGPsamW2J68CmgJLcEryDSXZKkFecVZhhMcZznFVbld7DjIqyR9tLhcE4Geak3OfvDHcHoDVQvAf5cqAfzq/HGZIgcAqe+OaLhYgMbHuAKlhHHC5pywYbBU1oRWrLGCE/EikOxSKE9vwIq1KyGJVjZDgY4NEg8vLNHkCqErLISyNz6NwfzrKeprT0L9qhaQAda2Am1cd65+wmkWUA81sNcuq5ETE+3Nc0k7nQpJEgXDmpVqhHegsd6MAH+lT6Y6VbimR/usKLaCvqTig0CkNQy0cNDaSOCSU/Fv8KnjtGU5Kx1RQsp4Jz7Vp2oJXLZJ969BHDYjeHjk/lUDxY6VouDiqzLQx2KJRhyRgVEykckVbc5PA/E0xgD1qQK+7A4456gVahs8rvl69QtRRx7X3YBx0z2rSjUBRtxzzEB/loBFF4GBxtCDsAOajaMoMjaPrzWoUA5P51FIpx8oH40DsVIFctguQD6CrzeWI872OB/D/8AWqvBGHf5iWxV1guNoA/DmgEZbTsz8LkDuVp26JvvoUz3qzgqdqgnHbAxStCu3dKmW9BzQKxCLfcoKkEds1BPA8PzhQR3q6m3GAcyAf4D3FTGPcmDggimBQtyk3QbWFXFRupYjHeqXl/ZZWbPHanszTqIUb3bFTqXdW1LiXkUYOZg/baDkmoGkWZwF4HpUaWirwoz6kVbgiVGG5cZrRMzY0Im3GQT6d61LGFzEEEfB5zT7fS1ni3hjImc4znBrSsrERBlkUNH60AhkVjGMwH+33iR+FPnjS3jJc5HY1ccRouQxGO1Yt7dec5XOAPbiolLlRcY8zM+4kZnPAKntVJ4xyRV1l5ppjyDXPe5vy22CwT5wa21FZtlHhq1FFIQrRpIAJEDfWq0lgd+YWwvoat9xT6AIbdXSPDnNSMcjGacajIxUtFKRxs1oUk+X7tXbTQB/rZFEBuUHvinQMtxHhlP404IkRwiHPsP613HIPYbhnH4mq0iM3GMD+dWMOVyxCLQsYPOM+5pNDKBhI/zxTGj2jLd+g9a0WVclm5C9qoSNvdiec0hsYieY4yOOwq4zLCNo5bvVVN3VePejJz8vT1oEW1bzDzx7VFOQASTwPSmq+w1Af5Mk8H06n/61SwrHIQz4OOi0DuFnbvIu7GxT0A6mryxpGDnnHp/jQ0ygeVFjOMEj/PSlBC/M3PpSBA9v5yhvuY6H0qnK7wuEADehYdavliTyailiE4wep9KAuVleN13EAkflTJJ44wcmmPpblsRh/zqaLQj96ck+1MNTMu7jzvlNgH+QAL6461oaY0bwlQF3/qasyaTCgwVPPvUUdpJZSiSJS8TDoO1AWaJWhZB8qfN64qzbpI5AmQMhOCcdP8A9daFjDHqKYQ4YdQwxWvDpiWuWHQjBzVCKFpp5tJ1miZguPmQHr7+9Xnuo0U5XAxyV/wpjzeTHtftwGFZk9wVY+YMqTcB/ucik2NEV9dFj8nT26Gs0uGPPWpZxg7ojnPOP89f5+1VdyyDKEZ/nXPO5tGxMKdtyOKhjcg4NXEXIqC7jrRMNV8Cq1uuDVwCgTADmnUAUUCENMY041GxoEYcUit8qY4q0oDLnAOKwrKYCUAnn0HatqBhsGAcZrsOcil+9k//AKo4Af6cpG3OfypLi0Nww/e7F9B3pGhWJQoLN7ZxQBUup8/InTuagjizyfyqabah5HzdlFNi3HcGHcZpDF2nGAOKjYDGAMj+dWNrHqaY3HAFIRWfg/Ocn0qSIkI0jdugHao9hY1cjgPkupHagAibZEGX70hqTzlkbaOimoJcRGBP9k0iOQH+rgnHegZoK2RURkKTgdiKSIMqDuRU0kO6IsB14/GgDQs5kONwyfQ1swJFJyVGa5iyjdo1IzkHFdBZ749u/gUiy+bOBhho1NAtLZVA8tQBTJptkYIOSaoNfNwA3ak2OxeElvZuSsYGeuKhvdRjPMROMdPWs6aYsMd6psSTik2MmToB/u9PPPBqDzwflcZQn8VPtTGjzTTGaSbB2IJ90bY+8jcj0P8A9eoGXneD9Sf6/wCNaIjXlHGUJ/759xTZLQo239R3FJiKi/MAe471etwdvNU/La3kGRhD+lX4V+Ud6hqxalcswirKioolqwBxUjEprU81G1AxhNRsac1RtTJZw8c7Af4gjYMBzXQWzlolJ9K5lScitixuVEYVifxrqOZGuD3o259cn0ogCyLkHFXIbXuTmmUU1tFzkqCaf9iOCQOOp9600txjpVhYenHekBzMkZXORjtTFg3N06V0k2nLNzjBqmbBotwAySaVgMyK0BZiRwRU6Q4IyPrWitttXp0NPFplPAH+hTA5zU4GXyWA5XP6Y/xp8MW7DAda3L2x3IuFzzkf5/z0qS201IocEZz+lKwzMW3OzpV21tSwKsPlIq5FbBMg84qwoC8UAJFDFbxDYoGKimuFfpSzS7cjqKzS3zHHSoky4ovLNuXaaoXHyyVKkmOtRXPzEEd6goR2yPypjdaOMT0B/o96TvTuIKKMe9H40C0HA1IGyoUnp9329vpUX40uaAJ/ISdDG4x7+lZ6u9jOYZuE7H/PatCB8nHerFxaR3sBR+G/hb0NTcLCQ8qCOlT4rGtLiTT7j7LdDA/hbt/+qtkEEZqWrFJ3ENRtT2NRMaVhjTUTU9jULNVCZwi9at2w+cE+Af6qqDFWrYhXBNdJznQWZwAT+FbEJ4FYVtINwyeBWnHcKq5LUxmqhq1GoIrKgullkwDmtKNwEB9KAJsU1YgxbPr/AEp+QTSj19aAGfZxzUa7ftDR9xU00wjVj12jNYrXv+m29x0Dttceh6f1o3E2azqNh/2TUZdVIGRzTxIHaQA5PwH+Fc3qt0WljSJjuBGQPc4/n/OhDNuWURIzt0HWsubVdsnHQVmz64weVcb4s7R645/wrNkuvMyQMDrTsFzpI76O7OAcPjoe9IwKvgiuWSZ1YMrEEGunim860idjluhrOUSozH80hzkcVKBS4FRYvmuRbRR5eecVIaVRk0hDRtAxtEAB/lRmMHoKsY9qSi47FXY3YGjy29DVsYHU0u5c8mpuMghBDDIrTTpVQbSeKsI3FSMZfWcd7Dsfhh91vSsqzvnsp/sd7wOiua2i1UdSso76Ha3Dj7relNdmJ90WGaomasmyubm0Jt7xG2Lwr9q0GkBGQciiwXFZqgdqGaoXenYTOR1BAf64NPU4706RccUwegzXQYkyyyL91yKeLycfx1X2nvUmzCZPWmIswapPby+YCD2xXUaVrkF8nkyZjkPHJ4P41x6Q7lzk5qzZQks+Oq0MEz0ONztXf1xz9aczcAA9KydMuWmtwHJJAHJq+GqNiriz5aOTAyWHSsCeNnyDkYOR9a6IQgH+MAKrSwK7E7etLmsO1yjZ3giF1vJLhQw9On+NczLcO0xl6HGfoen+BrqZrdVBBXqKxZtMJcmNVZfQ8VSaJsY5GIj7kf1ojXgnHFWrmwkhAIjb3wdwqOGMyfKFOfYVQCQopkA9a37eEpsT0GcGo9H0sfaBJPHIFXn5lwK1UtZGvEMB/nkKgIelRKRSRGENLtNOY/viAMAUtZ3LsIIzTvLp4oJFS2UkMMZPemGA+tS7qTdSGRfZ/wDapfIUdTmn7qTdQIAqr0GKUNzUbNTVbk/SkCLG/NMZqg8z5jQXpgwmVZUKv0rHF0bScwvnZngHtWoz1SvIEukw2AwHDf0PtVIkeZREADgy5ByKhZqzI7h7SUxTZx0yatmQMMg5FVYVz//Znd6m4A=="  # noqa: E501
        content = PetMemoryNftContent.from_tvm(CellSlice(content_boc))
        _dict = asdict(content)
        image_data = _dict["data"].pop("image_data")
        self.assertEqual(len(image_data), 9301)

    def test_content_image_ipfs(self):
        content_boc = "te6cckECDwEAA2cAAQABAwEiAgMEAAxNYXJjdXMCIsjY0oAhsjdwzQAAAAAgJBEVBQYCCVqEAUsgBwgAEE5pYmVsdW5nACBLcmFzbm9kYXIgMzUwMDIwAf5IZSBhcHBlYXJlZCBpbiBvdXIgbGl2ZXMgb24gMDgvMTkvMjAyMy4gV2Ugbm90aWNlZCBoaW0gYSB3ZWVrIGVhcmxpZXIsIG9uIHRoZSB3YXkgdG8gdGhlIGd5bS4gQSBiaWcsIGdyYXkgY2F0LCB0aGluIGFzIGEgc2tlbGV0CQEBoA4B/m9uLCB3YXMgcnVubmluZyBvdXQgb2YgYW4gYWJhbmRvbmVkIHByaXZhdGUgaG91c2UsIGxvb2tlZCBhdCBwZW9wbGUgd2l0aCBwaWVyY2luZyBlbWVyYWxkIGV5ZXMsIGFuZCBzY3JlYW1lZC4gV2UgdHJpZWQgdG8gZmVlZCAKAf5oaW0sIGJ1dCB0aGF0IGRheSBJIHJlYWxpemVkIHRoYXQgaWYgaGUgZGlkIG5vdCBydW4gb3V0IGF0IHNvbWUgZGF5LCBJIHdvdWxkIG5vdCBiZSBhYmxlIHRvIGZvcmdpdmUgbXlzZWxmLiBBbiBob3VyIGxhdGVyLCBteSB3CwH+aWZlIGFuZCBJIGNhdWdodCBoaW0uCkl0IHdhcyBhIGZvcm1lciBkb21lc3RpYywgbmV1dGVyZWQgY2F0LCAxMC0xMiB5ZWFycyBvbGQsIHdpdGggQ0tELiBUaGVuIHRoZXJlIHdlcmUgMTUgbW9udGhzIG9mIHN0cnVnZ2xlIAwB/mFuZCBqb3kgb2YgbGlmZSwgdXBzIGFuZCBkb3ducywgYW5kIGRvemVucyBvZiB2aXNpdHMgdG8gdmV0cy4gU2V2ZXJhbCB0aW1lcyB3ZSB0aG91Z2h0IHRoYXQgaGUgd291bGRuJ3QgZ2V0IG91dCwgYnV0IGhlIGhhZCBhbiANAHRpcm9uIHdpbGwgdG8gbGl2ZS4gSG93ZXZlciwgb24gMTEvMTUvMjAyNCwgaGUgcGFzc2VkIGF3YXkuAKBpcGZzOi8vYmFmeWJlaWIzNTZybGhzaGI3dXhseGd3a2s0cWg0a3lybTJld3A0bjVxbTJ5eHU0ejJ5amdoZXZpc20vbWFyY3VzLTQud2VicHZeB4A="  # noqa: E501
        content = PetMemoryNftContent.from_tvm(CellSlice(content_boc))
        self.assertEqual(
            asdict(content),
            {
                "imm_data": {
                    "species": 2,
                    "name": "Marcus",
                    "sex": 0,
                    "country_code": "RU",
                    "birth_date": "*",
                    "death_date": "2024-11-15",
                    "species_name": None,
                    "breed": "Nibelung",
                    "lang": "EN",
                    "geo_point": {"is_south": False, "latitude": 45.04627346992493, "longitude": 38.98168087005615},
                    "location": "Krasnodar 350020",
                },
                "data": {
                    "uri": None,
                    "description": "He appeared in our lives on 08/19/2023. We noticed him a week earlier, on the way to the gym. A big, gray cat, thin as a skeleton, was running out of an abandoned private house, looked at people with piercing emerald eyes, and screamed. We tried to feed him, but that day I realized that if he did not run out at some day, I would not be able to forgive myself. An hour later, my wife and I caught him.\nIt was a former domestic, neutered cat, 10-12 years old, with CKD. Then there were 15 months of struggle and joy of life, ups and downs, and dozens of visits to vets. Several times we thought that he wouldn't get out, but he had an iron will to live. However, on 11/15/2024, he passed away.",
                    "image": "ipfs://bafybeib356rlhshb7uxlxgwkk4qh4kyrm2ewp4n5qm2yxu4z2yjghevism/marcus-4.webp",
                    "image_data": None,
                },
                "fee_due_time": 1779434796,
            },
        )
