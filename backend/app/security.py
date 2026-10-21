"""Bound simultaneous Argon2 operations for small single-worker deployments."""

from threading import BoundedSemaphore
from pwdlib import PasswordHash


class SerializedPasswords:
    def __init__(self):
        self._hash = PasswordHash.recommended()
        self._gate = BoundedSemaphore(1)

    def hash(self, value):
        with self._gate:
            return self._hash.hash(value)

    def verify(self, value, hashed):
        with self._gate:
            return self._hash.verify(value, hashed)


passwords = SerializedPasswords()
