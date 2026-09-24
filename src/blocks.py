"""
Slack Block Kit builders for the story pointing bot.
"""

from __future__ import annotations
from datetime import datetime

# Fibonacci-ish story point scale
POINT_VALUES = ["1", "2", "3", "5", "8", "13", "21", "?", "☕"]

DESCRIPTION_INLINE_LIMIT = 500

# Voter avatars on the card; a context block holds at most 10 elements,
# and one is kept for the vote count.
MAX_AVATARS = 9


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
    reverted = getattr(session, "reverted", False)
    cancelled = getattr(session, "cancelled", False)

    vote_count = stats.vote_count
    all_agree = stats.all_agree
    agreed_value = stats.agreed_value

    blocks = []

    # ── Ticket: key + summary, reporter/type fields, description toggle ───
    reporter = getattr(session, "issue_reporter", "") or ""
    issue_type = getattr(session, "issue_type", "") or ""
    description = getattr(session, "issue_description", "") or ""
    expanded = getattr(session, "description_expanded", False)

    ticket = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*<{issue_url}|{issue_key}>*  {issue_summary}"},
    }
    fields = []
    if reporter:
        fields.append({"type": "mrkdwn", "text": f"*Reporter*\n{reporter}"})
    if issue_type:
        fields.append({"type": "mrkdwn", "text": f"*Type*\n{_issue_type_label(issue_type)}"})
    if fields:
        ticket["fields"] = fields
    # Short descriptions toggle inline; long ones are posted in the thread.
    short_description = description and len(description) <= DESCRIPTION_INLINE_LIMIT
    if short_description:
        ticket["accessory"] = {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Hide description" if expanded else "Description",
                "emoji": True,
            },
            "action_id": "toggle_description",
            "value": session.session_id,
        }
    blocks.append(ticket)

    if short_description and expanded:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": description},
        })
    elif description and not short_description:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "📋 _Description is long — full text posted in thread._",
            }],
        })

    # ── Voting: point buttons, who has voted, reveal/cancel ───────────────
    if not revealed and not cancelled:
        # One neutral row; Slack wraps it to the client's width.
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": pts, "emoji": True},
                    "value": pts,
                    "action_id": f"vote_{pts}",
                }
                for pts in POINT_VALUES
            ],
        })

        blocks.append({
            "type": "context",
            "elements": _voter_context(votes, vote_count),
        })

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reveal votes", "emoji": True},
                    "style": "primary",
                    "action_id": "reveal_votes",
                    "value": session.session_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reveal votes?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "This will show everyone's votes. "
                                "Make sure everyone has voted!"
                            ),
                        },
                        "confirm": {"type": "plain_text", "text": "Reveal"},
                        "deny": {"type": "plain_text", "text": "Not yet"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "cancel_pointing",
                    "value": session.session_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Cancel this vote?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"This will cancel pointing for *{issue_key}*. "
                                "Jira won't be updated. You can re-point later."
                            ),
                        },
                        "confirm": {"type": "plain_text", "text": "Cancel pointing"},
                        "deny": {"type": "plain_text", "text": "Keep going"},
                    },
                },
            ],
        })

    # ── Results (after reveal): one bar per value with its voters ─────────
    if revealed:
        blocks.append({"type": "divider"})
        groups: dict[str, list[str]] = {}
        for uid, v in votes.items():
            groups.setdefault(v["value"], []).append(f"<@{uid}>")
        if groups:
            results_text = "\n".join(
                f"`{pts:>2}`  {'🟩' * len(uids)}{'⬜' * (vote_count - len(uids))}  "
                f"{', '.join(uids)}"
                for pts, uids in sorted(groups.items(), key=lambda kv: _sort_key(kv[0]))
            )
        else:
            results_text = "_No votes were cast._"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": results_text},
        })

    # ── Cancelled banner ──────────────────────────────────────────────────
    if cancelled:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"✖️ *Pointing cancelled.* <{issue_url}|{issue_key}> was not "
                    "updated in Jira."
                ),
            },
        })
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "🔄 Re-point", "emoji": True},
                "style": "primary",
                "action_id": "revote",
                "value": session.session_id,
            }],
        })

    if revealed and not updated:
        revote_button = {
            "type": "button",
            "text": {"type": "plain_text", "text": "Re-vote", "emoji": True},
            "action_id": "revote",
            "value": session.session_id,
        }
        if all_agree:
            # Consensus path — pre-filled button
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Consensus: {agreed_value} points*",
                },
            })
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": f"Update Jira: {agreed_value} pts",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "update_jira",
                        "value": f"{session.session_id}::{agreed_value}",
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Update Jira ticket?",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"This will:\n• Set story points to "
                                    f"*{agreed_value}*\n"
                                    "• Remove pointing labels\n"
                                    "• Move ticket to configured status"
                                ),
                            },
                            "confirm": {"type": "plain_text", "text": "Update"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    revote_button,
                ],
            })
        else:
            # No consensus — summary + dropdown picker + update button
            summary = "⚠️ *No consensus*"
            numeric = sorted(
                float(v["value"]) for v in votes.values()
                if v["value"].isdigit()
            )
            if numeric:
                summary += f"  ·  median *{_fmt_pts(_median(numeric))}*"
                if numeric[0] != numeric[-1]:
                    summary += (
                        f"  ·  range {_fmt_pts(numeric[0])}–{_fmt_pts(numeric[-1])}"
                    )
            select = {
                "type": "static_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Final points…",
                    "emoji": True,
                },
                "action_id": "select_override_points",
                "options": [
                    {
                        "text": {
                            "type": "plain_text",
                            "text": f"{v} pts",
                            "emoji": True,
                        },
                        "value": f"{session.session_id}::{v}",
                    }
                    for v in POINT_VALUES
                ],
            }
            # Keep the chosen value visible across card re-renders.
            override = getattr(session, "override_points", None)
            if override in POINT_VALUES:
                select["initial_option"] = select["options"][POINT_VALUES.index(override)]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{summary}\nPick the final value:",
                },
                "accessory": select,
            })
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Update Jira",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "update_jira_override",
                        "value": session.session_id,
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Update Jira ticket?",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    "This will:\n• Set story points to your "
                                    "selected value\n"
                                    "• Remove pointing labels\n"
                                    "• Move ticket to configured status"
                                ),
                            },
                            "confirm": {"type": "plain_text", "text": "Update"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    revote_button,
                ],
            })

    # ── Updated confirmation banner (+ revert) ────────────────────────────
    if updated and not reverted:
        display_pts = agreed_value or getattr(session, "override_points", "?")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🎉 *Jira updated!* <{issue_url}|{issue_key}> set to "
                    f"*{display_pts} story points* and moved to the next status."
                ),
            },
        })
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "↩️ Revert to backlog",
                    "emoji": True,
                },
                "style": "danger",
                "action_id": "revert_jira",
                "value": session.session_id,
                "confirm": {
                    "title": {"type": "plain_text", "text": "Revert the ticket?"},
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "This will restore the original status and labels "
                            "and clear the story points."
                        ),
                    },
                    "confirm": {"type": "plain_text", "text": "Revert"},
                    "deny": {"type": "plain_text", "text": "Keep it"},
                },
            }],
        })

    # ── Reverted banner ───────────────────────────────────────────────────
    if reverted:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"↩️ *Reverted.* <{issue_url}|{issue_key}> was restored to its "
                    "original status and labels, and its story points cleared."
                ),
            },
        })

    return blocks


