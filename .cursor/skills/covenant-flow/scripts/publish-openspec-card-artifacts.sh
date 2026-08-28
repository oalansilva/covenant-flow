#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  publish-openspec-card-artifacts.sh --repo <owner/repo> --issue <number> --change <change-name> [--change-dir <path>] [--gist-id <id>] [--comment-id <id>] [--desc <gist description>] [--prototype-url <http-url>] [--prototype-path <repo-path>] [--snapshot-path <repo-path>] [--design-md-words <n>] [--html-generated-bytes <n|N/A>] [--html-copied-bytes <n|N/A>] [--spawn-count <n>]

Publishes OpenSpec text artifacts to a secret GitHub Gist and comments the linked
GitHub issue/card with the Gist URL. Run this before implementation edits.

Republication mode:
  --gist-id <id>    Updates the existing Gist from a previous publication of the
                    same change instead of creating a new one (no Gist sprawl).
  --comment-id <id> Updates the existing card comment (from a previous run)
                    instead of posting a duplicate comment. Requires --gist-id.
  Without --gist-id, a new Gist is created and a new comment is posted
  (first publication).

Gist contents are ONLY text OpenSpec artifacts:
  proposal.md, design.md, tasks.md, specs/**/*.md

Never upload HTML/CSS/JS prototypes to the Gist as the review surface.
Never upload `.impeccable/critique/` to the Gist; pass --snapshot-path so the card
comment links the git-tracked snapshot for T7.
HTML prototypes must be published to the consumer's browsable static path
and passed via `--prototype-url` (never a host-only default in this helper).
USAGE
}

repo=""
issue=""
change=""
change_dir=""
gist_id=""
comment_id=""
desc=""
prototype_url=""
prototype_path=""
snapshot_path=""
design_md_words=""
html_generated_bytes=""
html_copied_bytes=""
spawn_count=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="${2:-}"; shift 2 ;;
    --issue) issue="${2:-}"; shift 2 ;;
    --change) change="${2:-}"; shift 2 ;;
    --change-dir) change_dir="${2:-}"; shift 2 ;;
    --gist-id) gist_id="${2:-}"; shift 2 ;;
    --comment-id) comment_id="${2:-}"; shift 2 ;;
    --desc) desc="${2:-}"; shift 2 ;;
    --prototype-url) prototype_url="${2:-}"; shift 2 ;;
    --prototype-path) prototype_path="${2:-}"; shift 2 ;;
    --snapshot-path) snapshot_path="${2:-}"; shift 2 ;;
    --design-md-words) design_md_words="${2:-}"; shift 2 ;;
    --html-generated-bytes) html_generated_bytes="${2:-}"; shift 2 ;;
    --html-copied-bytes) html_copied_bytes="${2:-}"; shift 2 ;;
    --spawn-count) spawn_count="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$repo" || -z "$issue" || -z "$change" ]]; then
  usage >&2
  exit 2
fi

if [[ -n "$comment_id" && -z "$gist_id" ]]; then
  printf '--comment-id requires --gist-id (republication mode).\n' >&2
  usage >&2
  exit 2
fi

if [[ -z "$change_dir" ]]; then
  change_dir="openspec/changes/$change"
fi

if [[ ! -d "$change_dir" ]]; then
  printf 'OpenSpec change directory not found: %s\n' "$change_dir" >&2
  exit 1
fi

sources=()
for name in proposal.md design.md tasks.md; do
  if [[ -f "$change_dir/$name" ]]; then
    sources+=("$change_dir/$name")
  fi
done

if [[ -d "$change_dir/specs" ]]; then
  while IFS= read -r file; do
    case "$file" in
      *.md) sources+=("$file") ;;
    esac
  done < <(find "$change_dir/specs" -type f | sort)
fi

if [[ -d "$change_dir/prototype" ]]; then
  printf 'Note: skipping %s/prototype from Gist (use --prototype-url for the browsable screen).\n' "$change_dir"
fi

if [[ -d "$change_dir/.impeccable" || -d ".impeccable/critique" ]]; then
  printf 'Note: skipping .impeccable/critique from Gist (use --snapshot-path for the T7 link).\n'
fi

