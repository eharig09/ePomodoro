from __future__ import annotations

from types import SimpleNamespace

from services import settings_service


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self) -> None:
        self.password: str | None = None

    def get_password(self, service: str, username: str) -> str | None:
        return self.password

    def set_password(self, service: str, username: str, password: str) -> None:
        self.password = password

    def delete_password(self, service: str, username: str) -> None:
        if self.password is None:
            raise self.errors.PasswordDeleteError()
        self.password = None


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


def test_credential_store_label_matches_platform(monkeypatch) -> None:
    monkeypatch.setattr(settings_service.sys, "platform", "darwin")
    assert settings_service.credential_store_label() == "macOS Keychain"

    monkeypatch.setattr(settings_service.sys, "platform", "win32")
    assert settings_service.credential_store_label() == "Windows Credential Manager"
