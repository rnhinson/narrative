"""
In-memory store for active voting sessions.

Session shape:
    session_id:     str           — "{channel_id}:{message_ts}"
    channel_id:     str
    message_ts:     str           — Slack message timestamp
    issue_key:      str
    issue_summary:  str
    issue_url:      str
    votes:          dict[user_id, {"user_name": str, "value": str}]
    revealed:       bool
    updated:        bool
    initiated_by:   str           — user_id who started the vote
    override_points: str | None   — selected value when no consensus
    issue_description: str        — flattened Jira description text
    issue_reporter: str           — Jira reporter display name
    description_expanded: bool    — whether the card is showing the description
    original_state: dict | None   — pre-update snapshot for revert
    reverted: bool                — whether the Jira update was reverted
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    channel_id: str
    message_ts: str
    issue_key: str
    issue_summary: str
    issue_url: str
    initiated_by: str
    votes: dict = field(default_factory=dict)
    revealed: bool = False
    updated: bool = False
    override_points: str | None = None
    issue_description: str = ""
    issue_reporter: str = ""
    description_expanded: bool = False
    original_state: dict | None = None  # pre-update {status, labels, story_points}
    reverted: bool = False


@dataclass
class VoteStats:
    vote_count: int
    all_agree: bool
    agreed_value: str | None
    distribution: dict[str, int]


# Module-level store
_sessions: dict[str, Session] = {}


def create_session(
    channel_id: str,
    message_ts: str,
    issue_key: str,
    issue_summary: str,
    issue_url: str,
    initiated_by: str,
    issue_description: str = "",
    issue_reporter: str = "",
) -> Session:
    session_id = f"{channel_id}:{message_ts}"
    session = Session(
        session_id=session_id,
        channel_id=channel_id,
        message_ts=message_ts,
        issue_key=issue_key,
        issue_summary=issue_summary,
        issue_url=issue_url,
        initiated_by=initiated_by,
        issue_description=issue_description,
        issue_reporter=issue_reporter,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def get_session_by_message(channel_id: str, message_ts: str) -> Session | None:
    return _sessions.get(f"{channel_id}:{message_ts}")


def add_vote(
    session_id: str, user_id: str, user_name: str, value: str
) -> Session | None:
    session = _sessions.get(session_id)
    if not session:
        return None
    session.votes[user_id] = {"user_name": user_name, "value": value}
    return session


def set_revealed(session_id: str) -> Session | None:
    session = _sessions.get(session_id)
    if session:
        session.revealed = True
    return session


def set_updated(session_id: str) -> Session | None:
    session = _sessions.get(session_id)
    if session:
        session.updated = True
    return session


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def get_vote_stats(session: Session) -> VoteStats:
    values = [v["value"] for v in session.votes.values()]
    vote_count = len(values)
    distribution: dict[str, int] = {}
    for v in values:
        distribution[v] = distribution.get(v, 0) + 1
    unique = list(set(values))
    all_agree = vote_count > 0 and len(unique) == 1
    agreed_value = unique[0] if all_agree else None
    return VoteStats(
        vote_count=vote_count,
        all_agree=all_agree,
        agreed_value=agreed_value,
        distribution=distribution,
    )
