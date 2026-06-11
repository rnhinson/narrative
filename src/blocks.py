"""
Slack Block Kit builders for the story pointing bot.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

# Fibonacci-ish story point scale
POINT_VALUES = ["1", "2", "3", "5", "8", "13", "21", "?", "☕"]


def build_voting_message(session, stats) -> list[dict]:
    """
    Render the main voting card. Adapts based on state:
        voting → revealed (no consensus) → revealed (consensus) → updated
    """
    issue_key = session.issue_key
    issue_url = session.issue_url
    issue_summary = session.issue_summary
    votes = session.votes
    revealed = session.revealed
    updated = session.updated

    vote_count = stats.vote_count
    all_agree = stats.all_agree
    agreed_value = stats.agreed_value
    distribution = stats.distribution

    blocks = []

    # ── Header ────────────────────────────────────────────────────────────
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": "📖 Story Point Vote", "emoji": True},
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Ticket:* <{issue_url}|{issue_key}>\n*Summary:* {issue_summary}",
        },
    })
    blocks.append({"type": "divider"})

    # ── Vote buttons (hidden after reveal) ────────────────────────────────
    if not revealed:
        chunks = [POINT_VALUES[i:i+5] for i in range(0, len(POINT_VALUES), 5)]
        for chunk in chunks:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": pts, "emoji": True},
                        "value": pts,
                        "action_id": f"vote_{pts}",
                        **({"style": "primary"} if pts not in ("?", "☕") else {}),
                    }
                    for pts in chunk
                ],
            })

    # ── Voter list ────────────────────────────────────────────────────────
    if vote_count == 0:
        voter_text = "_No votes yet. Be the first!_"
    elif not revealed:
        # Single comma-separated line of who has voted (values hidden)
        names = ", ".join(f"<@{uid}>" for uid in votes)
        voter_text = f"✅  {names}"
    else:
        # Group voters by their point value, one line per value
        groups: dict[str, list[str]] = {}
        for uid, v in votes.items():
            groups.setdefault(v["value"], []).append(f"<@{uid}>")
        voter_text = "\n".join(
            f"*{pts}* — {', '.join(uids)}"
            for pts, uids in sorted(groups.items(), key=lambda kv: _sort_key(kv[0]))
        )

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Votes ({vote_count}):*\n{voter_text}"},
    })

    # ── Results (after reveal) ────────────────────────────────────────────
    if revealed:
        sorted_dist = sorted(distribution.items(), key=lambda kv: _sort_key(kv[0]))
        dist_text = "  |  ".join(
            f"*{pts}* pts → {cnt} vote{'s' if cnt > 1 else ''}"
            for pts, cnt in sorted_dist
        )
        if all_agree:
            consensus_text = f"\n\n✅ *Consensus reached: {agreed_value} points!*"
        else:
            consensus_text = "\n\n⚠️ *No consensus yet.* Discuss and re-vote or pick a value."

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Results:*\n{dist_text}{consensus_text}"},
        })

    blocks.append({"type": "divider"})

    # ── Action buttons ────────────────────────────────────────────────────
    if not revealed:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "👁️ Reveal Votes", "emoji": True},
                "style": "danger",
                "action_id": "reveal_votes",
                "value": session.session_id,
                "confirm": {
                    "title": {"type": "plain_text", "text": "Reveal votes?"},
                    "text": {"type": "mrkdwn", "text": "This will show everyone's votes. Make sure everyone has voted!"},
                    "confirm": {"type": "plain_text", "text": "Reveal"},
                    "deny": {"type": "plain_text", "text": "Not yet"},
                },
            }],
        })

    if revealed and not updated:
        if all_agree:
            # Consensus path — pre-filled button
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": f"✅ Update Jira: {agreed_value} pts", "emoji": True},
                        "style": "primary",
                        "action_id": "update_jira",
                        "value": f"{session.session_id}::{agreed_value}",
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Update Jira ticket?"},
                            "text": {"type": "mrkdwn", "text": f"This will:\n• Set story points to *{agreed_value}*\n• Remove pointing labels\n• Move ticket to configured status"},
                            "confirm": {"type": "plain_text", "text": "Update"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Re-vote", "emoji": True},
                        "action_id": "revote",
                        "value": session.session_id,
                    },
                ],
            })
        else:
            # No consensus — dropdown picker + update button
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "⚠️ *No consensus.* Choose the final point value to commit:"},
                "accessory": {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "Pick points…", "emoji": True},
                    "action_id": "select_override_points",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": f"{v} pts", "emoji": True},
                            "value": f"{session.session_id}::{v}",
                        }
                        for v in POINT_VALUES
                    ],
                },
            })
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Update Jira", "emoji": True},
                        "style": "primary",
                        "action_id": "update_jira_override",
                        "value": session.session_id,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Update Jira ticket?"},
                            "text": {"type": "mrkdwn", "text": "This will:\n• Set story points to your selected value\n• Remove pointing labels\n• Move ticket to configured status"},
                            "confirm": {"type": "plain_text", "text": "Update"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Re-vote", "emoji": True},
                        "action_id": "revote",
                        "value": session.session_id,
                    },
                ],
            })

    # ── Updated confirmation banner ───────────────────────────────────────
    if updated:
        display_pts = agreed_value or getattr(session, "override_points", "?")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎉 *Jira updated!* <{issue_url}|{issue_key}> set to *{display_pts} story points* and moved to the next status.",
            },
        })

    return blocks


# ── /point-config modal builders ─────────────────────────────────────────────

def build_config_modal(channel_id: str, config: dict, org_defaults: dict) -> dict:
    labels_value = ", ".join(config["labels_to_remove"])
    org_labels_value = ", ".join(org_defaults["labels_to_remove"])

    context_text = (
        "⚙️ This channel has custom settings. Org defaults shown as placeholder text."
        if config["is_customized"]
        else "⚙️ Using org-wide defaults. Fill in any field to override for this channel."
    )

    modal_blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context_text}]},
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "target_status",
            "label": {"type": "plain_text", "text": "Jira target status", "emoji": True},
            "hint": {"type": "plain_text", "text": "Workflow transition name to move the ticket into after pointing (must match exactly)."},
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["target_status"],
                "placeholder": {"type": "plain_text", "text": org_defaults["target_status"]},
            },
        },
        {
            "type": "input",
            "block_id": "labels_to_remove",
            "label": {"type": "plain_text", "text": "Labels to remove", "emoji": True},
            "hint": {"type": "plain_text", "text": "Comma-separated list of Jira labels to strip from the ticket when updating."},
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": labels_value,
                "placeholder": {"type": "plain_text", "text": org_labels_value or "e.g. needs-pointing, unpointed"},
            },
        },
        {
            "type": "input",
            "block_id": "story_points_field",
            "label": {"type": "plain_text", "text": "Story points field ID", "emoji": True},
            "hint": {"type": "plain_text", "text": "Jira custom field ID. Find via GET /rest/api/3/field. Common: customfield_10016 or customfield_10028."},
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["story_points_field"],
                "placeholder": {"type": "plain_text", "text": org_defaults["story_points_field"]},
            },
        },
    ]

    if config["is_customized"]:
        updated_at = config.get("updated_at") or ""
        try:
            dt = datetime.fromisoformat(updated_at)
            date_str = dt.strftime("%b %-d, %Y")
        except Exception:
            date_str = "unknown"

        modal_blocks += [
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_Last updated by <@{config['updated_by']}> on {date_str}_"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reset to org defaults", "emoji": True},
                    "style": "danger",
                    "action_id": "reset_channel_config",
                    "value": channel_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reset config?"},
                        "text": {"type": "mrkdwn", "text": "This will remove all channel-specific overrides and fall back to org-wide `.env` defaults."},
                        "confirm": {"type": "plain_text", "text": "Reset"},
                        "deny": {"type": "plain_text", "text": "Keep current"},
                    },
                },
            },
        ]

    return {
        "type": "modal",
        "callback_id": "point_config_submit",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Narrative Config", "emoji": True},
        "submit": {"type": "plain_text", "text": "Save", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": modal_blocks,
    }


def build_config_saved_message(config: dict) -> list[dict]:
    if config["labels_to_remove"]:
        labels_text = ", ".join(f"`{lb}`" for lb in config["labels_to_remove"])
    else:
        labels_text = "_none_"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"✅ *Config saved for this channel!*\n\n"
                    f"*Target status:* `{config['target_status']}`\n"
                    f"*Labels to remove:* {labels_text}\n"
                    f"*Story points field:* `{config['story_points_field']}`"
                ),
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "These settings apply to all future `/point` votes in this channel. Run `/point-config` again to change them."}],
        },
    ]


def build_config_reset_message() -> list[dict]:
    return [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": "↩️ *Channel config reset.* This channel will now use the org-wide defaults from `.env`."},
    }]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sort_key(pts: str) -> int:
    try:
        return POINT_VALUES.index(pts)
    except ValueError:
        return len(POINT_VALUES)
