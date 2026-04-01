# AI Employee Silver

[![CI](https://github.com/goosa123/AI-Employee-Silver/actions/workflows/python-app.yml/badge.svg)](https://github.com/goosa123/AI-Employee-Silver/actions/workflows/python-app.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stack](https://img.shields.io/badge/AI-Claude%20%7C%20Python%20%7C%20Gmail%20%7C%20LinkedIn-blueviolet)](#tech-stack)

> An autonomous AI-powered business assistant that monitors Gmail and LinkedIn 24/7, drafts content with Claude AI, and executes tasks through a human-in-the-loop approval workflow — with scheduled posting support.

---

## What It Does

| Capability | Details |
|---|---|
| **Gmail Monitoring** | Fetches unread emails every 60s, classifies, auto-replies or routes to approval |
| **LinkedIn Posting** | Takes a brief file, drafts a post via Claude AI, posts after human approval |
| **Scheduled Posting** | Approve a post with a future time — watcher auto-posts at the exact scheduled time |
| **Approval UI** | Web interface (Flask) to approve/reject/schedule pending posts with one click |
| **Human-in-the-Loop** | Every sensitive action waits for approval — nothing executes without owner sign-off |
| **Auto-start** | Watchers launch on Windows login via Task Scheduler — no manual start needed |
| **Live Dashboard** | Obsidian markdown dashboard updates every cycle with system health + token status |
| **Desktop Alerts** | Windows toast notification when approvals are pending |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER                         │
│  gmail_dev_watcher.py     linkedin_dev_watcher.py          │
│  (every 60s)              (every 300s)                     │
│         │                        │                          │
│         ▼                        ▼                          │
│   Gmail API              vault/linkedin/intake/             │
└──────────────┬───────────────────┬─────────────────────────┘
               │                   │
               ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    REASONING LAYER                          │
│  email_classifier skill    linkedin_drafter skill          │
│  email_drafter skill       (Claude AI via CLI)             │
│         │                        │                          │
│         ▼                        ▼                          │
│   vault/Pending_Approval/  ←  AI Drafts                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               │  Human reviews via Approval UI (http://localhost:5050)
               │  Approve / Reject / Schedule for later
               ▼
┌─────────────────────────────────────────────────────────────┐
│                   SCHEDULING LAYER                          │
│  vault/Scheduled/  ←  Approved posts with future time      │
│  main_watcher checks every cycle:                          │
│    scheduled_at <= now  →  move to Approved/  →  post      │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                     ACTION LAYER                            │
│  gmail_approver.py         linkedin_approver.py            │
│  (sends email via          (posts to LinkedIn via          │
│   Gmail API)                LinkedIn API)                  │
│         │                        │                          │
│         ▼                        ▼                          │
│      vault/Done/gmail/     vault/Done/linkedin/             │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATION LAYER                       │
│  watchers/launcher.py  ← Task Scheduler (AtLogon)          │
│  watchers/main_watcher.py  (Inbox / Drop / Vault / Sched)  │
│  scripts/generate_dashboard.py  → dashboard.md             │
│  utils/notifier.py  → Windows toast notifications          │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Tool |
|---|---|
| AI Brain | Claude AI (Haiku for skills, Sonnet for tasks) |
| Approval UI | Flask (local web interface — localhost:5050) |
| Memory / GUI | Obsidian — local Markdown vault |
| Watchers | Python 3.10+ — Gmail + LinkedIn + Filesystem |
| Email | Gmail API (OAuth2) |
| LinkedIn | LinkedIn API (OAuth2 — `w_member_social` scope) |
| MCP Server | FastMCP (`mcp_server/server.py`) |
| Scheduling | Windows Task Scheduler (AtLogon trigger) |
| Notifications | winotify (Windows toast) |

---

## Project Structure

```
AI-Employee-Silver/
├── watchers/
│   ├── launcher.py           # Single entry point — starts all watchers
│   ├── main_watcher.py       # Vault watcher — Inbox/Drop/Scheduled/Approval
│   └── watcher_config.py     # Polling intervals config
├── processors/
│   ├── gmail_processor.py    # Gmail fetch → classify → draft
│   ├── gmail_approver.py     # Send approved email replies
│   ├── linkedin_processor.py # Brief → draft LinkedIn post (supports scheduled_at)
│   └── linkedin_approver.py  # Post approved content (respects scheduled_at)
├── skills/
│   ├── email_classifier/     # Classify emails (Claude AI)
│   ├── email_drafter/        # Draft email replies (Claude AI)
│   └── linkedin_drafter/     # Draft LinkedIn posts (Claude AI)
├── integrations/
│   ├── gmail/                # Gmail API auth, reader, sender
│   └── linkedin/             # LinkedIn config, poster
├── mcp_server/
│   └── server.py             # FastMCP server
├── scripts/
│   ├── approval_ui.py        # Flask web UI — approve/reject/schedule
│   ├── generate_dashboard.py # Dashboard + notifications
│   ├── linkedin_auth.py      # One-time LinkedIn OAuth token
│   └── setup_task_scheduler.ps1  # Windows Task Scheduler setup
├── utils/
│   └── notifier.py           # Windows desktop notifications
├── vault/                    # Local data (gitignored)
│   ├── Inbox/                # Drop tasks here
│   ├── Pending_Approval/     # Awaiting human review
│   ├── Scheduled/            # Approved posts with future time
│   ├── Approved/             # Ready to execute
│   ├── Done/                 # Completed tasks
│   └── ...
├── credentials/              # OAuth tokens (gitignored)
├── .env                      # API credentials (gitignored)
└── requirements.txt
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Gmail OAuth
Place `gmail_credentials.json` in `credentials/` then:
```bash
python integrations/gmail/auth.py
```

### 3. LinkedIn OAuth (one-time)
Add to `.env`:
```
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_REDIRECT_URI=http://localhost:8080/callback
```
Then:
```bash
python scripts/linkedin_auth.py
```

### 4. Auto-start on Windows login
```powershell
# Run as Administrator
powershell -File scripts/setup_task_scheduler.ps1
```

### 5. Open vault in Obsidian
Open the `vault/` folder in Obsidian. Pin `Dashboard/dashboard.md` for live system status.

---

## Usage

### Start all watchers
```bash
python watchers/launcher.py
```

### Open Approval UI
```bash
python scripts/approval_ui.py
# Opens at http://localhost:5050
```

### Submit a task
Drop any `.md` or `.txt` file into `vault/Inbox/` — the watcher picks it up within seconds.

### LinkedIn post (immediate)
Create a brief in `vault/linkedin/intake/`:
```json
{
  "topic": "AI is transforming the business landscape",
  "tone": "professional",
  "audience": "Entrepreneurs and business owners",
  "key_points": ["Automation saves time", "10x output", "Human-in-the-loop control"],
  "cta": "Are you using AI to automate your business?"
}
```
Watcher drafts → review in Approval UI → Approve → posted to LinkedIn.

### LinkedIn post (scheduled)
Add `scheduled_at` to your brief:
```json
{
  "topic": "...",
  "scheduled_at": "2026-04-03 09:00"
}
```
Approve in UI → post goes to `vault/Scheduled/` → watcher auto-posts at exact time.

### Approval UI actions
| Action | Result |
|---|---|
| Approve | Moves to `Approved/` — executes in next watcher cycle |
| Approve + time | Moves to `Scheduled/` — auto-posts at that time |
| Reject | Moves to `Rejected/` — no action taken |
| Post Now | Immediate execution from `Scheduled/` |
| Cancel | Moves to `Rejected/` |

---

## Vault Flow

```
Inbox/ or Drop/
    └── main_watcher picks up
            └── Needs_Action/  (AI processes)
                    └── Pending_Approval/  (awaits human review)
                            ├── Approved/   → executes immediately
                            ├── Scheduled/  → executes at scheduled_at time
                            └── Rejected/   → no action
```

---

## Key Design Decisions

**Why file-based workflow?**
Every action leaves a file trail. Nothing happens silently. Full audit log always available in `vault/Archive/` and `vault/Logs/`.

**Why human-in-the-loop for LinkedIn?**
Zero auto-posting policy. Brand reputation requires owner review before anything goes public.

**Why a Scheduled folder?**
Separates "approved but waiting" from "approved and ready now". Watcher checks `scheduled_at` every cycle — no cron jobs, no external schedulers needed.

**Why PID lock files?**
Prevents duplicate watchers even if VS Code, Task Scheduler, or manual runs overlap.

**Why Claude Haiku for skills?**
Fast, cheap, deterministic for classification and drafting. Sonnet reserved for complex multi-step reasoning tasks.

---

## License

[MIT](LICENSE)
