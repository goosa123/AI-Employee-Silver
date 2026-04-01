# AI Employee Silver — Personal AI Employee Hackathon

> **Tier:** Silver | **Stack:** Claude Code + Python + Gmail API + LinkedIn API + MCP + Obsidian

A fully autonomous Digital FTE (Full-Time Equivalent) that manages Gmail and LinkedIn 24/7 — with human-in-the-loop approval for every sensitive action.

---

## What It Does

| Capability | Details |
|---|---|
| **Gmail Monitoring** | Fetches unread emails every 60s, classifies, auto-replies or routes to approval |
| **LinkedIn Posting** | Takes a brief file, drafts a post via Claude, posts after human approval |
| **Human-in-the-Loop** | Every sensitive action waits in `Pending_Approval/` — nothing executes without owner sign-off |
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
│  email_drafter skill       (Claude Haiku via CLI)          │
│         │                        │                          │
│         ▼                        ▼                          │
│   vault/Pending_Approval/  ←  AI Drafts                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               │  Human reviews → moves to Approved/ or Rejected/
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
│  watchers/main_watcher.py  (every 3s — Inbox/Drop/Vault)   │
│  scripts/generate_dashboard.py  → dashboard.md             │
│  utils/notifier.py  → Windows toast notifications          │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Tool |
|---|---|
| AI Brain | Claude Code (Haiku for skills, Sonnet for tasks) |
| Memory / GUI | Obsidian — local Markdown vault |
| Watchers | Python 3.14 — Gmail + LinkedIn + Filesystem |
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
│   ├── launcher.py          # Single entry point — starts all watchers
│   ├── main_watcher.py      # Vault filesystem watcher (3s interval)
│   └── watcher_config.py    # Polling intervals config
├── processors/
│   ├── gmail_processor.py   # Gmail fetch → classify → draft
│   ├── gmail_approver.py    # Send approved email replies
│   ├── linkedin_processor.py # Brief → draft LinkedIn post
│   └── linkedin_approver.py  # Post approved content to LinkedIn
├── skills/
│   ├── email_classifier/    # Classify emails (Claude Haiku)
│   ├── email_drafter/       # Draft email replies (Claude Haiku)
│   └── linkedin_drafter/    # Draft LinkedIn posts (Claude Haiku)
├── integrations/
│   ├── gmail/               # Gmail API auth, reader, sender
│   └── linkedin/            # LinkedIn config, poster
├── mcp_server/
│   └── server.py            # FastMCP server
├── scripts/
│   ├── generate_dashboard.py # Dashboard + notifications
│   ├── linkedin_auth.py     # One-time LinkedIn OAuth token
│   └── setup_task_scheduler.ps1  # Windows Task Scheduler setup
├── utils/
│   └── notifier.py          # Windows desktop notifications
├── vault/
│   ├── Inbox/               # Drop tasks here
│   ├── Drop/                # Informal input
│   ├── Needs_Action/        # Active work queue
│   ├── Pending_Approval/    # Awaiting human review
│   ├── Approved/            # Human-approved → AI executes
│   ├── Rejected/            # Declined outputs
│   ├── Done/                # Completed tasks
│   ├── Archive/             # Original source files
│   ├── Plans/               # Multi-step task plans
│   ├── Dashboard/           # Live system dashboard
│   ├── Logs/                # Watcher logs
│   ├── gmail/               # Gmail state (processed IDs, PID)
│   └── linkedin/            # LinkedIn state (intake, drafts, PID)
├── credentials/             # OAuth tokens (gitignored)
├── docs/
│   └── WORKFLOW.md          # Vault workflow documentation
├── Company_Handbook.md      # AI rules of engagement (in vault/)
└── .env                     # API credentials (gitignored)
```

---

## Setup

### 1. Install dependencies
```bash
pip install google-auth google-auth-oauthlib google-api-python-client requests python-dotenv winotify
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
Open `vault/` folder in Obsidian. Pin `Dashboard/dashboard.md` for live status.

---

## How to Use

### Submit a task
Drop any `.md` or `.txt` file into `vault/Inbox/` — the watcher picks it up in 3 seconds.

### LinkedIn post
Create a brief in `vault/linkedin/intake/`:
```json
{
  "topic": "AI is transforming Pakistan's tech industry",
  "tone": "professional",
  "audience": "Pakistani tech professionals",
  "key_points": ["Job opportunities", "Skill development", "Freelancing growth"],
  "cta": "Follow for more AI insights"
}
```
Watcher drafts the post → review in `Pending_Approval/` → move to `Approved/` → posted to LinkedIn.

### Review approvals
Check `vault/Pending_Approval/` in Obsidian:
- Move to `vault/Approved/` → action executes
- Move to `vault/Rejected/` → no action

---

## Silver Tier Checklist

- [x] Obsidian vault with Dashboard.md
- [x] Company_Handbook.md (rules of engagement)
- [x] Gmail Watcher (60s polling)
- [x] LinkedIn Watcher (300s polling)
- [x] LinkedIn auto-posting with human approval
- [x] Claude reasoning — Plan.md files in vault/Plans/
- [x] MCP server (FastMCP)
- [x] Human-in-the-loop approval workflow
- [x] Windows Task Scheduler (auto-start on login)
- [x] Agent Skills (email_classifier, email_drafter, linkedin_drafter)
- [x] Desktop notifications (winotify)
- [x] LinkedIn token expiry monitoring

---

## Key Design Decisions

**Why file-based workflow?**
Every action leaves a file trail. Nothing happens silently. Full audit log always available in `vault/Archive/` and `vault/Logs/`.

**Why human-in-the-loop for LinkedIn?**
Zero auto-posting policy. Brand reputation requires owner review before anything goes public.

**Why PID lock files?**
Prevents duplicate watchers even if VS Code, Task Scheduler, or manual runs overlap. Each watcher checks its own PID file on startup.

**Why Claude Haiku for skills?**
Fast, cheap, deterministic for classification and drafting. Sonnet reserved for complex multi-step reasoning tasks.
