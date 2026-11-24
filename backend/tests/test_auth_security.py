"""auth 安全模块单元测试：密码哈希与 JWT（不依赖 MySQL）"""

import jwt

from auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
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
