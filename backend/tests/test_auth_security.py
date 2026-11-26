"""auth 安全模块单元测试：密码哈希与 JWT（不依赖 MySQL）"""

import jwt
import pytest
from pydantic import ValidationError

from auth.schemas import ChangePasswordRequest, UpdateProfileRequest
from auth.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed) is True
    assert verify_password("wrong-pass", hashed) is False


def test_verify_password_with_invalid_hash():
    # 损坏的哈希串不应抛异常，返回 False
    assert verify_password("whatever", "not-a-valid-bcrypt-hash") is False


def test_access_token_roundtrip():
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert "exp" in payload and "iat" in payload


def test_decode_invalid_token_raises():
    import pytest

    with pytest.raises(jwt.PyJWTError):
        decode_access_token("this.is.bogus")


def test_refresh_token_is_opaque_and_unique():
    a = generate_refresh_token()
    b = generate_refresh_token()
    assert a != b
    # token_urlsafe(48) 产生足够长的 url-safe 随机串
    assert len(a) >= 40


def test_hash_token_stable_and_hex():
    raw = generate_refresh_token()
    h1 = hash_token(raw)
    h2 = hash_token(raw)
    assert h1 == h2  # 同一令牌哈希稳定
    assert h1 != hash_token(generate_refresh_token())  # 不同令牌哈希不同
    assert len(h1) == 64  # sha256 十六进制摘要
    assert all(c in "0123456789abcdef" for c in h1)


def test_update_profile_schema_validation():
    assert UpdateProfileRequest().nickname is None  # 未提交的字段不动
    assert UpdateProfileRequest(nickname="  新昵称  ").nickname == "新昵称"
    with pytest.raises(ValidationError):
        UpdateProfileRequest(nickname="   ")
    assert UpdateProfileRequest(avatar="").avatar == ""  # 空串表示清除头像
    with pytest.raises(ValidationError):
        UpdateProfileRequest(avatar="https://example.com/a.png")
    with pytest.raises(ValidationError):
        UpdateProfileRequest(avatar="data:text/plain;base64,YQ==")
    with pytest.raises(ValidationError):
        UpdateProfileRequest(avatar="data:image/png;base64," + "a" * (2 * 1024 * 1024))


def test_change_password_schema_validation():
    with pytest.raises(ValidationError):
        ChangePasswordRequest(old_password="old", new_password="12345")
