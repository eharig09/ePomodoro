from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse, urlunparse


CREDENTIAL_SERVICE = "Focus Productivity App"
CREDENTIAL_USERNAME = "todoist_api_token"
CALENDAR_CREDENTIAL_USERNAME = "calendar_subscription_urls"


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


def _credential_username(base_username: str = CREDENTIAL_USERNAME) -> str:
    """Keep each cloud account's optional credentials isolated."""
    user_id = os.getenv("FOCUS_CLOUD_USER_ID", "").strip()
    return f"{base_username}:{user_id}" if user_id else base_username


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


def get_calendar_feed_urls() -> dict[str, str]:
    """Return source-to-URL mappings from the operating-system vault."""
    try:
        raw = _keyring_module().get_password(
            CREDENTIAL_SERVICE,
            _credential_username(CALENDAR_CREDENTIAL_USERNAME),
        )
        decoded = json.loads(raw) if raw else {}
    except Exception:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(source_id): str(url)
        for source_id, url in decoded.items()
        if str(source_id).strip() and str(url).strip()
    }


def save_calendar_feed_url(source_id: str, url: str) -> None:
    clean_id = source_id.strip()
    clean_url = url.strip()
    if not clean_id or len(clean_id) > 100:
        raise ValueError("Calendar source ID is invalid")
    try:
        parsed = urlparse(clean_url)
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS iCalendar URL") from exc
    if parsed.scheme.lower() == "webcal":
        parsed = parsed._replace(scheme="https")
        clean_url = urlunparse(parsed)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Enter a valid HTTPS iCalendar URL")
    feeds = get_calendar_feed_urls()
    feeds[clean_id] = clean_url
    try:
        _keyring_module().set_password(
            CREDENTIAL_SERVICE,
            _credential_username(CALENDAR_CREDENTIAL_USERNAME),
            json.dumps(feeds, sort_keys=True),
        )
    except Exception as exc:
        raise CredentialStoreError(
            f"Focus could not save the calendar link in {credential_store_label()}."
        ) from exc


def remove_calendar_feed_url(source_id: str) -> None:
    feeds = get_calendar_feed_urls()
    feeds.pop(source_id.strip(), None)
    keyring = _keyring_module()
    username = _credential_username(CALENDAR_CREDENTIAL_USERNAME)
    try:
        if feeds:
            keyring.set_password(
                CREDENTIAL_SERVICE,
                username,
                json.dumps(feeds, sort_keys=True),
            )
        else:
            keyring.delete_password(CREDENTIAL_SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        return
    except Exception as exc:
        raise CredentialStoreError(
            f"Focus could not remove the calendar link from {credential_store_label()}."
        ) from exc
