---
name: pr-cost
description: Estimate what a pull request or branch cost in Claude Code usage, summing every request recorded on that branch across sessions, worktrees, and subagents on this machine.
argument-hint: "<branch | PR number> [--repo owner/name]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pr-cost.py *)
---

Cost estimate (API-equivalent pricing; misses work done on other branches or other machines):

```
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr-cost.py" $ARGUMENTS`
```

Report the total, the split between cache reads, cache writes, input, and output,
and the number of sessions. If cache writes dominate, note that the branch was
worked on in sessions that went cold between prompts. If one session accounts
for most of the cost, name it. Do not rerun the script.
