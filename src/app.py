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

from slack_bolt import App  # noqa: E402
from slack_bolt.adapter.socket_mode import SocketModeHandler  # noqa: E402

import store  # noqa: E402
import jira as jira_client  # noqa: E402
import config as channel_config  # noqa: E402
from blocks import (  # noqa: E402
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

    # Project scoping is required, not optional: a channel must explicitly
    # allow-list its Jira project(s) via /point-config before /point works
    # at all -- prevents pointing tickets into the wrong project by default.
    allowed_projects = cfg.get("allowed_projects") or []
    if not allowed_projects:
        respond(
            response_type="ephemeral",
            text=(
                "🔒 This channel hasn't been set up for pointing yet. Run "
                "`/point-config` and add your team's Jira project(s) under "
                "*Allowed Jira projects* first."
            ),
        )
        return

    project_key = issue_key.split("-", 1)[0]
    if project_key not in allowed_projects:
        respond(
            response_type="ephemeral",
            text=(
                f"🔒 This channel is scoped to "
                f"{', '.join(f'`{p}`' for p in allowed_projects)}. "
                f"*{issue_key}* is in project `{project_key}`, which isn't "
                "allowed here. Run `/point-config` to change the allowed projects."
            ),
        )
        return

    try:
        issue = jira_client.get_issue(issue_key, cfg)
    except Exception as exc:
        logger.error("Jira fetch error: %s", exc)
        respond(
            response_type="ephemeral",
            text=(
                f"❌ Could not fetch Jira issue *{issue_key}*. Check the key "
                f"and your Jira credentials.\n`{exc}`"
            ),
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
        issue_description=issue.get("description", ""),
        issue_reporter=issue.get("reporter", ""),
    )
    placeholder_stats = store.VoteStats(
        vote_count=0, all_agree=False, agreed_value=None, distribution={}
    )

    try:
        posted = client.chat_postMessage(
            channel=command["channel_id"],
            text=f"Story point vote for {issue_key}",
            blocks=build_voting_message(placeholder_session, placeholder_stats),
        )
    except Exception as exc:
        logger.error("Slack post error: %s", exc)
        respond(
            response_type="ephemeral",
            text="❌ Failed to post the voting message to this channel.",
        )
        return

    # Create the real session with the message ts
    session = store.create_session(
        channel_id=command["channel_id"],
        message_ts=posted["ts"],
        issue_key=issue["key"],
        issue_summary=issue["summary"],
        issue_url=issue["url"],
        initiated_by=command["user_id"],
        issue_description=issue.get("description", ""),
        issue_reporter=issue.get("reporter", ""),
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
def handle_vote(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    user_id = body["user"]["id"]
    user_name = body["user"].get("username", user_id)

    session = store.get_session_by_message(channel_id, message_ts)
    if not session:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "Session not found. Please start a new vote.",
        )
        return

    if session.revealed:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "Votes have already been revealed. Use *Re-vote* to start a new round.",
        )
        return

    store.add_vote(session.session_id, user_id, user_name, action["value"])
    stats = store.get_vote_stats(session)

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key}",
        blocks=build_voting_message(session, stats),
    )
    _post_ephemeral(
        client, channel_id, user_id, message_ts,
        f"You voted *{action['value']}* for {session.issue_key}. "
        "You can change your vote anytime before reveal.",
    )


for _pts in POINT_VALUES:
    app.action(f"vote_{_pts}")(handle_vote)


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
        _post_ephemeral(
            client, channel_id, user_id, message_ts, "No votes have been cast yet!"
        )
        return

    store.set_revealed(session_id)
    stats = store.get_vote_stats(session)

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key} — revealed!",
        blocks=build_voting_message(session, stats),
    )


# ── Toggle ticket description ─────────────────────────────────────────────────
@app.action("toggle_description")
def handle_toggle_description(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    session_id = action["value"]

    session = store.get_session(session_id)
    if not session:
        return

    # Shared toggle: expanding/collapsing updates the card for everyone.
    session.description_expanded = not session.description_expanded
    stats = store.get_vote_stats(session)

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key}",
        blocks=build_voting_message(session, stats),
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
def handle_select_override(ack, action):
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
    _perform_jira_update(
        client, channel_id, message_ts, user_id, session_id, point_value
    )


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
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "Please select a point value from the dropdown before updating Jira.",
        )
        return

    _perform_jira_update(
        client, channel_id, message_ts, user_id, session_id, session.override_points
    )


def _perform_jira_update(
    client, channel_id, message_ts, user_id, session_id, point_value
):
    session = store.get_session(session_id)
    if not session:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found.")
        return

    if session.updated:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "Jira has already been updated for this session.",
        )
        return

    cfg = channel_config.get_channel_config(session.channel_id)
    try:
        result = jira_client.update_issue(session.issue_key, point_value, cfg)
    except Exception as exc:
        logger.error("Jira update error: %s", exc)
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            f"Failed to update Jira: `{exc}`",
        )
        return

    # Stash the pre-update state so the update can be reverted later.
    session.original_state = result.get("original")
    store.set_updated(session_id)
    stats = store.get_vote_stats(session)
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
        blocks=build_voting_message(session, stats),
    )


# ── Revert Jira update ────────────────────────────────────────────────────────
@app.action("revert_jira")
def handle_revert_jira(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    user_id = body["user"]["id"]
    session_id = action["value"]

    session = store.get_session(session_id)
    if not session:
        _post_ephemeral(client, channel_id, user_id, message_ts, "Session not found.")
        return

    if not session.updated:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "Nothing to revert — Jira wasn't updated for this session.",
        )
        return

    if session.reverted:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "This session has already been reverted.",
        )
        return

    if not session.original_state:
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            "No original state was captured, so this can't be reverted automatically.",
        )
        return

    cfg = channel_config.get_channel_config(session.channel_id)
    try:
        result = jira_client.revert_issue(
            session.issue_key, session.original_state, cfg
        )
    except Exception as exc:
        logger.error("Jira revert error: %s", exc)
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            f"Failed to revert Jira: `{exc}`",
        )
        return

    session.reverted = True
    stats = store.get_vote_stats(session)
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Story point vote for {session.issue_key} — reverted",
        blocks=build_voting_message(session, stats),
    )

    # Fields always restore; the status move is best-effort (directional
    # workflow transitions). Warn if it couldn't get back to the original.
    orig_status = session.original_state.get("status")
    if orig_status and not result.get("status_restored", False):
        _post_ephemeral(
            client, channel_id, user_id, message_ts,
            f"Labels and story points were restored, but I couldn't transition "
            f"*{session.issue_key}* back to *{orig_status}* — no matching "
            "workflow transition from its current status. Set the status "
            "manually if needed.",
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
    projects_raw = (values["allowed_projects"]["value"]["value"] or "").strip()
    allowed_projects = [
        pk.strip().upper() for pk in projects_raw.split(",") if pk.strip()
    ]

    saved = channel_config.set_channel_config(
        channel_id,
        {
            "target_status": target_status,
            "labels_to_remove": labels_to_remove,
            "story_points_field": story_points_field,
            "allowed_projects": allowed_projects,
        },
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
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "↩️ *Channel config reset.* This channel will now "
                            "use the org-wide defaults from `.env`."
                        ),
                    },
                }
            ],
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
