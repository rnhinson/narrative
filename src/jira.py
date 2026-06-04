"""
Jira REST API client.

Org-wide credentials (base URL, email, API token) come from environment
variables. Per-channel settings (story points field, labels to remove,
target status) are passed in as a ChannelConfig at call time.
"""

from __future__ import annotations
import os
import httpx

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

_AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def get_issue(issue_key: str, channel_config) -> dict:
    """
    Fetch summary, labels, status and story-points for an issue.
    Returns a plain dict: {key, summary, labels, status, story_points, url}
    """
    field = channel_config["story_points_field"]
    url = (
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
        f"?fields=summary,labels,status,{field}"
    )
    resp = httpx.get(url, auth=_AUTH, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    fields = resp.json()["fields"]
    return {
        "key": issue_key,
        "summary": fields.get("summary", ""),
        "labels": fields.get("labels", []),
        "status": (fields.get("status") or {}).get("name"),
        "story_points": fields.get(field),
        "url": f"{JIRA_BASE_URL}/browse/{issue_key}",
    }


def _get_transitions(issue_key: str) -> list[dict]:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    resp = httpx.get(url, auth=_AUTH, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["transitions"]


def update_issue(issue_key: str, story_points: str, channel_config) -> dict:
    """
    1. Set story points on the ticket.
    2. Remove the configured labels.
    3. Transition the ticket to the configured target status.

    Returns a summary dict of what was done.
    """
    story_points_field = channel_config["story_points_field"]
    labels_to_remove = channel_config["labels_to_remove"]
    target_status = channel_config["target_status"]

    # Current issue state
    issue = get_issue(issue_key, channel_config)
    new_labels = [lb for lb in issue["labels"] if lb not in labels_to_remove]

    # Update fields
    issue_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    resp = httpx.put(
        issue_url,
        auth=_AUTH,
        headers=_HEADERS,
        json={"fields": {story_points_field: int(story_points), "labels": new_labels}},
        timeout=10,
    )
    resp.raise_for_status()

    # Find and execute transition
    transitions = _get_transitions(issue_key)
    match = next(
        (t for t in transitions if t["name"].lower() == target_status.lower()), None
    )
    if not match:
        available = ", ".join(t["name"] for t in transitions)
        raise ValueError(
            f'Transition "{target_status}" not found. Available: {available}'
        )

    resp = httpx.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions",
        auth=_AUTH,
        headers=_HEADERS,
        json={"transition": {"id": match["id"]}},
        timeout=10,
    )
    resp.raise_for_status()

    return {
        "story_points": story_points,
        "removed_labels": [lb for lb in labels_to_remove if lb in issue["labels"]],
        "new_status": target_status,
        "url": issue["url"],
    }
