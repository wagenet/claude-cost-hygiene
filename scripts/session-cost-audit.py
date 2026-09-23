#!/usr/bin/env python3
"""Audit Claude Code transcripts for cost-relevant behavior.

Usage: session-cost-audit.py [--days N] [--top N]
Reads <config dir>/projects/*/*.jsonl ($CLAUDE_CONFIG_DIR or ~/.claude), prices every request with Claude Code's own
formula (cache write 2x input for the 1h TTL, cache read 0.1x input, no long-context
premium; verified against cost-state records), and flags sessions that break the
cost rules: context above 200k, resumed after >1h idle with a large context,
manual /compact run late, multi-day sessions. Subagent transcripts count toward
their parent session's cost (the "sub" column); flags cover the main thread only.
"""
import argparse, collections, datetime as dt, glob, json, os, re

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
def ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))

def subagent_cost(fn, seen):
    """Cost of the subagent transcripts stored beside a session, in <session>/subagents/."""
    cost = 0.0
    for sub in glob.glob(os.path.join(fn[:-len('.jsonl')], 'subagents', '*.jsonl')):
        with open(sub) as f:
            for line in f:
                if '"usage"' not in line: continue
                try: d = json.loads(line)
                except ValueError: continue
                m = d.get('message', {}); u = m.get('usage'); rid = d.get('requestId')
                if d.get('type') != 'assistant' or not u or not rid or rid in seen: continue
                seen.add(rid)
                ri, rw, rr, ro = rates(m.get('model', ''))
                cost += (u.get('input_tokens', 0) * ri + u.get('cache_creation_input_tokens', 0) * rw +
                         u.get('cache_read_input_tokens', 0) * rr + u.get('output_tokens', 0) * ro) / 1e6
    return cost

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30); ap.add_argument('--top', type=int, default=15)
    a = ap.parse_args()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)
    rows = []
    for fn in glob.glob(os.path.join(projects_dir(), '*', '*.jsonl')):
        if dt.datetime.fromtimestamp(os.path.getmtime(fn), dt.timezone.utc) < since: continue
        reqs, seen, prompts, compacts, title = [], set(), 0, [], ''
        out_tok, result_tok, reads, later, idx = 0, 0, [], [], 0
        with open(fn) as f:
            for line in f:
                try: d = json.loads(line)
                except ValueError: continue
                t = d.get('type')
                if t in ('custom-title', 'ai-title') and not title: title = d.get('title') or d.get('customTitle') or d.get('aiTitle') or ''
                elif t == 'system' and d.get('subtype') == 'compact_boundary':
                    cm = d.get('compactMetadata') or {}; compacts.append((cm.get('trigger'), cm.get('preTokens') or 0))
                elif t == 'user' and not d.get('isSidechain') and not d.get('isMeta'):
                    c = d.get('message', {}).get('content')
                    if not (isinstance(c, list) and any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in c)): prompts += 1
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get('type') == 'tool_result':
                                x = b.get('content'); result_tok += len(x if isinstance(x, str) else json.dumps(x) if x else '') // 4
                            elif isinstance(b, dict) and b.get('type') == 'text': idx += 1; later.append((idx, b.get('text', '')))
                    elif isinstance(c, str): idx += 1; later.append((idx, c))
                elif t == 'assistant':
                    m = d.get('message', {}); u = m.get('usage'); rid = d.get('requestId')
                    for b in m.get('content', []) or []:
                        if not isinstance(b, dict): continue
                        idx += 1
                        if b.get('type') == 'tool_use':
                            inp = b.get('input') or {}
                            if b.get('name') == 'Read' and inp.get('file_path') and not str(inp['file_path']).endswith(('.png', '.jpg')):
                                reads.append((idx, os.path.basename(inp['file_path'])))
                            elif b.get('name') == 'Bash':
                                for pth in re.findall(r'(?:cat|sed -n \S+|head(?: -\S+)*|tail(?: -\S+)*|bat)\s+(\S+\.(?:rs|ts|tsx|js|py|md|toml|json|ya?ml|c|h|cpp|mm|swift|log|txt))', str(inp.get('command', ''))):
                                    reads.append((idx, os.path.basename(pth)))
                            later.append((idx, json.dumps(inp)))
                        elif b.get('type') == 'text': later.append((idx, b.get('text', '')))
                    if not u or not rid or rid in seen: continue
                    seen.add(rid); out_tok += u.get('output_tokens', 0)
                    ri, rw, rr, ro = rates(m.get('model', ''))
                    cr, cw, o, i = u.get('cache_read_input_tokens', 0), u.get('cache_creation_input_tokens', 0), u.get('output_tokens', 0), u.get('input_tokens', 0)
                    reqs.append(dict(t=ts(d['timestamp']), model=m.get('model', ''), ctx=i + cr + cw, cr=cr, cw=cw,
                                     cost=(i * ri + cw * rw + cr * rr + o * ro) / 1e6, rewrite_cost=cw * rw / 1e6))
        if not reqs: continue
        reqs.sort(key=lambda r: r['t'])
        sub = subagent_cost(fn, seen)
        cost = sum(r['cost'] for r in reqs) + sub; peak = max(r['ctx'] for r in reqs)
        excess = sum(((r['ctx'] - 200_000) / r['ctx']) * (r['cw'] * rates(r['model'])[1] + r['cr'] * rates(r['model'])[2]) / 1e6 for r in reqs if r['ctx'] > 200_000)
        stale = [(r['rewrite_cost'], (r['t'] - p['t']).total_seconds() / 3600) for p, r in zip(reqs, reqs[1:])
                 if (r['t'] - p['t']).total_seconds() > 3600 and r['cw'] > 20_000 and r['cr'] < 0.5 * (p['cr'] + p['cw'])]
        late = [pre for trig, pre in compacts if trig == 'manual' and pre > 150_000]
        span = (reqs[-1]['t'] - reqs[0]['t']).total_seconds() / 3600
        flags = []
        if peak > 200_000: flags.append(f'ctx>200k (peak {peak // 1000}k, ${excess:.0f} excess)')
        if stale: flags.append(f'{len(stale)} stale-resume rewrites (${sum(s[0] for s in stale):.0f})')
        if late: flags.append(f'late /compact at {",".join(str(p // 1000) + "k" for p in late)}')
        if span > 24: flags.append(f'{span / 24:.0f}-day span')
        # context composition: Claude's own output (thinking, tool inputs, text) vs tool results
        own = out_tok / max(1, out_tok + result_tok)
        # relevance proxy: share of files read whose name is mentioned again later in the session
        names = {}
        for i, nm in reads: names.setdefault(nm, i)
        ref = sum(1 for nm, i in names.items() if len(nm) < 5 or any(j > i and os.path.splitext(nm)[0] in txt for j, txt in later))
        relevance = ref / len(names) if names else None
        rows.append(dict(cost=cost, sub=sub, prompts=prompts, reqs=len(reqs), peak=peak, span=span, flags=flags,
                         title=title or os.path.basename(os.path.dirname(fn))[-40:], start=reqs[0]['t'], excess=excess,
                         stale=sum(s[0] for s in stale), models=collections.Counter(r['model'] for r in reqs),
                         own=own, relevance=relevance, nfiles=len(names)))
    rows.sort(key=lambda r: -r['cost'])
    tot = sum(r['cost'] for r in rows)
    print(f'Last {a.days} days: {len(rows)} sessions, est. API-equivalent ${tot:,.0f} '
          f'(${sum(r["sub"] for r in rows):,.0f} in subagents); '
          f'${sum(r["excess"] for r in rows):,.0f} attributable to context beyond 200k; '
          f'${sum(r["stale"] for r in rows):,.0f} to cache rewrites after >1h idle.')
    print(f'{"cost":>6} {"sub":>5} {"prompts":>7} {"reqs":>5} {"peak":>6} {"span":>6} {"own-out":>7} {"reused":>6}  title / flags')
    print('  own-out = share of context growth that is Claude\'s own output (thinking, tool inputs, text) rather than tool results')
    print('  reused  = share of files read that were referred to again later (relevance proxy)')
    for r in rows[:a.top]:
        rel = f'{r["relevance"] * 100:5.0f}%' if r['relevance'] is not None else '     -'
        print(f'${r["cost"]:5.0f} ${r["sub"]:4.0f} {r["prompts"]:7d} {r["reqs"]:5d} {r["peak"] // 1000:5d}k {r["span"]:5.0f}h {r["own"] * 100:6.0f}% {rel}  {r["title"][:50]}')
        for fl in r['flags']: print(f'{"":42}  ! {fl}')
    print(f'\nmodels: {dict(sum((r["models"] for r in rows), collections.Counter()))}')

if __name__ == '__main__': main()
