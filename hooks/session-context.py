#!/usr/bin/env python3
"""UserPromptSubmit hook: tell Claude the current model, effort, and context size.

Reads the tail of the session transcript and finds the last assistant request.
Falls back to settings.json before the first request, and on that request alone
adds a nudge to suggest a cheaper model for small tasks. Never blocks; on any
error it prints {} and exits 0.
"""
import json, os, sys

TAIL_BYTES = 400_000

# Fires once per session: switching models later discards the prompt cache.
MODEL_NUDGE = (
    ' If this task is clearly PR-sized or smaller and the session is on Opus, '
    'say so in one line before starting, with the command: `/model sonnet`, or '
    '`/model haiku` for trivial or batch work. For large multi-package tasks on '
    'Opus, mention `/model opusplan`. Do not repeat this later in the session.'
)


def config_dir():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')


def last_request(path):
    with open(path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read().decode('utf-8', 'replace')
    for line in reversed(chunk.split('\n')):
        if '"assistant"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get('type') != 'assistant':
            continue
        msg = r.get('message', {})
        u = msg.get('usage') or {}
        ctx = (u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0)
               + u.get('cache_read_input_tokens', 0))
        if not ctx:
            continue
        return msg.get('model'), r.get('effort'), ctx
    return None


def from_settings():
    try:
        s = json.load(open(os.path.join(config_dir(), 'settings.json')))
    except Exception:
        return None, None
    return s.get('model'), s.get('effortLevel')


def main():
    data = json.load(sys.stdin)
    found = None
    tp = data.get('transcript_path')
    if tp and os.path.exists(tp):
        found = last_request(tp)
    if found:
        model, effort, ctx = found
        note = 'Session state: model %s, effort %s, context about %dk tokens (as of the previous request).' % (
            model or 'unknown', effort or 'unknown', round(ctx / 1000))
    else:
        model, effort = from_settings()
        note = 'Session state: first request; settings default model %s, effort %s.' % (
            model or 'unknown', effort or 'unknown')
        # settings.json misses a --model flag, so an unset or Opus default still nudges.
        if not model or ('opus' in model and model != 'opusplan'):
            note += MODEL_NUDGE
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'UserPromptSubmit', 'additionalContext': note}}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{}')
    sys.exit(0)
