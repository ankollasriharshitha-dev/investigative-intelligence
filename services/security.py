"""Local password, TOTP, session, and RBAC services for the prototype."""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.audit import AuditService


ROLES = ("Investigator", "Senior Officer", "Forensic Officer", "Administrator")
PERMISSIONS = {
    "case:create": {"Investigator", "Senior Officer", "Administrator"},
    "case:view": set(ROLES), "evidence:upload": {"Investigator", "Senior Officer", "Forensic Officer", "Administrator"},
    "evidence:verify": {"Senior Officer", "Forensic Officer", "Administrator"},
    "analysis:view": {"Investigator", "Senior Officer", "Forensic Officer", "Administrator"},
    "audit:view": {"Administrator"}, "users:manage": {"Administrator"}, "security:configure": {"Administrator"},
}


@dataclass(frozen=True)
class User:
    username: str
    role: str
    password_hash: str
    totp_secret: str
    mfa_enrolled: bool


class AuthorizationError(PermissionError):
    pass


class AuthenticationService:
    """File-backed demo identities. Passwords are PBKDF2 hashes, never plaintext."""

    def __init__(self, path: Path, audit: AuditService) -> None:
        self.path, self.audit = path, audit
        self._ensure_users()

    def verify_password(self, username: str, password: str) -> User | None:
        user = self.get_user(username)
        valid = bool(user and _verify_password(password, user.password_hash))
        self.audit.record(username, "LOGIN", "session", "Success" if valid else "Denied")
        return user if valid else None

    def verify_totp(self, user: User, code: str, window: int = 1) -> bool:
        valid = user.mfa_enrolled and any(hmac.compare_digest(_totp(user.totp_secret, offset), str(code).strip()) for offset in range(-window, window + 1))
        self.audit.record(user.username, "MFA_VERIFICATION", "session", "Success" if valid else "Denied")
        return valid

    def begin_totp_enrollment(self, username: str) -> User:
        """Create and persist a secret for a user who has not enrolled yet."""
        records = self._records()
        for record in records:
            if record.get("username") == username:
                if not record.get("totp_secret"):
                    record["totp_secret"] = _new_secret()
                    self._write(records)
                return User(record["username"], record["role"], record["password_hash"], record["totp_secret"], bool(record.get("mfa_enrolled", False)))
        raise ValueError("Unknown user")

    def complete_totp_enrollment(self, user: User, code: str, window: int = 1) -> bool:
        """Verify a real TOTP code before marking MFA enrollment complete."""
        valid = any(hmac.compare_digest(_totp(user.totp_secret, offset), str(code).strip()) for offset in range(-window, window + 1))
        if valid:
            records = self._records()
            for record in records:
                if record.get("username") == user.username:
                    record["mfa_enrolled"] = True
                    self._write(records)
                    break
        self.audit.record(user.username, "MFA_ENROLLMENT", "session", "Success" if valid else "Denied")
        return valid

    @staticmethod
    def provisioning_uri(user: User, issuer: str = "Investigative Intelligence") -> str:
        label = quote(f"{issuer}:{user.username}")
        return f"otpauth://totp/{label}?secret={user.totp_secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"

    def get_user(self, username: str) -> User | None:
        for record in self._records():
            if record.get("username") == username:
                return User(record["username"], record["role"], record["password_hash"], record["totp_secret"], bool(record.get("mfa_enrolled", False)))
        return None

    def require(self, user: User | None, permission: str) -> None:
        if not user or user.role not in PERMISSIONS.get(permission, set()):
            self.audit.record(user.username if user else "anonymous", "PERMISSION_DENIED", permission, "Denied")
            raise AuthorizationError("You do not have permission for this operation.")

    def _ensure_users(self) -> None:
        if self.path.exists(): return
        # Fixed hashes permit local demo access without storing a plaintext password.
        password_hash = _hash_password(os.environ.get("II_DEMO_PASSWORD", "DemoPass!2026"))
        records = [{"username": "demo_investigator", "role": "Investigator", "password_hash": password_hash, "totp_secret": _new_secret(), "mfa_enrolled": False}, {"username": "demo_forensic", "role": "Forensic Officer", "password_hash": password_hash, "totp_secret": _new_secret(), "mfa_enrolled": False}, {"username": "demo_admin", "role": "Administrator", "password_hash": password_hash, "totp_secret": _new_secret(), "mfa_enrolled": False}]
        self._write(records)

    def _records(self) -> list[dict[str, Any]]:
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _hash_password(password: str) -> str:
    salt = os.urandom(16); rounds = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError): return False


def _new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp(secret: str, offset: int = 0) -> str:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    counter = int(time.time() // 30) + offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    index = digest[-1] & 15
    value = (struct.unpack(">I", digest[index:index + 4])[0] & 0x7fffffff) % 1_000_000
    return f"{value:06d}"