# ── /point-config modal builders ─────────────────────────────────────────────

def build_config_modal(channel_id: str, config: dict, org_defaults: dict) -> dict:
    labels_value = ", ".join(config["labels_to_remove"])
    org_labels_value = ", ".join(org_defaults["labels_to_remove"])

    if config["is_customized"]:
        context_text = (
            "⚙️ This channel has custom settings. "
            "Org defaults shown as placeholder text."
        )
    else:
        context_text = (
            "⚙️ Using org-wide defaults. "
            "Fill in any field to override for this channel."
        )

    projects_value = ", ".join(config["allowed_projects"])
    org_projects_value = ", ".join(org_defaults["allowed_projects"])

    modal_blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context_text}]},
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "allowed_projects",
            "label": {
                "type": "plain_text",
                "text": "Allowed Jira projects",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Comma-separated project short codes this channel may point "
                    "(e.g. PLAT, INFRA). Required before /point will work in "
                    "this channel."
                ),
            },
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": projects_value,
                "placeholder": {
                    "type": "plain_text",
                    "text": org_projects_value or "e.g. PLAT, INFRA",
                },
            },
        },
        {
            "type": "input",
            "block_id": "jira_base_url",
            "label": {
                "type": "plain_text",
                "text": "Jira site URL",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Your Jira Cloud site, e.g. https://yourcompany.atlassian.net. "
                    "Required before /point will work in this channel."
                ),
            },
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["jira_base_url"],
                "placeholder": {
                    "type": "plain_text",
                    "text": org_defaults["jira_base_url"] or "e.g. https://yourcompany.atlassian.net",
                },
            },
        },
        {
            "type": "input",
            "block_id": "jira_email",
            "label": {
                "type": "plain_text",
                "text": "Jira email",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": "Email for the Jira account this channel authenticates as.",
            },
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["jira_email"],
                "placeholder": {
                    "type": "plain_text",
                    "text": org_defaults["jira_email"] or "e.g. you@company.com",
                },
            },
        },
        {
            "type": "input",
            "block_id": "jira_api_token",
            "label": {
                "type": "plain_text",
                "text": "Jira API token",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Generate at id.atlassian.com/manage-profile/security/api-tokens. "
                    "Required before /point will work in this channel. Stored "
                    "encrypted and never shown again -- leave blank to keep the "
                    "current one; type a new value to replace it."
                    + (
                        "  🔒 A token is currently configured for this channel."
                        if config.get("has_channel_token")
                        else "  No channel-specific token is set yet."
                    )
                ),
            },
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                # Deliberately never pre-filled -- see hint above.
                "placeholder": {
                    "type": "plain_text",
                    "text": "Paste a new token to set/replace it",
                },
            },
        },
        {
            "type": "input",
            "block_id": "target_status",
            "label": {
                "type": "plain_text",
                "text": "Jira target status",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Workflow transition name to move the ticket into after "
                    "pointing (must match exactly)."
                ),
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["target_status"],
                "placeholder": {
                    "type": "plain_text",
                    "text": org_defaults["target_status"],
                },
            },
        },
        {
            "type": "input",
            "block_id": "labels_to_remove",
            "label": {
                "type": "plain_text",
                "text": "Labels to remove",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Comma-separated list of Jira labels to strip from the "
                    "ticket when updating."
                ),
            },
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": labels_value,
                "placeholder": {
                    "type": "plain_text",
                    "text": org_labels_value or "e.g. needs-pointing, unpointed",
                },
            },
        },
        {
            "type": "input",
            "block_id": "story_points_field",
            "label": {
                "type": "plain_text",
                "text": "Story points field ID",
                "emoji": True,
            },
            "hint": {
                "type": "plain_text",
                "text": (
                    "Jira custom field ID. Find via GET /rest/api/3/field. "
                    "Common: customfield_10016 or customfield_10028."
                ),
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "initial_value": config["story_points_field"],
                "placeholder": {
                    "type": "plain_text",
                    "text": org_defaults["story_points_field"],
                },
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
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"_Last updated by <@{config['updated_by']}> "
                        f"on {date_str}_"
                    ),
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reset to org defaults",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": "reset_channel_config",
                    "value": channel_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reset config?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "This will remove all channel-specific overrides "
                                "and fall back to org-wide `.env` defaults."
                            ),
                        },
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
    if config["allowed_projects"]:
        projects_text = ", ".join(f"`{pk}`" for pk in config["allowed_projects"])
    else:
        projects_text = "_none set — /point is blocked until this is set_"
    base_url_text = config["jira_base_url"] or "_none set — /point is blocked until this is set_"
    email_text = config["jira_email"] or "_none set_"
    token_text = "🔒 configured" if config["jira_api_token"] else "_none set — /point is blocked until this is set_"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"✅ *Config saved for this channel!*\n\n"
                    f"*Allowed projects:* {projects_text}\n"
                    f"*Jira site URL:* {base_url_text}\n"
                    f"*Jira email:* {email_text}\n"
                    f"*Jira API token:* {token_text}\n"
                    f"*Target status:* `{config['target_status']}`\n"
                    f"*Labels to remove:* {labels_text}\n"
                    f"*Story points field:* `{config['story_points_field']}`"
                ),
            },
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    "These settings apply to all future `/point` votes in this "
                    "channel. Run `/point-config` again to change them."
                ),
            }],
        },
    ]


