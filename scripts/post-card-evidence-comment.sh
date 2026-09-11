#!/usr/bin/env bash
set -u -o pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/post-card-evidence-comment.sh \
  --transition done|homologado|pronto \
  --card <number> \
  --commit <sha> \
  [--pr <number>] \
  [--branch <name>] \
  [--summary <text>] [--tests <text>] [--qa <text>] \
  --review <text> (required for --transition done) \
  [--package <name>] [--cards <list>] [--deploy <evidence>] [--branches <list>] \
  [--dry-run]

Posts the canonical evidence comment (AGENTS.md templates) for a card
transition, deduplicating by transition + commit ref: if a comment for the
same transition already exists with the same commit ref (or with no
recognizable ref), nothing is posted and the existing comment is reported.

Transitions:
  done        "Implementação concluída." (AGENTS.md Kanban Done template)
  homologado  "Homologado por Alan na develop."
  pronto      "Publicado em main." (AGENTS.md Kanban Pronto template)

For --review on done, cite the local Code Review result, e.g.:
  diff-reviewer (uncommitted vs HEAD): no findings
  diff-reviewer (origin/develop...HEAD): no findings
  code-reviewer: no findings

Dedup normalization:
  - URL commits: github.com/.../commit/<sha>
  - "PR N (sha)" and "Commit/merge: <ref>" forms
  - Ref-less legacy comments of the same transition also block posting

Fail-closed: if REST `GET /repos/<owner>/<repo>/issues/<n>/comments` fails, the script exits with an error
and does NOT post, preventing duplicates.
USAGE
}

repo="oalansilva/crypto"
transition=""
card=""
commit=""
pr=""
branch=""
summary=""
tests=""
qa=""
review=""
package=""
cards=""
deploy=""
branches=""
dry_run=0

take2() {
  if [[ $# -lt 2 ]]; then
    printf 'ERROR: option "%s" requires a value\n' "${1:-}" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --transition) take2 "$@"; transition="$2"; shift 2 ;;
    --card) take2 "$@"; card="$2"; shift 2 ;;
    --commit) take2 "$@"; commit="$2"; shift 2 ;;
    --pr) take2 "$@"; pr="$2"; shift 2 ;;
    --branch) take2 "$@"; branch="$2"; shift 2 ;;
    --summary) take2 "$@"; summary="$2"; shift 2 ;;
    --tests) take2 "$@"; tests="$2"; shift 2 ;;
    --qa) take2 "$@"; qa="$2"; shift 2 ;;
    --review) take2 "$@"; review="$2"; shift 2 ;;
    --package) take2 "$@"; package="$2"; shift 2 ;;
    --cards) take2 "$@"; cards="$2"; shift 2 ;;
    --deploy) take2 "$@"; deploy="$2"; shift 2 ;;
    --branches) take2 "$@"; branches="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help|help) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

error() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ -n "$transition" ]] || error "--transition is required (done|homologado|pronto)"
case "$transition" in
  done|homologado|pronto) ;;
  *) error "invalid --transition '$transition' (expected done|homologado|pronto)" ;;
esac
[[ -n "$card" ]] || error "--card <number> is required"
[[ -n "$commit" ]] || error "--commit <sha> is required"
if [[ "$transition" == "done" && -z "$review" ]]; then
  error "--review is required for done (cite diff-reviewer uncommitted, vs develop, and code-reviewer)"
fi

commit_norm="$(printf '%s' "$commit" | tr '[:upper:]' '[:lower:]')"

extract_ref() {
  local body="$1"
  local out=""
  body="$(printf '%s' "$body" | tr '[:upper:]' '[:lower:]')"
  out="$(printf '%s' "$body" | grep -oE 'github\.com/[^ )]+/commit/[0-9a-f]{7,40}' | grep -oE '[0-9a-f]{7,40}$' | tail -1 || true)"
  if [[ -z "$out" ]]; then
    out="$(printf '%s' "$body" | grep -oE '\([0-9a-f]{7,40}\)' | tr -d '()' | tail -1 || true)"
  fi
  if [[ -z "$out" ]]; then
    out="$(printf '%s' "$body" | grep -oE 'Commit/merge: [0-9a-f]{7,40}' | grep -oE '[0-9a-f]{7,40}$' | tail -1 || true)"
  fi
  printf '%s' "$out"
}

transition_marker() {
  case "$transition" in
    done) printf 'Implementação concluída.' ;;
    homologado) printf 'Homologado por Alan na develop.' ;;
    pronto) printf 'Publicado em main.' ;;
  esac
}

marker="$(transition_marker)"

