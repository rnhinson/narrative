"""
Narrative — Slack Bolt (Python) entry point.

Run with:
    python src/app.py

Environment variables are loaded from .env via python-dotenv.
"""

import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import store
import jira as jira_client
import config as channel_config
from blocks import (
    POINT_VALUES,
    build_voting_message,
    build_config_modal,
    build_config_saved_message,
    build_config_reset_message,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App initialisation ────────────────────────────────────────────────────────
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)


# ── /point ────────────────────────────────────────────────────────────────────
@app.command("/point")
def handle_point(ack, command, respond, client):
    ack()

    issue_key = command["text"].strip().upper()

    if not issue_key or not re.match(r"^[A-Z]+-\d+$", issue_key):
        respond(
            response_type="ephemeral",
            text="❌ Please provide a valid Jira issue key. Example: `/point PROJ-123`",
        )
        return

    cfg = channel_config.get_channel_config(command["channel_id"])

    try:
        issue = jira_client.get_issue(issue_key, cfg)
    except Exception as exc:
        logger.error("Jira fetch error: %s", exc)
        respond(
            response_type="ephemeral",
            text=f"❌ Could not fetch Jira issue *{issue_key}*. Check the key and your Jira credentials.\n`{exc}`",
        )
        return

    # Post a placeholder message first to get the timestamp
    placeholder_session = store.Session(
        session_id="pending",
        channel_id=command["channel_id"],
        message_ts="",
        issue_key=issue["key"],
        issue_summary=issue["summary"],
        issue_url=issue["url"],
        initiated_by=command["user_id"],
    )
    placeholder_stats = store.VoteStats(vote_count=0, all_agree=False, agreed_value=None, distribution={})

    try:
        posted = client.chat_postMessage(
            channel=command["channel_id"],
            text=f"Story point vote for {issue_key}",
            blocks=build_voting_message(placeholder_session, placeholder_stats),
        )
    except Exception as exc:
        logger.error("Slack post error: %s", exc)
        respond(response_type="ephemeral", text="❌ Failed to post the voting message to this channel.")
        return

    # Create the real session with the message ts
    session = store.create_session(
        channel_id=command["channel_id"],
        message_ts=posted["ts"],
        issue_key=issue["key"],
        issue_summary=issue["summary"],
        issue_url=issue["url"],
        initiated_by=command["user_id"],
    )
    stats = store.get_vote_stats(session)

    # Update with real session ID baked into button values
    client.chat_update(
        channel=command["channel_id"],
        ts=posted["ts"],
        text=f"Story point vote for {issue_key}",
        blocks=build_voting_message(session, stats),
    )


# ── Vote buttons ──────────────────────────────────────────────────────────────
def _make_vote_handler(pts: str):
    def handler(ack, action, body, client):
        ack()
        channel_id = body["channel"]["id"]
        message_ts = body["message"]["ts"]
        user_id = body["user"]["id"]
        user_name = body["user"].get("username", user_id)

        session = store.get_session_by_message(channel_id, message_ts)
        if not session:
            _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found. Please start a new vote.")
            return

        if session.revealed:
            _post_ephemeral(client, channel_id, user_id, message_ts, "Votes have already been revealed. Use *Re-vote* to start a new round.")
            return

        store.add_vote(session.session_id, user_id, user_name, action["value"])
        updated = store.get_session(session.session_id)
        stats = store.get_vote_stats(updated)

        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"Story point vote for {session.issue_key}",
            blocks=build_voting_message(updated, stats),
        )
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            f"You voted *{action['value']}* for {session.issue_key}. You can change your vote anytime before reveal.",
        )

    return handler


for _pts in POINT_VALUES:
    app.action(f"vote_{_pts}")(_make_vote_handler(_pts))


# ── Reveal votes ──────────────────────────────────────────────────────────────
@app.action("reveal_votes")
def handle_reveal(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    user_id = body["user"]["id"]
    session_id = action["value"]

    session = store.get_session(session_id)
    if not session:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found.")
        return

    if not session.votes:
        _post_ephemeral(client, channel_id, user_id, message_ts, "No votes have been cast yet!")
        return

    store.set_revealed(session_id)
    updated = store.get_session(session_id)
    stats = store.get_vote_stats(updated)

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key} — revealed!",
        blocks=build_voting_message(updated, stats),
    )


# ── Re-vote ───────────────────────────────────────────────────────────────────
@app.action("revote")
def handle_revote(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    session_id = action["value"]

    session = store.get_session(session_id)
    if not session:
        return

    session.votes = {}
    session.revealed = False
    session.override_points = None
    stats = store.get_vote_stats(session)

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key} — re-voting",
        blocks=build_voting_message(session, stats),
    )


