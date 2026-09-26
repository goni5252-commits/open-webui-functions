#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -lt 2 ]; then
  echo 'Usage: bash scripts/publish.sh "commit message" file [file ...]' >&2
  exit 1
fi
message=$1
shift
test -n "$message"
test "$(git branch --show-current)" = main || { echo 'Publish requires main.' >&2; exit 1; }
test "$(git remote get-url origin)" = https://github.com/goni5252-commits/open-webui-functions.git || { echo 'Unexpected origin.' >&2; exit 1; }
git diff --cached --quiet || { echo 'Existing staged changes: review them before publishing.' >&2; exit 1; }
has_changelog=false
for path in "$@"; do
  case "$path" in
    CHANGELOG.md) has_changelog=true ;;
    README.md|AGENTS.md|.gitignore|functions/*.py|function-*.json|scripts/*.py|scripts/*.sh|tests/*.py|harness/open-terminal/*.md|harness/open-terminal/*.json|harness/open-terminal/skills/*/SKILL.md|harness/open-terminal/scripts/*.py|harness/open-terminal/examples/*.json|harness/open-terminal-harness-v*.zip|harness/open-terminal-harness-v*.zip.sha256) ;;
    *) echo "Unsupported publish path: $path" >&2; exit 1 ;;
  esac
  case "$path" in *..*|/*) echo 'Use repository-relative file paths.' >&2; exit 1 ;; esac
  test -f "$path" || { echo "Not a file: $path" >&2; exit 1; }
done
$has_changelog || { echo 'Include CHANGELOG.md with every publication.' >&2; exit 1; }
if git ls-files --error-unmatch CHANGELOG.md >/dev/null 2>&1; then
  git diff --quiet -- CHANGELOG.md && { echo 'Add a new changelog entry first.' >&2; exit 1; }
fi
python3 scripts/build_exports.py --check
python3 scripts/build_harness.py --check
git diff --check
git fetch origin main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || {
  echo 'Local and remote main differ. Reconcile or retry an existing unpushed commit first.' >&2; exit 1;
}
git push --dry-run origin HEAD:main
git add -- "$@"
git diff --cached --check
git commit -m "$message"
git push origin HEAD:main
echo "Published: https://github.com/goni5252-commits/open-webui-functions/commit/$(git rev-parse HEAD)"
