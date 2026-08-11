from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import settings_service


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.passwords:
            raise self.errors.PasswordDeleteError()
        del self.passwords[(service, username)]


def test_credential_round_trip(monkeypatch) -> None:
    vault = FakeKeyring()
    monkeypatch.delenv("TODOIST_API_TOKEN", raising=False)
    monkeypatch.setattr(settings_service, "_keyring_module", lambda: vault)

    assert settings_service.get_todoist_token() == ""
    settings_service.save_todoist_token(" secret ")
    assert settings_service.get_todoist_token() == "secret"
    assert settings_service.get_todoist_token_source() == "credential"

    settings_service.remove_todoist_token()
    assert settings_service.get_todoist_token() == ""


def test_environment_token_is_a_developer_override(monkeypatch) -> None:
    monkeypatch.setenv("TODOIST_API_TOKEN", "from-environment")
    monkeypatch.setattr(
        settings_service,
        "_keyring_module",
        lambda: SimpleNamespace(get_password=lambda *_: "from-vault"),
    )

    assert settings_service.get_todoist_token() == "from-environment"
    assert settings_service.get_todoist_token_source() == "environment"


def test_todoist_tokens_are_scoped_to_cloud_account(monkeypatch) -> None:
    vault = FakeKeyring()
    monkeypatch.delenv("TODOIST_API_TOKEN", raising=False)
    monkeypatch.setattr(settings_service, "_keyring_module", lambda: vault)

    settings_service.save_todoist_token("local-token")
    monkeypatch.setenv("FOCUS_CLOUD_USER_ID", "account-a")
    assert settings_service.get_todoist_token() == ""
    settings_service.save_todoist_token("account-token")

    monkeypatch.delenv("FOCUS_CLOUD_USER_ID")
    assert settings_service.get_todoist_token() == "local-token"
    monkeypatch.setenv("FOCUS_CLOUD_USER_ID", "account-a")
    assert settings_service.get_todoist_token() == "account-token"


def test_credential_store_label_matches_platform(monkeypatch) -> None:
    monkeypatch.setattr(settings_service.sys, "platform", "darwin")
    assert settings_service.credential_store_label() == "macOS Keychain"

    monkeypatch.setattr(settings_service.sys, "platform", "win32")
    assert settings_service.credential_store_label() == "Windows Credential Manager"


def test_calendar_subscription_urls_round_trip_and_are_account_scoped(
    monkeypatch,
) -> None:
    vault = FakeKeyring()
    monkeypatch.setattr(settings_service, "_keyring_module", lambda: vault)
    monkeypatch.delenv("FOCUS_CLOUD_USER_ID", raising=False)

    settings_service.save_calendar_feed_url(
        "work",
        "https://calendar.example.com/private.ics",
    )
    assert settings_service.get_calendar_feed_urls() == {
        "work": "https://calendar.example.com/private.ics"
    }

    monkeypatch.setenv("FOCUS_CLOUD_USER_ID", "account-a")
    assert settings_service.get_calendar_feed_urls() == {}
    settings_service.save_calendar_feed_url(
        "personal",
        "https://calendar.example.com/personal.ics",
    )
    settings_service.remove_calendar_feed_url("personal")
    assert settings_service.get_calendar_feed_urls() == {}

    monkeypatch.delenv("FOCUS_CLOUD_USER_ID")
    assert "work" in settings_service.get_calendar_feed_urls()

    with pytest.raises(ValueError, match="HTTPS"):
        settings_service.save_calendar_feed_url("unsafe", "http://example.com/a.ics")

    settings_service.save_calendar_feed_url(
        "webcal",
        "webcal://calendar.example.com/a.ics",
    )
    assert settings_service.get_calendar_feed_urls()["webcal"].startswith("https://")