def build_config_reset_message() -> list[dict]:
    return [{
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "↩️ *Channel config reset.* This channel will now use the "
                "org-wide defaults from `.env`."
            ),
        },
    }]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _voter_context(votes: dict, vote_count: int) -> list[dict]:
    """
    Context elements for who has voted: an avatar per voter, then the count.
    A context block allows 10 elements, so past MAX_AVATARS the rest show
    as "+N". Voters without an avatar URL are listed as @mentions.
    """
    if vote_count == 0:
        return [{"type": "mrkdwn", "text": "_No votes yet_"}]

    with_avatar = [
        (uid, v) for uid, v in votes.items() if v.get("avatar_url")
    ]
    without_avatar = [uid for uid, v in votes.items() if not v.get("avatar_url")]

    elements = [
        {
            "type": "image",
            "image_url": v["avatar_url"],
            "alt_text": v.get("user_name") or "voter",
        }
        for _, v in with_avatar[:MAX_AVATARS]
    ]
    text = f"*{vote_count} voted*"
    hidden = len(with_avatar) - MAX_AVATARS
    if hidden > 0:
        text = f"+{hidden}  ·  " + text
    if without_avatar:
        text += "  ·  " + ", ".join(f"<@{uid}>" for uid in without_avatar)
    elements.append({"type": "mrkdwn", "text": text})
    return elements


# Jira's built-in issue types; anything else shows as plain text.
ISSUE_TYPE_EMOJI = {
    "story": "📗",
    "bug": "🐞",
    "task": "☑️",
    "sub-task": "☑️",
    "subtask": "☑️",
    "epic": "⚡",
    "spike": "🔍",
}


def _issue_type_label(issue_type: str) -> str:
    emoji = ISSUE_TYPE_EMOJI.get(issue_type.lower())
    return f"{emoji} {issue_type}" if emoji else issue_type


def _median(values: list[float]) -> float:
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _fmt_pts(value: float) -> str:
    return f"{value:g}"


def _sort_key(pts: str) -> int:
    try:
        return POINT_VALUES.index(pts)
    except ValueError:
        return len(POINT_VALUES)
