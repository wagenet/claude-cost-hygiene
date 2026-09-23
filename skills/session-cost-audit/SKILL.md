---
name: session-cost-audit
description: Audit recent Claude Code sessions for cost waste (context beyond 200k, cache rewrites after idle, late compaction, multi-day sessions) and report the most expensive sessions with what to change.
argument-hint: "[--days N] [--top N]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session-cost-audit.py *)
---

Audit output (API-equivalent pricing, all sessions on this machine):

```
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session-cost-audit.py" $ARGUMENTS`
```

Summarize this for the user in a few sentences and a short table. Lead with the
total and the two attributable waste figures (context beyond 200k, cache rewrites
after idle). Then list the flagged sessions with the one change that would have
avoided each flag:

- `ctx>200k`: compact or start a fresh session before the context passes 200k.
- `stale-resume rewrites`: run `/compact` before continuing a session that sat
  idle for over an hour, or start fresh; the cache expires after an hour and the
  whole context is rewritten at the cache-write price.
- `late /compact`: compact earlier, around 120k to 150k tokens.
- `N-day span`: one session per task; long-lived sessions accumulate stale context.

If nothing is flagged, say so in one line. Do not rerun the script.
