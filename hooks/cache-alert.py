#!/usr/bin/env python3
"""Desktop alert shortly before an idle session's prompt cache expires.

  cache-alert.py arm      Stop hook: start a background timer for this session.
  cache-alert.py cancel   UserPromptSubmit, PreCompact, SessionEnd: stop it.
  cache-alert.py wait ... the detached timer itself (started by arm).

The timer fires LEAD_SECONDS before the 1h cache written by the last request
expires, and only when the context is big enough for a cold resume to cost
something. The notification says what the rewrite would cost and what to do:
reply to keep the cache warm, /compact while compaction is cheap, or /clear.
Sessions on the 5m cache are skipped; ten minutes' warning is longer than the
cache lives. Set COST_HYGIENE_CACHE_ALERT=0 to turn alerts off.

Hooks never block; on any error they print {} and exit 0.
"""
import datetime as dt, json, os, shutil, signal, subprocess, sys, time

TAIL_BYTES = 400_000
MIN_TOKENS = 50_000   # matches the status line's near-expiry warning
LEAD_SECONDS = 600
TTL_SECONDS = 3600
WRITE_RATES = {  # $/MTok for a 1h cache write, as in statusline.sh
    'fable': 20, 'opus-5-5': 8, 'opus': 10, 'sonnet': 4, 'haiku': 2,
}


def config_dir():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')


def pid_file(session):
    d = os.path.join(config_dir(), 'cost-hygiene', 'cache-alert')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, os.path.basename(session) + '.pid')


def last_request(path):
    """(model, context tokens, cache TTL in seconds, response time) of the last request."""
    with open(path, 'rb') as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL_BYTES))
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
        cc = u.get('cache_creation') or {}
        ttl = 300 if cc.get('ephemeral_5m_input_tokens') and not cc.get('ephemeral_1h_input_tokens') else TTL_SECONDS
        try:
            at = dt.datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')).timestamp()
        except Exception:
            at = time.time()
        return msg.get('model') or '', ctx, ttl, at
    return None


def cancel(session):
    """Kill this session's timer, if one is running."""
    path = pid_file(session)
    try:
        with open(path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        os.remove(path)
    except OSError:
        pass
    # Only kill the pid if it is still our timer for this session, not a reused pid.
    try:
        cmd = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    if 'cache-alert.py wait ' + session in cmd:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def arm(data):
    session, tp = data.get('session_id'), data.get('transcript_path')
    if not session:
        return
    cancel(session)
    if os.environ.get('COST_HYGIENE_CACHE_ALERT') == '0' or not tp or not os.path.exists(tp):
        return
    found = last_request(tp)
    if not found:
        return
    model, ctx, ttl, at = found
    if ctx < MIN_TOKENS or ttl < TTL_SECONDS:
        return
    fire_at = at + ttl - LEAD_SECONDS
    if fire_at <= time.time():
        return
    p = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), 'wait', session, tp,
         str(os.path.getsize(tp)), str(int(fire_at)), str(ctx), model, data.get('cwd') or ''],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True)
    with open(pid_file(session), 'w') as f:
        f.write(str(p.pid))


def resumed(tp, offset):
    """Whether the session has had a prompt or response since the timer was armed.
    A backstop for a missed cancel hook; bookkeeping entries do not count."""
    try:
        with open(tp, 'rb') as f:
            f.seek(offset)
            tail = f.read().decode('utf-8', 'replace')
    except OSError:
        return True
    for line in tail.split('\n'):
        try:
            if json.loads(line).get('type') in ('user', 'assistant'):
                return True
        except (ValueError, AttributeError):
            continue
    return False


def notify(title, subtitle, body):
    if sys.platform == 'darwin':
        # Pass text as arguments so quotes in it cannot break the script.
        subprocess.run(['osascript',
                        '-e', 'on run argv',
                        '-e', 'display notification (item 3 of argv) with title (item 1 of argv) subtitle (item 2 of argv)',
                        '-e', 'end run', title, subtitle, body], timeout=10)
    elif shutil.which('notify-send'):
        subprocess.run(['notify-send', '--app-name=Claude Code', title,
                        (subtitle + ': ' if subtitle else '') + body], timeout=10)


def wait(session, tp, offset, fire_at, ctx, model, cwd):
    time.sleep(max(0, int(fire_at) - time.time()))
    path = pid_file(session)
    try:
        with open(path) as f:
            if int(f.read().strip()) != os.getpid():
                return
        os.remove(path)
    except (OSError, ValueError):
        return
    if resumed(tp, int(offset)):
        return
    ctx = int(ctx)
    rate = next((r for k, r in WRITE_RATES.items() if k in model), WRITE_RATES['opus'])
    mins = max(1, round((int(fire_at) + LEAD_SECONDS - time.time()) / 60))
    notify('Claude prompt cache expires in %dm' % mins,
           os.path.basename(cwd.rstrip('/')) if cwd else '',
           '%dk context: resuming later rewrites it for ~$%.2f. '
           'Reply now to keep it warm, /compact to shrink it, or /clear if you are done.'
           % (round(ctx / 1000), ctx * rate / 1e6))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'wait':
        wait(*sys.argv[2:9])
        return
    data = json.load(sys.stdin)
    if mode == 'arm':
        arm(data)
    elif mode == 'cancel' and data.get('session_id'):
        cancel(data['session_id'])
    print('{}')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        if sys.argv[1:2] != ['wait']:
            print('{}')
    sys.exit(0)
