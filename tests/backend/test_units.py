"""Pure unit tests: password policy, tokens, log redaction."""
from __future__ import annotations

import json
import logging
from datetime import UTC

import pytest


def test_password_policy():
    from agentsmind.security.passwords import password_problems

    assert password_problems("Plenty-Long-Passw0rd") == []
    assert password_problems("short")
    assert password_problems("aaaaaaaaaaaaaaa")
    assert password_problems("ayesha.khan-2026!", email="ayesha.khan@example.com")


def test_hash_and_verify():
    from agentsmind.security.passwords import hash_password, verify_password

    h = hash_password("Plenty-Long-Passw0rd")
    assert verify_password("Plenty-Long-Passw0rd", h)
    assert not verify_password("plenty-long-passw0rd", h)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_access_token_round_trip_and_tamper(monkeypatch):
    import jwt as pyjwt

    from agentsmind.security.tokens import TokenError, create_access_token, decode_access_token

    tok, ttl = create_access_token(7, ["hr", "admin"])
    c = decode_access_token(tok)
    assert c.user_id == 7 and c.roles == ("admin", "hr") and ttl == 900
    forged = pyjwt.encode({"sub": "7", "roles": ["admin"], "typ": "access", "iss": "agentsmind",
                           "iat": 0, "exp": 9999999999, "jti": "x"}, "wrong-secret-" + "y" * 40, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged)
    none_alg = pyjwt.encode({"sub": "7"}, key=None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(none_alg)


def test_expired_token_rejected():
    from datetime import datetime, timedelta

    from agentsmind.security.tokens import TokenError, create_access_token, decode_access_token

    tok, _ = create_access_token(1, ["employee"], now=datetime.now(UTC) - timedelta(hours=2))
    with pytest.raises(TokenError):
        decode_access_token(tok)


def test_json_log_redacts_secrets(capsys):
    from agentsmind.log_config import configure_logging

    configure_logging("INFO", True)
    logging.getLogger("t").info("hello", extra={"password": "hunter2", "nested": {"api_key": "sk-1"}, "ok": 1})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["msg"] == "hello" and rec["password"] == "***" and rec["nested"]["api_key"] == "***"
    assert rec["ok"] == 1 and "hunter2" not in line
