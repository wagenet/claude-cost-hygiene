#!/bin/sh
# Claude Code status line: model, effort, and context size. Expensive models,
# high effort, and a large context are each colored to stand out.
# Context is keyed on absolute tokens, not percent — on a 1M window "20%" is
# already 200k tokens.

input=$(cat)

eval "$(printf '%s' "$input" | jq -r '
  "model=" + ((.model.display_name // "Claude") | sub(" \\(.*\\)$"; "") | @sh),
  "effort=" + ((.effort.level // "") | @sh),
  "fast=" + ((.fast_mode // false) | tostring | @sh),
  "tp=" + ((.transcript_path // "") | @sh),
  "tok=" + ((
    (.context_window.current_usage // null) as $u
    | if $u then (($u.input_tokens // 0) + ($u.cache_creation_input_tokens // 0) + ($u.cache_read_input_tokens // 0))
      elif .context_window.used_percentage and .context_window.context_window_size
        then (.context_window.used_percentage * .context_window.context_window_size / 100 | floor)
      else 0 end) | tostring | @sh),
  "mid=" + ((.model.id // "") | @sh),
  "cwarm=" + ((if .prompt_cache.warm == null then "none" else (.prompt_cache.warm | tostring) end) | @sh),
  "cexp=" + ((.prompt_cache.expires_at // 0) | tostring | @sh),
  "crecache=" + ((.prompt_cache.recache_tokens_if_cold // 0) | tostring | @sh),
  "mcause=" + ((.prompt_cache.last_miss_cause // "") as $c
    | (if ($c | type) == "string" then (try ($c | fromjson) catch $c) else $c end)
    | (if type == "object" then (.causes // [])
       elif type == "array" then .
       elif . == "" then []
       else [tostring] end)
    | map(tostring
      | if test("^ttl_expired_") then "idle >" + sub("^ttl_expired_"; "")
        else gsub("_"; " ") end)
    | join(", ") | .[0:40] | @sh),
  "mat=" + ((.prompt_cache.last_miss_at // null) as $t
    | (if $t == null then 0
       elif ($t | type) == "number" then (if $t > 1e12 then $t / 1000 else $t end)
       else (try ($t | sub("\\.[0-9]+"; "") | fromdateiso8601) catch 0) end)
    | floor | tostring | @sh)')"

esc() { printf '\033[%sm' "$1"; }
R=$(esc 0)

# Model: Opus is the baseline and stays plain; cheaper is dim, pricier is loud.
case "$model" in
  *Haiku*|*Sonnet*) mc=$(esc 2) ;;
  *Fable*)          mc=$(esc '1;97;45') ; model=" $model \$\$ " ;;
  *)                mc="" ;;
esac
out="${mc}${model}${R}"

# Effort: quiet at low/medium, loud above.
case "$effort" in
  low|medium) out="$out $(esc 2)${effort}${R}" ;;
  high)       out="$out $(esc '1;33')high${R}" ;;
  xhigh)      out="$out $(esc '1;31')xhigh${R}" ;;
  max)        out="$out $(esc '1;97;41') MAX ${R}" ;;
  "")         ;;
  *)          out="$out ${effort}" ;;
esac

[ "$fast" = "true" ] && out="$out $(esc '1;97;41') FAST \$\$ ${R}"

# Subagents active in the last 2 minutes: model and current context each.
# Reads an undocumented layout (<session>/subagents/agent-*.jsonl), so any
# failure just prints nothing.
sub="${tp%.jsonl}/subagents"
if [ -n "$tp" ] && [ -d "$sub" ]; then
  now=$(date +%s)
  agents=""
  for f in "$sub"/agent-*.jsonl; do
    [ -f "$f" ] || continue
    mt=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null) || continue
    [ $((now - mt)) -le 120 ] || continue
    a=$(tail -n 40 "$f" | jq -rs '[.[] | select(.message.usage)] | last // empty
      | "\(.message.model) \((.message.usage | .input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens) / 1000 | floor)"' 2>/dev/null)
    [ -n "$a" ] || continue
    am=${a% *}; ak=${a##* }
    case "$am" in
      *haiku*)  a="$(esc 2)haiku ${ak}k${R}" ;;
      *sonnet*) a="$(esc 2)sonnet ${ak}k${R}" ;;
      *fable*)  a="$(esc '1;97;45')fable ${ak}k${R}" ;;
      *opus*)   a="opus ${ak}k" ;;
      *)        a="$am ${ak}k" ;;
    esac
    agents="${agents:+$agents, }$a"
  done
  [ -n "$agents" ] && out="$out | agents: $agents"
fi

# Context and cache are always shown (both can be acted on); advice text
# appears only once there is something to do.
k=$((tok / 1000))
if   [ "$tok" -lt 120000 ] 2>/dev/null; then c=$(esc 32); msg=""
elif [ "$tok" -lt 200000 ]; then c=$(esc 33);          msg="heavy: /compact soon"
elif [ "$tok" -lt 300000 ]; then c=$(esc '1;31');      msg="HEAVY: /compact now"
elif [ "$tok" -lt 500000 ]; then c=$(esc '1;97;41');   msg=" ⚠ BLOATED: /compact or /clear "
else                             c=$(esc '1;5;97;41'); msg=" ☠ STOP: save notes, /clear "
fi

if [ "$tok" -eq 0 ] 2>/dev/null; then ctx=" | $(esc 2)fresh${R}"
else ctx=" | ${c}${k}k${msg:+ $msg}${R}"
fi

cache=""
if [ "$cwarm" != "none" ]; then
  now=$(date +%s)
  if [ "$cwarm" = "true" ] && [ "$cexp" -gt "$now" ] 2>/dev/null; then
    mins=$(( (cexp - now + 59) / 60 ))
    # Near expiry on a big context, replying soon avoids a costly rewrite.
    if [ "$mins" -le 10 ] && [ "$tok" -ge 50000 ] 2>/dev/null; then
      cache=" | $(esc 33)cache expires in ${mins}m${R}"
    else
      cache=" | $(esc 2)cache warm ${mins}m${R}"
    fi
  elif [ "$crecache" -ge 50000 ] 2>/dev/null; then
    # Cold cache: the next prompt rewrites the whole context at the cache-write price.
    case "$mid" in
      *fable*)    rate=20 ;;
      *opus-5-5*) rate=8 ;;
      *opus*)     rate=10 ;;
      *sonnet*)   rate=4 ;;
      *haiku*)    rate=2 ;;
      *)          rate=8 ;;
    esac
    usd=$(awk -v t="$crecache" -v r="$rate" 'BEGIN { printf "%.2f", t * r / 1000000 }')
    cache=" | $(esc '1;97;41') COLD: next msg ~\$${usd} ${R}"
  else
    cache=" | $(esc 2)cache cold${R}"
  fi
fi

# Unexpected cache miss in the last 10 minutes: name the cause so the user
# can avoid repeating it (e.g. toggling MCP servers or editing CLAUDE.md
# mid-session). Small contexts are skipped since the rebuild is cheap.
miss=""
if [ -n "$mcause" ] && [ "$tok" -ge 50000 ] 2>/dev/null && [ "$mat" -gt 0 ] 2>/dev/null; then
  if [ $(( $(date +%s) - mat )) -le 600 ]; then
    # Idle expiry (cyan) is expected but costly; other causes (yellow) are avoidable.
    case "$mcause" in
      idle*) miss=" | $(esc "1;96")cache rebuilt: ${mcause}${R}" ;;
      *)     miss=" | $(esc "1;93")cache miss: ${mcause}${R}" ;;
    esac
  fi
fi

printf '%s%s%s%s\n' "$out" "$ctx" "$cache" "$miss"
