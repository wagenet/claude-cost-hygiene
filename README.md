# cost-hygiene

A Claude Code plugin that keeps sessions cheap. It grew out of an audit of a
month of transcripts, where most of the waste came from three things: contexts
that grew past 200k tokens, sessions resumed after the one-hour prompt cache had
expired (every token rewritten at the cache-write price), and effort left high
for a whole session when only one hard step needed it.

## What it does

| Piece | Mechanism | Effect |
|---|---|---|
| Session-state note | `UserPromptSubmit` hook | Every prompt tells Claude the current model, effort level, and context size, read from the transcript. Claude cannot otherwise see these. |
| Effort escalation | `SessionStart` hook | After two failures on the same root cause, Claude stops and suggests `/effort high s` (or, if already high, something else). Re-injected after compaction. |
| `/session-cost-audit [--days N] [--top N]` | skill + script | Prices every session on this machine with Claude Code's own formula and flags the ones that broke a cost rule. |
| `/pr-cost <branch or PR#>` | skill + script | Sums what one branch cost across sessions, worktrees, and subagents. |
| `/cost-hygiene-setup` | skill + installer | Installs the status line (below). One-time, because plugins cannot set `statusLine`. |

### Status line

Shows model, effort, context size with an escalating `/compact` nudge, and the
prompt cache: a warm countdown, a warning when it is about to expire on a big
context, and when it has gone cold, the estimated cost of the next message. A
recent cache miss is named so you can avoid repeating its cause.

```
Opus high | 136k heavy: /compact soon | cache warm 42m
Opus high | 210k HEAVY: /compact now | COLD: next msg ~$1.68
```

Requires `jq`.

## Install

```
claude plugin marketplace add wagenet/claude-cost-hygiene
claude plugin install cost-hygiene@claude-cost-hygiene
```

Then, inside Claude Code, run `/cost-hygiene-setup` once to install the status
line, and restart. The hooks and the two audit skills work immediately.

From a local checkout:

```
claude plugin marketplace add /path/to/claude-cost-hygiene
claude plugin install cost-hygiene@claude-cost-hygiene
```

The install is a copy of the committed tree. After editing the plugin, bump
`version` in `.claude-plugin/plugin.json` (the updater treats an unchanged
version as current), commit, run `claude plugin update cost-hygiene@claude-cost-hygiene`,
and restart Claude Code.

## Pricing assumptions

Costs are API-equivalent estimates: input, 1h cache write (2x input), cache read
(0.1x input), and output, per model family. They match Claude Code's own cost
records but are not what a subscription bills. Rates live at the top of each
script in `scripts/`.

## Layout

```
.claude-plugin/plugin.json       manifest
.claude-plugin/marketplace.json  lets the repo be added as a marketplace
hooks/hooks.json                 registers the two hooks
hooks/session-context.py         UserPromptSubmit: session-state note
hooks/session-start.py           SessionStart: effort-escalation rule
scripts/session-cost-audit.py    /session-cost-audit
scripts/pr-cost.py               /pr-cost
scripts/install-statusline.sh    /cost-hygiene-setup
statusline/statusline.sh         the status line script
skills/*/SKILL.md                the three slash commands
```

All scripts need only python3 (3.8+) and, for the status line, `jq`. They
respect `CLAUDE_CONFIG_DIR`.
