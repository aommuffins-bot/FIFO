"""
auth.py -- 權限管理層：使用者驗證、角色控制
------------------------------------------------------------------------
角色設計：
- admin（管理者）：可進貨、可出貨、可查看完整損益報表
- staff（店員）：僅可執行出貨，無法進貨或查看成本/毛利數據

實作說明：
- 密碼雜湊：使用 Python 標準庫 hashlib.pbkdf2_hmac
- Token 機制：輕量級自製 JWT(HS256)，僅依賴標準庫，無需額外安裝 python-jose

v2 修正紀錄：
- seed_known_accounts() 改為「強制校正密碼」邏輯：
  系統內建帳號（admin/aom_founder/aom_staff）若已存在於資料庫，
  但密碼與程式碼中指定的已知密碼不符（例如資料庫殘留舊版本的密碼），
  會自動更新為程式碼中指定的密碼，確保每次部署後這幾組帳密必定可登入。
  （此設計僅適用於系統固定帳號，不影響一般使用者未來自訂密碼的彈性）
"""

import os
import hmac
import hashlib
import base64
import json
import time
import secrets
from typing import Optional
from sqlalchemy import text
from db_engine import get_conn, users

SECRET_KEY = os.environ.get("AOM_JWT_SECRET", "CHANGE_ME_IN_PRODUCTION_ENV_VAR")
TOKEN_TTL_SECONDS = 8 * 3600


def hash_password(password: str, salt: Optional[str] = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return base64.b64encode(digest).decode(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest, _ = hash_password(password, salt)
    return hmac.compare_digest(digest, password_hash)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encode_token(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(payload)
    payload["exp"] = int(time.time()) + TOKEN_TTL_SECONDS
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise TokenError("Token 格式錯誤")
    signing_input = (header_b64 + "." + payload_b64).encode()
    expected_sig = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenError("Token 簽章驗證失敗")
    payload = json.loads(_b64url_decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise TokenError("Token 已過期，請重新登入")
    return payload


def create_user(username: str, password: str, role: str, store_id: Optional[int] = 1) -> int:
    if role not in ("admin", "staff"):
        raise ValueError("role 必須為 admin 或 staff")
    pw_hash, salt = hash_password(password)
    with get_conn() as conn:
        result = conn.execute(
            users.insert().values(
                username=username, password_hash=pw_hash, password_salt=salt,
                role=role, store_id=store_id, is_active=1
            )
        )
        return result.inserted_primary_key[0]


def update_password(username: str, new_password: str) -> None:
    """強制更新指定帳號的密碼（不論目前密碼為何）。"""
    pw_hash, salt = hash_password(new_password)
    with get_conn() as conn:
        conn.execute(
            text(
                "UPDATE users SET password_hash = :h, password_salt = :s "
                "WHERE username = :u"
            ),
            {"h": pw_hash, "s": salt, "u": username}
        )


def authenticate(username: str, password: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            text(
                "SELECT user_id, username, password_hash, password_salt, "
                "role, store_id, is_active FROM users WHERE username = :u"
            ),
            {"u": username}
        ).mappings().first()
        if not row or not row["is_active"]:
            return None
        if not verify_password(password, row["password_hash"], row["password_salt"]):
            return None
        return {
            "user_id": row["user_id"], "username": row["username"],
            "role": row["role"], "store_id": row["store_id"]
        }


def user_exists(username: str) -> bool:
    with get_conn() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE username = :u"), {"u": username}
        ).scalar()
        return bool(count)


# 系統內建固定帳號（帳號、密碼、角色）：每次啟動皆會強制校正密碼
KNOWN_ACCOUNTS = [
    ("admin", "admin123", "admin"),
    ("aom_founder", "Dc20220111", "admin"),
    ("aom_staff", "aomstaff008", "staff"),
]


def seed_known_accounts():
    """
    確保系統預設帳號存在於真實資料庫中，且密碼與下方 KNOWN_ACCOUNTS 一致：
    - 帳號不存在 -> 建立新帳號
    - 帳號已存在但密碼不符（例如資料庫殘留舊版本密碼）-> 強制更新為指定密碼
    此設計確保無論資料庫先前狀態為何，系統固定帳號永遠可用指定密碼登入，
    避免因新舊版本密碼設定不一致導致「帳密正確卻登入失敗」的問題。
    """
    for username, password, role in KNOWN_ACCOUNTS:
        if not user_exists(username):
            create_user(username, password, role=role, store_id=1)
        else:
            with get_conn() as conn:
                row = conn.execute(
                    text(
                        "SELECT password_hash, password_salt FROM users WHERE username = :u"
                    ),
                    {"u": username}
                ).mappings().first()
            if row and not verify_password(password, row["password_hash"], row["password_salt"]):
                update_password(username, password)