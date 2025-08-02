#!/usr/bin/python3
import base64
import hashlib
import hmac
import os
import sys

def hi(password: bytes, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password, salt, iterations)

def generate_scram_sha256(username: str, password: str, iterations: int = 4096):
    salt = os.urandom(16)
    salted_password = hi(password.encode('utf-8'), salt, iterations)

    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()

    return f'"{username}" "SCRAM-SHA-256${iterations}:{base64.b64encode(salt).decode()}:{base64.b64encode(stored_key).decode()}:{base64.b64encode(server_key).decode()}"'

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 generate_scram.py <username> <password>")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    print(generate_scram_sha256(username, password))