# ── Point override dropdown ───────────────────────────────────────────────────
@app.action("select_override_points")
def handle_select_override(ack, action, body):
    ack()
    value = action["selected_option"]["value"]  # "session_id::pts"
    session_id, point_value = value.split("::", 1)
    session = store.get_session(session_id)
    if session:
        session.override_points = point_value


# ── Update Jira (consensus path) ──────────────────────────────────────────────
@app.action("update_jira")
def handle_update_jira(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    user_id = body["user"]["id"]
    session_id, point_value = action["value"].split("::", 1)
    _perform_jira_update(client, channel_id, message_ts, user_id, session_id, point_value)


# ── Update Jira (no-consensus / override path) ────────────────────────────────
@app.action("update_jira_override")
def handle_update_jira_override(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    user_id = body["user"]["id"]
    session_id = action["value"]

    session = store.get_session(session_id)
    if not session:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found.")
        return

    if not session.override_points:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Please select a point value from the dropdown before updating Jira.")
        return

    _perform_jira_update(client, channel_id, message_ts, user_id, session_id, session.override_points)


def _perform_jira_update(client, channel_id, message_ts, user_id, session_id, point_value):
    session = store.get_session(session_id)
    if not session:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found.")
        return

    if session.updated:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Jira has already been updated for this session.")
        return

    cfg = channel_config.get_channel_config(session.channel_id)
    try:
        jira_client.update_issue(session.issue_key, point_value, cfg)
    except Exception as exc:
        logger.error("Jira update error: %s", exc)
        _post_ephemeral(client, channel_id, user_id, message_ts, f"Failed to update Jira: `{exc}`")
        return

    store.set_updated(session_id)
    updated = store.get_session(session_id)
    stats = store.get_vote_stats(updated)
    # Patch agreed_value so the confirmation banner renders the right number
    stats = store.VoteStats(
        vote_count=stats.vote_count,
        all_agree=stats.all_agree,
        agreed_value=point_value,
        distribution=stats.distribution,
    )

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key} — complete!",
        blocks=build_voting_message(updated, stats),
    )


# ── /point-config ─────────────────────────────────────────────────────────────
@app.command("/point-config")
def handle_point_config(ack, command, client):
    ack()
    config = channel_config.get_channel_config(command["channel_id"])
    org_defaults = channel_config.get_org_defaults()

    client.views_open(
        trigger_id=command["trigger_id"],
        view=build_config_modal(command["channel_id"], config, org_defaults),
    )


# ── Config modal submit ───────────────────────────────────────────────────────
@app.view("point_config_submit")
def handle_config_submit(ack, view, body, client):
    ack()
    channel_id = view["private_metadata"]
    values = view["state"]["values"]

    target_status = values["target_status"]["value"]["value"].strip()
    labels_raw = (values["labels_to_remove"]["value"]["value"] or "").strip()
    labels_to_remove = [lb.strip() for lb in labels_raw.split(",") if lb.strip()]
    story_points_field = values["story_points_field"]["value"]["value"].strip()

    saved = channel_config.set_channel_config(
        channel_id,
        {"target_status": target_status, "labels_to_remove": labels_to_remove, "story_points_field": story_points_field},
        body["user"]["id"],
    )

    client.chat_postEphemeral(
        channel=channel_id,
        user=body["user"]["id"],
        text="Config saved for this channel.",
        blocks=build_config_saved_message(saved),
    )


# ── Reset channel config ──────────────────────────────────────────────────────
@app.action("reset_channel_config")
def handle_reset_config(ack, action, body, client):
    ack()
    channel_id = action["value"]
    channel_config.reset_channel_config(channel_id)

    client.views_update(
        view_id=body["view"]["id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Config reset"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "↩️ *Channel config reset.* This channel will now use the org-wide defaults from `.env`."}}],
        },
    )
    client.chat_postEphemeral(
        channel=channel_id,
        user=body["user"]["id"],
        text="Channel config has been reset to org defaults.",
        blocks=build_config_reset_message(),
    )


# ── Helper ────────────────────────────────────────────────────────────────────
def _post_ephemeral(client, channel_id, user_id, thread_ts, text):
    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            thread_ts=thread_ts,
            text=text,
        )
    except Exception as exc:
        logger.warning("Ephemeral post failed: %s", exc)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("⚡️ Starting Narrative in Socket Mode")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
