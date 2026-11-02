import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    PasswordPolicyError,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    token_hash,
    validate_password,
    verify_password,
)

SECRET = "s" * 40


def test_hash_and_verify() -> None:
    h = hash_password("Lahore-2027-xyz")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Lahore-2027-xyz")
    assert not verify_password(h, "lahore-2027-xyz")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "x")


@pytest.mark.parametrize(
    "pw", ["short1", "onlyletterslong", "1234567890123", "x" * 120 + "1" * 9, "ali.khan1"]
)
def test_password_rules_reject(pw: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(pw, email="Ali.Khan1@school.pk")


def test_password_rules_accept() -> None:
    validate_password("Sab-theek-123", email="ali@school.pk")


def test_access_token_roundtrip_and_failures() -> None:
    uid = uuid.uuid4()
    token = create_access_token(uid, secret=SECRET, ttl=timedelta(minutes=15))
    assert decode_access_token(token, secret=SECRET) == uid
    with pytest.raises(TokenError):
        decode_access_token(token, secret="t" * 40)
    expired = create_access_token(uid, secret=SECRET, ttl=timedelta(seconds=-5))
    with pytest.raises(TokenError):
        decode_access_token(expired, secret=SECRET)
    with pytest.raises(TokenError):
        decode_access_token("garbage", secret=SECRET)


def test_token_hash_is_stable_sha256() -> None:
    assert token_hash("abc") == token_hash("abc")
    assert len(token_hash("abc")) == 64
