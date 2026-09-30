#!/usr/bin/env bash
# SessionStart: fetch origin and fast-forward only when that is provably safe; report everything else.
# Output: hookSpecificOutput.additionalContext, one "SYNC:" line per fact. Always exits 0.
# Never resets, rebases, stashes, checks out, switches, pulls with merge or forces: the only write is
# `git merge --ff-only`, and only on a clean tree. Portable to macOS bash 3.2 (no GNU timeout, no jq).
set -u
export LC_ALL=C GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never

FETCH_TIMEOUT=10
lines=""
say() { lines="${lines}SYNC: $*
"; }

json_escape() {
  # Escape backslash and double quote, drop tabs and CRs; newlines become \n.
  printf '%s' "$1" | tr -d '\r' | tr '\t' ' ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }'
}

emit() {
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
    "$(json_escape "${lines%
}")"
  exit 0
}

# Runs "$@" in its own process group and kills the whole group after $1 seconds.
# Returns the command's status, or 124 on timeout.
run_with_timeout() {
  local secs=$1 out=$2 pid deadline
  shift 2
  deadline=$((SECONDS + secs))
  set -m
  "$@" >"$out" 2>&1 &
  pid=$!
  set +m
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 0.3
      kill -KILL -- "-$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 0.1
  done
  wait "$pid"
}

# Upstream of a local branch, only if its remote-tracking ref still exists.
upstream_of() {
  local u
  u=$(git for-each-ref --format='%(upstream:short)' "refs/heads/$1" 2>/dev/null)
  [ -n "$u" ] && git rev-parse --verify --quiet "$u^{commit}" >/dev/null && echo "$u"
}

count() { git rev-list --count "$@" 2>/dev/null || echo "?"; }
short() { git rev-parse --short "$1" 2>/dev/null || echo "?"; }

# --- Repo dir: stdin JSON "cwd", falling back to $CLAUDE_PROJECT_DIR, then $PWD.
input=""
[ -t 0 ] || input=$(cat 2>/dev/null)
dir=$(printf '%s' "$input" | tr -d '\n' | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
[ -n "$dir" ] && [ -d "$dir" ] || dir=${CLAUDE_PROJECT_DIR:-$PWD}

if ! cd "$dir" 2>/dev/null || ! git rev-parse --git-dir >/dev/null 2>&1; then
  say "$dir is not a git repository — nothing synced."
  emit
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  say "no 'origin' remote — nothing fetched or synced; ask before continuing."
  emit
fi

# --- Fetch with a hard timeout; on failure keep going with cached refs.
fetch_ok=1
tmp=$(mktemp "${TMPDIR:-/tmp}/sync-main.XXXXXX")
# stderr of the call hides bash's "Terminated" job notice when the fetch is killed.
run_with_timeout "$FETCH_TIMEOUT" "$tmp" git fetch origin --prune --quiet 2>/dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  fetch_ok=0
  if [ "$rc" -eq 124 ]; then
    why="timed out after ${FETCH_TIMEOUT}s"
  else
    why=$(grep -v '^[[:space:]]*$' "$tmp" | head -1 | cut -c1-160)
    [ -n "$why" ] || why="exit $rc"
  fi
  say "OFFLINE: git fetch origin failed ($why). Comparisons below use cached refs and may be stale — tell JP before working."
fi
rm -f "$tmp"

# --- Default branch: origin/HEAD, falling back to main.
def=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
def=${def#origin/}
[ -n "$def" ] || def=main
up_def="origin/$def"
if ! git rev-parse --verify --quiet "refs/remotes/$up_def" >/dev/null; then
  say "$up_def does not exist locally (never fetched?) — nothing synced; ask before continuing."
  emit
fi

# --- Working tree state.
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
busy=""
for f in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply BISECT_LOG; do
  [ -e "$(git rev-parse --git-path "$f")" ] && busy="$busy ${f}"
done

branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
head_sha=$(short HEAD)

if [ -z "$branch" ]; then
  say "detached HEAD at $head_sha ($(count "$up_def..HEAD") ahead, $(count "HEAD..$up_def") behind $up_def) — nothing changed; ask before continuing."
elif [ -n "$busy" ]; then
  say "$branch has an operation in progress (${busy# }) — nothing changed; ask before continuing."
else
  ahead=$(count "$up_def..HEAD")
  behind=$(count "HEAD..$up_def")
  upstream=$(upstream_of "$branch")
  dirty_note=""
  [ "$dirty" -gt 0 ] && dirty_note=" Working tree has $dirty uncommitted/untracked path(s)."

  if [ "$branch" = "$def" ]; then
    if [ "$ahead" = 0 ] && [ "$behind" = 0 ]; then
      if [ "$dirty" -gt 0 ]; then
        say "$def == $up_def ($head_sha) but the tree is dirty.$dirty_note Ask before continuing."
      else
        say "$def == $up_def ($head_sha)"
      fi
    elif [ "$ahead" != 0 ] && [ "$behind" != 0 ]; then
      say "$def has DIVERGED from $up_def ($ahead ahead, $behind behind) — nothing changed; ask before continuing.$dirty_note"
    elif [ "$ahead" != 0 ]; then
      say "$def is $ahead ahead of $up_def (local commits not on origin) — nothing changed; ask before continuing.$dirty_note"
    elif [ "$dirty" -gt 0 ]; then
      say "$def is $behind behind $up_def but the tree is dirty — nothing changed; ask before continuing.$dirty_note"
    elif git merge --ff-only --quiet "$up_def" >/dev/null 2>&1; then
      say "$def fast-forwarded $head_sha → $(short HEAD) ($behind commit(s)); $def == $up_def"
    else
      say "$def is $behind behind $up_def and the fast-forward failed — nothing changed; ask before continuing."
    fi
  elif [ "$ahead" = 0 ] && [ -z "$upstream" ]; then
    # Fresh branch (e.g. a new worktree): nothing of its own and never pushed.
    if [ "$behind" = 0 ]; then
      if [ "$dirty" -gt 0 ]; then
        say "$branch (new branch, no upstream) == $up_def ($head_sha) but the tree is dirty.$dirty_note Ask before continuing."
      else
        say "$branch (new branch, no upstream) == $up_def ($head_sha)"
      fi
    elif [ "$dirty" -gt 0 ]; then
      say "$branch (new branch, no upstream) is $behind behind $up_def but the tree is dirty — nothing changed; ask before continuing.$dirty_note"
    elif git merge --ff-only --quiet "$up_def" >/dev/null 2>&1; then
      say "$branch (new branch, no upstream) fast-forwarded $head_sha → $(short HEAD) ($behind commit(s)); $branch == $up_def"
    else
      say "$branch (new branch) is $behind behind $up_def and the fast-forward failed — nothing changed; ask before continuing."
    fi
  else
    msg="$branch is $ahead ahead, $behind behind $up_def"
    if [ -n "$upstream" ]; then
      msg="$msg; vs $upstream: $(count "$upstream..HEAD") ahead, $(count "HEAD..$upstream") behind"
    elif [ -n "$(git config "branch.$branch.merge" 2>/dev/null)" ]; then
      msg="$msg; its upstream is gone (deleted on origin)"
    else
      msg="$msg; no upstream"
    fi
    if [ "$behind" != 0 ] || [ "$dirty" -gt 0 ]; then
      msg="$msg — ask before continuing.$dirty_note"
    else
      msg="$msg — non-default branch: continue only if JP said so."
    fi
    say "$msg"
  fi
fi

# --- Local branches with commits not on their upstream (or on no remote at all when there is none).
unpushed=""
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  u=$(upstream_of "$b")
  if [ -n "$u" ]; then
    n=$(count "$u..$b")
    [ "$n" != 0 ] && unpushed="$unpushed, $b ($n not on $u)"
  else
    n=$(count "$b" --not --remotes)
    [ "$n" != 0 ] && unpushed="$unpushed, $b ($n on no remote, no upstream or upstream gone)"
  fi
done
[ -n "$unpushed" ] && say "unpushed local branches: ${unpushed#, } — remind JP to push before ending the session."

emit
