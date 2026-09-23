#!/usr/bin/env python3
"""Estimate what a PR cost in Claude Code usage.

Usage: pr-cost.py <branch | PR number> [--repo owner/name]
Sums every request whose transcript entry was recorded on the PR's branch,
across all sessions, worktrees, and subagents on this machine. Priced like
session-cost-audit.py (API-equivalent; cache write = 1h TTL rate).
Misses: work done on another branch (e.g. main) before branching, and other
machines.
"""
import argparse, collections, glob, json, os, subprocess

RATES = {  # $/MTok: input, cache_write(1h), cache_read, output
    'fable': (10, 20, 0.25, 50), 'opus-5-5': (4, 8, 0.2, 20), 'opus': (5, 10, 0.5, 25),
    'sonnet': (2, 4, 0.2, 10), 'haiku': (1, 2, 0.1, 5),
}
def projects_dir():
    return os.path.join(os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude'), 'projects')
def rates(model):
    for k, v in RATES.items():
        if k in model: return v
    return RATES['opus']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target', help='branch name or PR number')
    ap.add_argument('--repo', help='owner/name, for resolving a PR number outside its repo')
    a = ap.parse_args()
    branch = a.target
    if branch.lstrip('#').isdigit():
        cmd = ['gh', 'pr', 'view', branch.lstrip('#'), '--json', 'headRefName', '-q', '.headRefName']
        if a.repo: cmd += ['--repo', a.repo]
        branch = subprocess.check_output(cmd, text=True).strip()

    files = glob.glob(os.path.join(projects_dir(), '*', '*.jsonl')) + \
            glob.glob(os.path.join(projects_dir(), '*', '*', 'subagents', '*.jsonl'))
    seen, sessions = set(), collections.defaultdict(lambda: dict(cost=0.0, reqs=0, sub=0.0, first=None, last=None))
    parts = collections.Counter()
    for fn in files:
        with open(fn) as f:
            for line in f:
                if branch not in line or '"usage"' not in line: continue
                try: d = json.loads(line)
                except ValueError: continue
                if d.get('type') != 'assistant' or d.get('gitBranch') != branch: continue
                rid = d.get('requestId'); m = d.get('message', {}); u = m.get('usage')
                if not u or not rid or rid in seen: continue
                seen.add(rid)
                ri, rw, rr, ro = rates(m.get('model', ''))
                p = dict(input=u.get('input_tokens', 0) * ri, cache_write=u.get('cache_creation_input_tokens', 0) * rw,
                         cache_read=u.get('cache_read_input_tokens', 0) * rr, output=u.get('output_tokens', 0) * ro)
                cost = sum(p.values()) / 1e6
                parts.update({k: v / 1e6 for k, v in p.items()})
                s = sessions[d.get('sessionId', fn)]
                s['cost'] += cost; s['reqs'] += 1
                if d.get('isSidechain'): s['sub'] += cost
                t = d.get('timestamp', '')
                s['first'] = min(filter(None, [s['first'], t])); s['last'] = max(filter(None, [s['last'], t]))

    if not sessions:
        print(f'No requests recorded on branch {branch!r}.'); return
    tot = sum(s['cost'] for s in sessions.values())
    print(f'{branch}: est. ${tot:,.2f} API-equivalent over {sum(s["reqs"] for s in sessions.values())} requests, {len(sessions)} sessions')
    print('  ' + ', '.join(f'{k.replace("_", " ")} ${v:,.2f} ({v / tot:.0%})' for k, v in parts.most_common()))
    print(f'{"cost":>8} {"subagents":>9} {"reqs":>5}  first → last (UTC)')
    for sid, s in sorted(sessions.items(), key=lambda kv: -kv[1]['cost']):
        print(f'${s["cost"]:7.2f} ${s["sub"]:8.2f} {s["reqs"]:5d}  {s["first"][:16]} → {s["last"][:16]}  {sid[:8]}')

if __name__ == '__main__': main()
