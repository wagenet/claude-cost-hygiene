#!/usr/bin/env python3
"""SessionStart hook: inject the effort-escalation rule as context.

Plugins cannot add to CLAUDE.md, so the rule is delivered here instead. It runs
on startup, resume, clear, and after compaction, so the rule survives
compaction. Never blocks; on any error it prints {} and exits 0.
"""
import json, sys

RULE = (
    "Effort escalation (cost-hygiene plugin): each user prompt carries a "
    "\"Session state\" note with the current model, effort level, and context size. "
    "If the same test or check has failed twice on the same root cause, or you are "
    "about to start a third approach to the same problem, stop before the next "
    "attempt and report what failed and what you tried. Then, by current effort: "
    "below high, say that `/effort high s` (session-only) may help. At high, judge "
    "whether the failures come from missing information or a wrong approach, or from "
    "reasoning depth (subtle logic, concurrency, many interacting constraints); only "
    "for depth, say that `/effort xhigh s` may help. At xhigh or above, or at high "
    "when depth is not the problem, say so and propose what else would help instead: "
    "more context, a different decomposition, or the user's input. Never suggest "
    "lowering effort as an escalation, and never suggest max. When the hard part is "
    "done, remind the user to drop effort back to their default."
)


def main():
    sys.stdin.read()
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'SessionStart', 'additionalContext': RULE}}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{}')
    sys.exit(0)
