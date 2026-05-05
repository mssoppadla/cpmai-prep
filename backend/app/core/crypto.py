"""Symmetric encryption for at-rest secrets (LLM API keys)."""
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings


class CryptoService:
    def __init__(self):
        if not settings.ENCRYPTION_KEY:
            raise RuntimeError("ENCRYPTION_KEY is required")
        self._fernet = Fernet(settings.ENCRYPTION_KEY.encode())

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as e:
            raise RuntimeError("Failed to decrypt — wrong ENCRYPTION_KEY?") from e


crypto = CryptoService() if settings.ENCRYPTION_KEY else None