comments_json=""
comments_raw=""
if ! comments_raw="$(gh api --paginate "repos/${repo}/issues/${card}/comments" 2>/dev/null)"; then
  error "could not fetch comments for card $card (REST GET /issues/${card}/comments failed); refusing to post (fail-closed)"
fi
# --paginate may emit one JSON array per page concatenated; slurp+add merges them.
if [[ -z "$comments_raw" ]] || ! comments_json="$(printf '%s' "$comments_raw" | jq -se 'if length == 0 then empty elif all(.[]; type == "array") then add else empty end' 2>/dev/null)" || [[ -z "$comments_json" ]]; then
  error "could not fetch comments for card $card (REST comments failed or returned invalid JSON); refusing to post (fail-closed)"
fi
if ! printf '%s' "$comments_json" | jq -e '
  (type == "array") and
  (all(.[]; type == "object" and (.body | type == "string") and (.url | type == "string")))
' >/dev/null 2>&1; then
  error "could not fetch comments for card $card (REST comments failed or returned invalid JSON); refusing to post (fail-closed)"
fi

sha_matches() {
  local a="$1" b="$2"
  [[ "$a" == "$b"* ]] || [[ "$b" == "$a"* ]]
}

duplicate=""
existing_url=""
while IFS=$'\t' read -r body url; do
  if printf '%s' "$body" | grep -qiF "$marker"; then
    existing_ref="$(extract_ref "$body")"
    if [[ -z "$existing_ref" ]]; then
      duplicate="$body"
      existing_url="$url"
      break
    fi
    if sha_matches "$existing_ref" "$commit_norm"; then
      duplicate="$body"
      existing_url="$url"
      break
    fi
  fi
done < <(printf '%s' "$comments_json" | jq -r '.[] | [.body, .url] | @tsv')

if [[ -n "$duplicate" ]]; then
  printf 'DEDUPE: card #%s already has a %s evidence comment with commit ref %s.\n' "$card" "$transition" "$commit_norm"
  printf 'Existing comment: %s\n' "$existing_url"
  exit 0
fi

build_body() {
  case "$transition" in
    done)
      cat <<'EOF'
Implementação concluída.
EOF
      [[ -z "$branch" ]] || printf 'Branch: %s\n' "$branch"
      printf 'Integrado em: develop\n'
      if [[ -n "$pr" ]]; then
        printf 'Commit/merge: PR %s (%s)\n' "$pr" "$commit_norm"
      else
        printf 'Commit/merge: %s\n' "$commit_norm"
      fi
      if [[ -n "$summary" ]]; then
        printf 'Resumo:\n%s\n' "$summary"
      fi
      if [[ -n "$tests" ]]; then
        printf 'Testes executados:\n%s\n' "$tests"
      fi
      if [[ -n "$qa" ]]; then
        printf 'QA:\n%s\n' "$qa"
      fi
      if [[ -n "$review" ]]; then
        printf 'Code Review:\n%s\n' "$review"
      fi
      printf 'Próximo passo: Alan testar/homologar na develop.\n'
      ;;
    homologado)
      cat <<'EOF'
Homologado por Alan na develop.
Apto para próximo pacote de release.
EOF
      ;;
    pronto)
      cat <<'EOF'
Publicado em main.
EOF
      [[ -n "$package" ]] || package="<pacote>"
      printf 'Pacote/release: %s\n' "$package"
      if [[ -n "$cards" ]]; then
        printf 'Cards incluídos: %s\n' "$cards"
      fi
      if [[ -n "$pr" ]]; then
        printf 'Commit/merge: PR %s (%s)\n' "$pr" "$commit_norm"
      else
        printf 'Commit/merge: %s\n' "$commit_norm"
      fi
      [[ -n "$deploy" ]] || deploy="<deploy PROD pendente>"
      printf 'Deploy PROD: %s\n' "$deploy"
      [[ -n "$branches" ]] || branches="<lista ou pendência>"
      printf 'Branches limpas: %s\n' "$branches"
      printf 'Status final: pronto.\n'
      ;;
  esac
}

body="$(build_body)"

printf 'Posting evidence comment for card #%s (%s):\n' "$card" "$transition"
printf '%s\n' "$body" | sed 's/^/  /'

if [[ "$dry_run" -eq 1 ]]; then
  printf 'DRY-RUN: no comment posted.\n'
  exit 0
fi

if ! gh issue comment "$card" --repo "$repo" --body "$body" >/dev/null; then
  error "gh issue comment failed; comment NOT posted for card $card"
fi
printf 'Posted: https://github.com/%s/issues/%s\n' "$repo" "$card"
