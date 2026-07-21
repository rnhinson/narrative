"""
Per-channel configuration store.

Persists overrides to {DATA_DIR}/config-store.json so they survive restarts.
Falls back to org-wide .env values for any field not explicitly set.

The per-channel Jira API token is a real credential, unlike the rest of this
file's settings, so it's encrypted at rest with a Fernet key from
CONFIG_ENCRYPTION_KEY before ever touching disk. The org-wide JIRA_API_TOKEN
fallback lives only in the environment (never written to config-store.json),
so it doesn't need this.
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent))
STORE_PATH = DATA_DIR / "config-store.json"

_ENCRYPTION_KEY = os.environ.get("CONFIG_ENCRYPTION_KEY", "")
_cipher = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None


class EncryptionNotConfigured(RuntimeError):
    """A channel-specific Jira token was submitted, but CONFIG_ENCRYPTION_KEY
    isn't set, so it can't be stored securely."""


def encrypt_token(raw: str) -> str:
    if not _cipher:
        raise EncryptionNotConfigured(
            "CONFIG_ENCRYPTION_KEY is not set -- ask an admin to configure it "
            "before saving a channel-specific Jira API token."
        )
    return _cipher.encrypt(raw.encode()).decode()


def _decrypt_token(value: str) -> str:
    if not value or not _cipher:
        # No stored value, or no key to read it with -- fail closed (blank)
        # rather than raise on every config lookup.
        return ""
    try:
        return _cipher.decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


# Org-wide defaults — read once at import time
_ORG_DEFAULTS = {
    "target_status": os.environ.get("JIRA_TARGET_STATUS", "Ready for Sprint"),
    "labels_to_remove": [
        lb.strip()
        for lb in os.environ.get("JIRA_LABELS_TO_REMOVE", "").split(",")
        if lb.strip()
    ],
    "story_points_field": os.environ.get(
        "JIRA_STORY_POINTS_FIELD", "customfield_10016"
    ),
    # Project short codes this channel may point (e.g. ["PLAT", "INFRA"]).
    # Empty here means "no org-wide default" -- each channel must then set
    # its own via /point-config before /point will work (see app.py's
    # handle_point). Set this to give every channel a default set instead
    # of requiring per-channel setup.
    "allowed_projects": [
        pk.strip().upper()
        for pk in os.environ.get("JIRA_ALLOWED_PROJECTS", "").split(",")
        if pk.strip()
    ],
    # Org-wide Jira identity, used as the fallback when a channel hasn't
    # configured its own via /point-config. Plain env vars, not written to
    # config-store.json, so they don't need encryption.
    "jira_email": os.environ.get("JIRA_EMAIL", ""),
    "jira_api_token": os.environ.get("JIRA_API_TOKEN", ""),
}

# In-memory cache
_store: dict = {}


def _load() -> None:
    global _store
    try:
        if STORE_PATH.exists():
            _store = json.loads(STORE_PATH.read_text())
    except Exception as exc:
        print(f"Config store read error: {exc}")
        _store = {}


def _save() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STORE_PATH.write_text(json.dumps(_store, indent=2))
    except Exception as exc:
        print(f"Config store write error: {exc}")


# Load on import
_load()


def get_channel_config(channel_id: str) -> dict:
    """
    Return the effective config for a channel, merging saved overrides
    with org-wide defaults.
    """
    saved = _store.get(channel_id, {})
    saved_token = saved.get("jira_api_token")  # stored encrypted, or absent
    return {
        "target_status": saved.get(
            "target_status", _ORG_DEFAULTS["target_status"]
        ),
        "labels_to_remove": saved.get(
            "labels_to_remove", _ORG_DEFAULTS["labels_to_remove"]
        ),
        "story_points_field": saved.get(
            "story_points_field", _ORG_DEFAULTS["story_points_field"]
        ),
        "allowed_projects": saved.get(
            "allowed_projects", _ORG_DEFAULTS["allowed_projects"]
        ),
        "jira_email": saved.get("jira_email", _ORG_DEFAULTS["jira_email"]),
        "jira_api_token": (
            _decrypt_token(saved_token) if saved_token
            else _ORG_DEFAULTS["jira_api_token"]
        ),
        # Whether THIS channel has its own token configured, distinct from
        # inheriting the org-wide one -- lets the UI show accurate status
        # without ever echoing the decrypted token back.
        "has_channel_token": bool(saved_token),
        "updated_by": saved.get("updated_by"),
        "updated_at": saved.get("updated_at"),
        "is_customized": channel_id in _store,
    }


def set_channel_config(channel_id: str, updates: dict, user_id: str) -> dict:
    existing = _store.get(channel_id, {})
    _store[channel_id] = {
        **existing,
        **updates,
        "updated_by": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save()
    return get_channel_config(channel_id)


def reset_channel_config(channel_id: str) -> None:
    _store.pop(channel_id, None)
    _save()


def get_org_defaults() -> dict:
    return dict(_ORG_DEFAULTS)
