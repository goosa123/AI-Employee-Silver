# Per-watcher polling intervals (seconds).
# Edit these values to change how often each watcher checks for new work.
INTERVALS = {
    "main":      3,    # vault/Inbox + vault/Drop file watcher
    "gmail":     60,   # Gmail inbox poller
    "linkedin":  300,  # LinkedIn intake poller
    "facebook":  300,  # Facebook intake poller (future)
}
