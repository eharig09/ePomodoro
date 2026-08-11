from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import cloud_account_service as cloud_accounts
from services.cloud_account_service import (
    CloudAccountService,
    CloudConfig,
    CloudConfigurationError,
    activate_cloud_profile,
    restore_local_profile,
)
from database.db import create_goal, get_daily_reflections, get_goals, init_db, save_daily_reflection
from datetime import date


def test_cloud_config_requires_public_https_credentials(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-key")
    assert CloudConfig.from_environment() == CloudConfig(
        url="https://example.supabase.co",
        publishable_key="publishable-key",
    )

    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "service_role-secret")
    with pytest.raises(CloudConfigurationError, match="service-role"):
        CloudConfig.from_environment()


def test_sign_in_uses_publishable_key_and_saves_session(monkeypatch) -> None:
    captured: list[tuple[str, str, dict[str, str], object]] = []
    saved = []

    def transport(method, url, headers, body):
        captured.append((method, url, headers, json.loads(body)))
        return 200, {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "user": {"id": "8bb3ed5f-f2df-44e7-a457-e180f433fa30", "email": "me@example.com"},
        }

    monkeypatch.setattr(cloud_accounts, "save_cloud_session", saved.append)
    service = CloudAccountService(
        CloudConfig("https://example.supabase.co", "public-key"),
        transport=transport,
    )
    session = service.sign_in(" ME@example.com ", "password123")

    assert session.user_id == "8bb3ed5f-f2df-44e7-a457-e180f433fa30"
    assert saved == [session]
    assert captured[0][1].endswith("/auth/v1/token?grant_type=password")
    assert captured[0][2]["apikey"] == "public-key"
    assert captured[0][3] == {"email": "me@example.com", "password": "password123"}


def test_account_profiles_are_isolated_and_import_is_explicit(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "focus.db"
    base.write_bytes(b"local database")
    monkeypatch.setenv("FOCUS_DB_PATH", str(base))
    monkeypatch.delenv("FOCUS_BASE_DB_PATH", raising=False)

    account_id = "8bb3ed5f-f2df-44e7-a457-e180f433fa30"
    target = activate_cloud_profile(account_id, import_local=True)

    assert target != base
    assert target.read_bytes() == b"local database"
    assert target.parent.name == account_id
    assert Path(cloud_accounts.os.environ["FOCUS_DB_PATH"]) == target
    assert cloud_accounts.os.environ["FOCUS_CLOUD_USER_ID"] == account_id
    assert restore_local_profile() == base
    assert "FOCUS_CLOUD_USER_ID" not in cloud_accounts.os.environ


def test_import_merges_missing_data_into_existing_profile(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "focus.db"
    init_db(base)
    save_daily_reflection(date(2026, 8, 10), mood=4, journal="Recovered", db_path=base)
    monkeypatch.setenv("FOCUS_DB_PATH", str(base))
    monkeypatch.delenv("FOCUS_BASE_DB_PATH", raising=False)
    account_id = "8bb3ed5f-f2df-44e7-a457-e180f433fa30"
    target = cloud_accounts.profile_database_path(account_id)
    init_db(target)
    create_goal("Keep this goal", db_path=target)

    activate_cloud_profile(account_id, import_local=True)

    assert get_daily_reflections(target)[0].journal == "Recovered"
    assert get_goals(target)[0].name == "Keep this goal"
    restore_local_profile()