if [[ ${#sources[@]} -eq 0 ]]; then
  printf 'No OpenSpec artifacts found in %s\n' "$change_dir" >&2
  exit 1
fi

if [[ -z "$desc" ]]; then
  desc="$repo openspec $change"
fi

if [[ -z "$prototype_url" ]]; then
  for candidate in \
    "frontend/public/prototypes/$change/index.html" \
    "frontend/public/prototypes/$change/carteira-stables.html"
  do
    if [[ -f "$candidate" ]]; then
      prototype_path="${prototype_path:-$candidate}"
      break
    fi
  done
fi

body_file="$(mktemp)"
publish_dir="$(mktemp -d)"
trap 'rm -rf "$publish_dir"; rm -f "$body_file"' EXIT

publish_files=()
publish_names=()
for source in "${sources[@]}"; do
  relative="${source#"$change_dir"/}"
  publish_name="${relative//\//__}"
  publish_path="$publish_dir/$publish_name"
  cp "$source" "$publish_path"
  publish_files+=("$publish_path")
  publish_names+=("$publish_name")
done

if [[ -n "$gist_id" ]]; then
  printf 'Updating existing Gist %s (change %s).\n' "$gist_id" "$change"
  payload="$(mktemp)"
  {
    printf '{ "files": {'
    first=1
    for name in "${publish_names[@]}"; do
      path=""
      for source in "${sources[@]}"; do
        relative="${source#"$change_dir"/}"
        if [[ "${relative//\//__}" == "$name" ]]; then
          path="$source"
          break
        fi
      done
      if [[ $first -eq 0 ]]; then printf ','; fi
      first=0
      content="$(cat "$path")"
      printf '"%s": {"content": %s}' "$name" "$(jq -Rn --arg c "$content" '$c')"
    done
    printf ' } }'
  } > "$payload"
  gh api -X PATCH "gists/$gist_id" --input "$payload" >/dev/null
  rm -f "$payload"
  gist_url="$(gh gist view "$gist_id" --json html_url -q .html_url 2>/dev/null || printf 'https://gist.github.com/%s' "$gist_id")"
else
  printf 'Creating new Gist for change %s.\n' "$change"
  gist_url="$(gh gist create "${publish_files[@]}" --desc "$desc")"
fi

bt='`'
{
  printf '## OpenSpec vinculado ao card\n\n'
  printf 'Change: %s%s%s\n\n' "$bt" "$change" "$bt"
  printf 'Artefatos **textuais** publicados no Gist (proposal/design/specs/tasks). HTML de protótipo **não** entra no Gist.\n\n'
  printf '### Arquivos no Gist\n'
  for name in "${publish_names[@]}"; do
    printf '%s\n' "- ${bt}${name}${bt}"
  done
  printf '\nGist: %s\n\n' "$gist_url"
  printf 'Comandos:\n'
  printf '%s\n' '```bash'
  printf 'gh gist view %s\n' "$gist_url"
  for name in "${publish_names[@]}"; do
    printf 'gh gist view %s --filename %s\n' "$gist_url" "$name"
  done
  printf '%s\n' '```'
  if [[ -n "$prototype_url" ]]; then
    printf '\n### Protótipo navegável (tela)\n'
    printf '%s\n' "- **Abrir:** ${prototype_url}"
    if [[ -n "$prototype_path" ]]; then
      printf '%s\n' "- Path: ${bt}${prototype_path}${bt}"
    fi
    printf '%s\n' '- Não use o Gist para visualizar HTML.'
  fi
  if [[ -n "$snapshot_path" ]]; then
    printf '\n### Snapshot Impeccable\n'
    printf '%s\n' "- Path: ${bt}${snapshot_path}${bt}"
    printf '%s\n' '- Gist OpenSpec **não** é a crítica. Alan abre este arquivo no T7.'
    printf '%s\n' '- Apply e Code Review **não** lêem `.impeccable/critique/`.'
  fi
  if [[ -n "$design_md_words" || -n "$html_generated_bytes" || -n "$html_copied_bytes" || -n "$spawn_count" ]]; then
    printf '\n### Proxies\n'
    printf '%s\n' "- \`design.md\` words: ${design_md_words:-N/A}"
    printf '%s\n' "- HTML generated vs copied: ${html_generated_bytes:-N/A} vs ${html_copied_bytes:-N/A}"
    printf '%s\n' "- Spawns: ${spawn_count:-N/A}"
  fi
} > "$body_file"

if [[ -n "$comment_id" ]]; then
  printf 'Updating existing comment %s.\n' "$comment_id"
  gh api -X PATCH "repos/$repo/issues/comments/$comment_id" \
    -F body=@"$body_file" >/dev/null
  comment_url="https://github.com/$repo/issues/$issue#issuecomment-$comment_id"
elif [[ -n "$gist_id" ]]; then
  printf 'Gist updated (no duplicate comment posted). Use --comment-id to refresh the card comment.\n'
  comment_url=""
else
  comment_url="$(gh issue comment "$issue" --repo "$repo" --body-file "$body_file")"
fi

printf 'gist_url=%s\n' "$gist_url"
if [[ -n "$comment_url" ]]; then
  printf 'comment_url=%s\n' "$comment_url"
fi
if [[ -n "$prototype_url" ]]; then
  printf 'prototype_url=%s\n' "$prototype_url"
fi
