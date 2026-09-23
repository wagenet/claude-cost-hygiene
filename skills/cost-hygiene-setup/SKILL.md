---
name: cost-hygiene-setup
description: Install the cost-hygiene status line (model, effort, context size, warm/cold prompt cache with the cost of a cold resume) into the user's Claude Code settings. Run once after installing the plugin.
argument-hint: "[--force]"
disable-model-invocation: true
allowed-tools: Bash(sh ${CLAUDE_PLUGIN_ROOT}/scripts/install-statusline.sh *)
---

Plugins cannot set `statusLine`, so this one-time step copies the plugin's status
line script into the user's Claude config directory and points settings at it.

Run:

```
sh "${CLAUDE_PLUGIN_ROOT}/scripts/install-statusline.sh" $ARGUMENTS
```

Then relay its output. If it reports that a status line script already exists
and differs, show the user the diff it printed and explain that rerunning with
`--force` replaces their copy (a timestamped backup is kept). Do not pass
`--force` unless the user asked for it. Remind the user to restart Claude Code
for the status line change to take effect.
