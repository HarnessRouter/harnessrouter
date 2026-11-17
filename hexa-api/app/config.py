from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default='', repr=False)
    admin_username: str = "admin"
    admin_password_hash: str = field(default='', repr=False)
    session_secret: str = field(default='', repr=False)
    gateway_url: str = "http://127.0.0.1:3000/api/harness"
    gateway_api_key: str = field(default='', repr=False)
    cookie_secure: bool = True
    session_ttl_seconds: int = 60 * 60 * 24 * 14

    def validate(self):
        parsed = urlsplit(self.gateway_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('HEXA_GATEWAY_URL 必须为无凭据的 HTTP(S) 地址。')
        if not self.database_url:
            raise ValueError('必须配置 HEXA_DATABASE_URL。')
        if not self.admin_password_hash or not self.session_secret or not self.gateway_api_key or self.session_ttl_seconds <= 0:
            raise ValueError('必须配置管理员密码哈希、会话 secret、Gateway API Key 和有效会话期限。')

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("HEXA_DATABASE_URL", ''),
            admin_username=os.getenv("HEXA_ADMIN_USERNAME", "admin"),
            admin_password_hash=os.getenv("HEXA_ADMIN_PASSWORD_HASH", ""),
            session_secret=os.getenv("HEXA_SESSION_SECRET", ""),
            gateway_url=os.getenv("HEXA_GATEWAY_URL", cls.gateway_url),
            gateway_api_key=os.getenv("HEXA_GATEWAY_API_KEY", ""),
            cookie_secure=os.getenv("HEXA_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"},
            session_ttl_seconds=int(os.getenv("HEXA_SESSION_TTL_SECONDS", str(cls.session_ttl_seconds))),
        )
