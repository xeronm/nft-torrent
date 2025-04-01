import unittest

from NFTorrent.auth import NodeJWTBearer

def get_node_state():
    return [
        {"adnl_id":"35Amksx2Z3frlaXULPQak4kRr8Imncuw+8JM/KMXGJ4=","ip_str":"192.168.1.10:3333"},
        {"adnl_id":"35Amksx2Z3frlaXULPQak4kRr8Imncuw+8JM/KMXGJ4=","ip_str":"192.168.1.20:3333"},
    ]

class TestNodeJWTBearer(unittest.TestCase):

    def test_jwt_bearer(self):
        bearer_s10 = NodeJWTBearer(subject='192.168.1.10', jwt_algorithm='HS256', jwt_secret='0123456789', node_state=get_node_state)
        bearer_s20 = NodeJWTBearer(subject='192.168.1.20', jwt_algorithm='HS256', jwt_secret='0123456789', node_state=get_node_state)
        bearer_s30 = NodeJWTBearer(subject='192.168.1.30', jwt_algorithm='HS256', jwt_secret='0123456789', node_state=get_node_state)

        token_s20_a10 = bearer_s20.get_jwt_token('192.168.1.10')
        try:
            validated = bearer_s10.verify_jwt_token(token_s20_a10, '192.168.1.20') or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, True)

        token_s10_a20 = bearer_s10.get_jwt_token('192.168.1.20')
        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a20, '192.168.1.10') or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, True)

        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a20, '192.168.1.30') or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, 'InvalidSubjectError')


        token_s10_a30 = bearer_s10.get_jwt_token('192.168.1.30')
        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a30, '192.168.1.10') or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, 'InvalidAudienceError')

        token_s30_a10 = bearer_s30.get_jwt_token('192.168.1.10')
        try:
            validated = bearer_s10.verify_jwt_token(token_s30_a10, '192.168.1.30') or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, 'InvalidSubjectError')
