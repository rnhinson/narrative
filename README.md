# 🃏 Narrative

A Slack bot for running Agile story point voting sessions with Jira integration. Drop it into any channel, call `/point PROJ-123`, and your team can vote, reveal, and update Jira — without leaving Slack.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-%3E%3D3.12-blue)

---

## Features

- **`/point PROJ-123`** — starts a vote in the channel with a live link to the Jira ticket
- **Fibonacci scale** — buttons for 1, 2, 3, 5, 8, 13, 21, ?, ☕
- **Hidden votes** — voters are listed but values stay hidden until reveal
- **Reveal** — shows all votes with a distribution; highlights consensus
- **Override** — if there's no consensus, a dropdown lets the team pick a final value
- **Re-vote** — resets the round without losing the session
- **Update Jira** — one click when ready: sets story points, removes labels, transitions the ticket
- **`/point-config`** — per-channel config so each team can set their own Jira status, labels, and field ID

---

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/your-org/narrative.git
cd narrative
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From Scratch**
2. Add **Bot Token Scopes** under OAuth & Permissions: `chat:write`, `chat:write.public`, `commands`
3. Create two **Slash Commands** — `/point` and `/point-config` — both pointing at `https://your-host/slack/events`
4. Enable **Interactivity** and set the Request URL to `https://your-host/slack/events`
5. Enable **Socket Mode** (recommended for local dev) and generate an App-Level Token with `connections:write`
6. Install the app to your workspace and copy the Bot Token

### 3. Create a Jira API token

Generate one at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

### 4. Configure environment

```bash
cp .env.example .env
# Fill in your Slack and Jira credentials
```

### 5. Run

```bash
# Development (Socket Mode — no public URL needed)
python src/app.py

# Production (HTTP mode)
SOCKET_MODE=false python src/app.py
```

---

## Configuration

All settings can be set org-wide in `.env`, and overridden per-channel using `/point-config`.

| Variable | Description | Default |
|---|---|---|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (`xoxb-...`) | required |
| `SLACK_SIGNING_SECRET` | From Basic Information in your Slack App | required |
| `SLACK_APP_TOKEN` | App-Level Token for Socket Mode (`xapp-...`) | required in Socket Mode |
| `JIRA_BASE_URL` | e.g. `https://yourcompany.atlassian.net` | required |
| `JIRA_EMAIL` | Email associated with the API token | required |
| `JIRA_API_TOKEN` | Jira API token | required |
| `JIRA_TARGET_STATUS` | Workflow transition name after pointing | `Ready for Sprint` |
| `JIRA_LABELS_TO_REMOVE` | Comma-separated labels to strip | _(empty)_ |
| `JIRA_STORY_POINTS_FIELD` | Jira custom field ID for story points | `customfield_10016` |
| `PORT` | HTTP port | `3000` |
| `SOCKET_MODE` | `true` for local dev, `false` for production HTTP | `true` |
| `DATA_DIR` | Directory for persisting per-channel config | project root |

**Finding your story points field ID:**
```bash
curl -u your@email.com:YOUR_API_TOKEN \
  https://yourcompany.atlassian.net/rest/api/3/field \
  | grep -i "story point"
```

### Per-channel config

Any channel member can run `/point-config` to override the org-wide defaults for their channel. Settings are persisted to `config-store.json` and survive restarts.

---

## Project structure

```
src/
  app.py            — Slack Bolt app, all command and action handlers
  blocks.py         — Block Kit message builder (voting card UI)
  config.py         — Per-channel config store with file persistence
  store.py          — In-memory voting session state
  jira.py           — Jira REST API client
.github/workflows/
  deploy.yml        — GitHub Actions CI/CD pipeline
```

---

## License

[MIT](LICENSE)
