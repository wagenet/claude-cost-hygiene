#!/bin/sh
# Install the cost-hygiene status line into the user's Claude config.
# Usage: install-statusline.sh [--force]
#   Copies statusline/statusline.sh to <config>/statusline.sh and sets
#   settings.statusLine to run it with a 60s refresh (so the cache countdown
#   ticks). Refuses to overwrite a differing script unless --force is given.
#   Always backs up settings.json (and the script, on --force) with a timestamp.
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
src="$here/statusline/statusline.sh"
cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
dst="$cfg/statusline.sh"
settings="$cfg/settings.json"
stamp=$(date +%Y%m%d-%H%M%S)
force=0
[ "${1:-}" = "--force" ] && force=1

command -v jq >/dev/null 2>&1 || { echo "jq is required by the status line script; install it first (brew install jq)." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required to edit settings.json." >&2; exit 1; }
mkdir -p "$cfg"

if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
  if [ "$force" -eq 1 ]; then
    cp "$dst" "$dst.bak-$stamp"
    echo "Backed up existing status line to $dst.bak-$stamp"
  else
    echo "A different status line already exists at $dst. Diff (yours vs plugin):"
    diff "$dst" "$src" || true
    echo
    echo "Rerun with --force to replace it (a backup will be kept), or merge by hand."
    exit 2
  fi
fi
cp "$src" "$dst"
chmod +x "$dst"
echo "Installed status line script at $dst"

[ -f "$settings" ] && cp "$settings" "$settings.bak-$stamp" && echo "Backed up settings to $settings.bak-$stamp"
python3 - "$settings" "$dst" <<'PY'
import json, os, sys
path, script = sys.argv[1], sys.argv[2]
home = os.path.expanduser('~')
if script.startswith(home + os.sep):
    script = '~' + script[len(home):]
try:
    s = json.load(open(path))
except FileNotFoundError:
    s = {}
s['statusLine'] = {'type': 'command', 'command': script, 'refreshInterval': 60}
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(s, f, indent=2)
    f.write('\n')
os.replace(tmp, path)
print('Set statusLine in %s to %s (refresh every 60s)' % (path, script))
PY
echo "Restart Claude Code to pick up the new status line."
