"""
Per-channel configuration store.

Persists overrides to {DATA_DIR}/config-store.json so they survive restarts.
Falls back to org-wide .env values for any field not explicitly set.
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent))
STORE_PATH = DATA_DIR / "config-store.json"

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
    # Empty list = allow any project (backward-compatible default).
    "allowed_projects": [
        pk.strip().upper()
        for pk in os.environ.get("JIRA_ALLOWED_PROJECTS", "").split(",")
        if pk.strip()
    ],
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
