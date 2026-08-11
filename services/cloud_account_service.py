from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from database.db import DEFAULT_DB_PATH


CLOUD_CREDENTIAL_SERVICE = "ePomodoro Cloud"
CLOUD_CREDENTIAL_USERNAME = "session"


class CloudAccountError(RuntimeError):
    pass


class CloudConfigurationError(CloudAccountError):
    pass


@dataclass(frozen=True, slots=True)
class CloudConfig:
    url: str
    publishable_key: str

    @classmethod
    def from_environment(cls) -> CloudConfig | None:
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        if not url and not key:
            url, key = _bundled_config_values()
        if not url and not key:
            return None
        if not url or not key:
            raise CloudConfigurationError(
                "Set both SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY."
            )
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise CloudConfigurationError("SUPABASE_URL must be a clean HTTPS URL.")
        _reject_privileged_key(key)
        return cls(url=url, publishable_key=key)


def _bundled_config_values() -> tuple[str, str]:
    config_path = Path(__file__).resolve().parents[1] / "cloud_config.json"
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return "", ""
    if not isinstance(values, dict):
        return "", ""
    return (
        str(values.get("supabase_url") or "").strip().rstrip("/"),
        str(values.get("supabase_publishable_key") or "").strip(),
    )


@dataclass(frozen=True, slots=True)
class CloudSession:
    access_token: str
    refresh_token: str
    user_id: str
    email: str
    expires_at: str

    @property
    def expires_soon(self) -> bool:
        try:
            expires = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return True
        return expires <= datetime.now(timezone.utc) + timedelta(minutes=2)


Transport = Callable[
    [str, str, dict[str, str], bytes | None],
    tuple[int, object],
]


def _keyring_module():
    import keyring

    return keyring


def _reject_privileged_key(key: str) -> None:
    if "service_role" in key.casefold():
        raise CloudConfigurationError("A service-role key must never be used in an app.")
    parts = key.split(".")
    if len(parts) != 3:
        return
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if claims.get("role") == "service_role":
        raise CloudConfigurationError("A service-role key must never be used in an app.")


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> tuple[int, object]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read()
        try:
            parsed: object = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        return exc.code, parsed
    except (URLError, TimeoutError, OSError) as exc:
        raise CloudAccountError("Could not reach the sync service.") from exc


class CloudAccountService:
    def __init__(
        self,
        config: CloudConfig,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _default_transport

    def sign_up(self, email: str, password: str) -> CloudSession | None:
        clean_email, clean_password = _validate_credentials(email, password)
        response = self.request_json(
            "POST",
            "/auth/v1/signup",
            payload={"email": clean_email, "password": clean_password},
        )
        session = _session_from_response(response)
        if session is not None:
            save_cloud_session(session)
        return session

    def sign_in(self, email: str, password: str) -> CloudSession:
        clean_email, clean_password = _validate_credentials(email, password)
        response = self.request_json(
            "POST",
            "/auth/v1/token?grant_type=password",
            payload={"email": clean_email, "password": clean_password},
        )
        session = _session_from_response(response)
        if session is None:
            raise CloudAccountError("The sync service did not return a user session.")
        save_cloud_session(session)
        return session

    def refresh(self, session: CloudSession) -> CloudSession:
        response = self.request_json(
            "POST",
            "/auth/v1/token?grant_type=refresh_token",
            payload={"refresh_token": session.refresh_token},
        )
        refreshed = _session_from_response(response)
        if refreshed is None:
            raise CloudAccountError("The account session could not be refreshed.")
        save_cloud_session(refreshed)
        return refreshed

    def authorized_json(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> object:
        session = get_cloud_session()
        if session is None:
            raise CloudAccountError("Sign in before syncing.")
        if session.expires_soon:
            session = self.refresh(session)
        try:
            return self.request_json(
                method,
                path,
                payload=payload,
                access_token=session.access_token,
                extra_headers=extra_headers,
            )
        except _UnauthorizedError:
            session = self.refresh(session)
            return self.request_json(
                method,
                path,
                payload=payload,
                access_token=session.access_token,
                extra_headers=extra_headers,
            )

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        access_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> object:
        headers = {
            "apikey": self.config.publishable_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        status, response = self._transport(
            method,
            f"{self.config.url}{path}",
            headers,
            body,
        )
        if status == 401 and access_token:
            raise _UnauthorizedError
        if not 200 <= status < 300:
            message = _error_message(response) or f"Cloud request failed ({status})."
            raise CloudAccountError(message)
        return response


class _UnauthorizedError(RuntimeError):
    pass


def _validate_credentials(email: str, password: str) -> tuple[str, str]:
    clean_email = email.strip().casefold()
    if "@" not in clean_email or len(clean_email) > 254:
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Use a password with at least 8 characters.")
    return clean_email, password


def _session_from_response(response: object) -> CloudSession | None:
    if not isinstance(response, dict) or not response.get("access_token"):
        return None
    user = response.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        return None
    expires_in = max(60, int(response.get("expires_in", 3600)))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return CloudSession(
        access_token=str(response["access_token"]),
        refresh_token=str(response["refresh_token"]),
        user_id=str(user["id"]),
        email=str(user.get("email") or ""),
        expires_at=expires_at.isoformat(),
    )


def _error_message(response: object) -> str:
    if isinstance(response, dict):
        for key in ("msg", "message", "error_description", "error"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(response).strip() if isinstance(response, str) else ""


def save_cloud_session(session: CloudSession) -> None:
    try:
        _keyring_module().set_password(
            CLOUD_CREDENTIAL_SERVICE,
            CLOUD_CREDENTIAL_USERNAME,
            json.dumps(asdict(session)),
        )
    except Exception as exc:
        raise CloudAccountError("Could not save the account in the secure vault.") from exc


def get_cloud_session() -> CloudSession | None:
    try:
        raw = _keyring_module().get_password(
            CLOUD_CREDENTIAL_SERVICE,
            CLOUD_CREDENTIAL_USERNAME,
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        values = json.loads(raw)
        return CloudSession(**values)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def remove_cloud_session() -> None:
    keyring = _keyring_module()
    try:
        keyring.delete_password(CLOUD_CREDENTIAL_SERVICE, CLOUD_CREDENTIAL_USERNAME)
    except keyring.errors.PasswordDeleteError:
        return
    except Exception as exc:
        raise CloudAccountError("Could not remove the account from the secure vault.") from exc


def base_database_path() -> Path:
    configured = os.getenv("FOCUS_BASE_DB_PATH") or os.getenv("FOCUS_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH


def profile_database_path(user_id: str) -> Path:
    safe_id = str(UUID(user_id))
    base = base_database_path()
    return base.parent / "profiles" / safe_id / base.name


def activate_cloud_profile(user_id: str, *, import_local: bool = False) -> Path:
    base = base_database_path()
    os.environ.setdefault("FOCUS_BASE_DB_PATH", str(base))
    target = profile_database_path(user_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if import_local and base.exists() and not target.exists():
        shutil.copy2(base, target)
    os.environ["FOCUS_DB_PATH"] = str(target)
    os.environ["FOCUS_CLOUD_USER_ID"] = str(UUID(user_id))
    return target


def activate_stored_cloud_profile() -> CloudSession | None:
    session = get_cloud_session()
    if session is not None:
        activate_cloud_profile(session.user_id)
    return session


def restore_local_profile() -> Path:
    base = base_database_path()
    os.environ["FOCUS_DB_PATH"] = str(base)
    os.environ.pop("FOCUS_CLOUD_USER_ID", None)
    return base
