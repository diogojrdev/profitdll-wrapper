"""Tests for .env parsing in profitdll_wrapper._config."""

from __future__ import annotations

from pathlib import Path

import pytest

from profitdll_wrapper._config import load_credentials, load_env_file


def test_inline_comment_is_stripped(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "ACTIVATION_KEY=fake-activation-key-000 # trailing comment\nPASSWORD=fake-password-123\n",
        encoding="utf-8",
    )
    parsed = load_env_file(env)
    assert parsed["ACTIVATION_KEY"] == "fake-activation-key-000"
    assert parsed["PASSWORD"] == "fake-password-123"


def test_hash_without_space_is_preserved(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TOKEN=abc#def\n", encoding="utf-8")
    assert load_env_file(env)["TOKEN"] == "abc#def"


def test_full_line_comment_and_quotes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nUSER='someone@example.com'\n\nBROKER=15003\n",
        encoding="utf-8",
    )
    parsed = load_env_file(env)
    assert parsed == {"USER": "someone@example.com", "BROKER": "15003"}


def test_os_user_does_not_leak_into_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic OS vars (USER/PASSWORD) must never be used as credentials."""
    monkeypatch.setenv("USER", "os-username")
    monkeypatch.setenv("PASSWORD", "os-password")
    creds = load_credentials(tmp_path / ".env-missing")
    assert creds["user"] == ""
    assert creds["password"] == ""


def test_env_file_user_and_prefixed_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """:.env USER= works; PROFITDLL_USER in the environment takes precedence."""
    env = tmp_path / ".env"
    env.write_text("USER=file-user\nPASSWORD=file-pass\n", encoding="utf-8")
    creds = load_credentials(env)
    assert creds["user"] == "file-user"
    assert creds["password"] == "file-pass"

    monkeypatch.setenv("PROFITDLL_USER", "env-user")
    assert load_credentials(env)["user"] == "env-user"
