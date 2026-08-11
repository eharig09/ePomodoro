from __future__ import annotations

import os
import sys


CREDENTIAL_SERVICE = "Focus Productivity App"
CREDENTIAL_USERNAME = "todoist_api_token"


class CredentialStoreError(RuntimeError):
    """A user-safe error raised when credentials cannot be stored securely."""


def credential_store_label() -> str:
    if sys.platform == "win32":
        return "Windows Credential Manager"
    if sys.platform == "darwin":
        return "macOS Keychain"
    return "the system credential store"


def _keyring_module():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - guarded by packaged dependencies
        raise CredentialStoreError(
            "Secure credential storage is unavailable. Reinstall Focus and try again."
        ) from exc
    return keyring


def _credential_username() -> str:
    """Keep each cloud account's optional Todoist credential isolated."""
    user_id = os.getenv("FOCUS_CLOUD_USER_ID", "").strip()
    return f"{CREDENTIAL_USERNAME}:{user_id}" if user_id else CREDENTIAL_USERNAME


def get_todoist_token() -> str:
    """Return a developer override or the token in the operating-system vault."""
    environment_token = os.getenv("TODOIST_API_TOKEN", "").strip()
    if environment_token:
        return environment_token
    try:
        return (_keyring_module().get_password(
            CREDENTIAL_SERVICE, _credential_username()
        ) or "").strip()
    except Exception:
        # A broken or locked credential vault should never prevent local-only use.
        return ""


def get_todoist_token_source() -> str:
    if os.getenv("TODOIST_API_TOKEN", "").strip():
        return "environment"
    return "credential" if get_todoist_token() else "none"


def save_todoist_token(token: str) -> None:
    clean_token = token.strip()
    if not clean_token:
        raise ValueError("Enter a Todoist API token")
    try:
        _keyring_module().set_password(
            CREDENTIAL_SERVICE, _credential_username(), clean_token
        )
    except Exception as exc:
        raise CredentialStoreError(
            f"Focus could not save the token in {credential_store_label()}."
        ) from exc


def remove_todoist_token() -> None:
    keyring = _keyring_module()
    try:
        keyring.delete_password(CREDENTIAL_SERVICE, _credential_username())
    except keyring.errors.PasswordDeleteError:
        return
    except Exception as exc:
        raise CredentialStoreError(
            f"Focus could not remove the token from {credential_store_label()}."
        ) from exc
