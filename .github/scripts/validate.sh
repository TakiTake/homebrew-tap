#!/usr/bin/env bash
#
# Everything that must hold before a formula change is pushed. Run by ci.yml on
# human PRs, and by update-formula.yml before it opens an automated one —
# GitHub does not start workflow runs for pull requests created with
# GITHUB_TOKEN, so the automated PRs would otherwise go unchecked.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

die() { printf '::error::%s\n' "$*" >&2; exit 1; }

# A missing interpreter is a warning locally and a hard failure in CI, so the
# gate never silently degrades where it actually guards something.
require() {
  local what="$1"
  if [[ -n "${CI:-}" ]]; then
    die "${what} is required to validate this repository"
  fi
  printf '%s\n' "warning: ${what} not found, skipping that check" >&2
}

if command -v ruby >/dev/null 2>&1; then
  for formula in Formula/*.rb; do
    ruby -c "$formula" >/dev/null
    echo "ok: $formula"
  done
else
  require ruby
fi

# Every script, not just update-formula.sh: brew-check.sh runs only on a macOS
# runner mid-update, so a syntax error in it would otherwise first surface there.
for script in .github/scripts/*.sh; do
  bash -n "$script"
  echo "ok: $script"
done

command -v python3 >/dev/null 2>&1 || die "python3 is required to validate this repository"

if python3 -c "import yaml" 2>/dev/null; then
  python3 -c '
import sys, yaml
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        yaml.safe_load(fh)
    print(f"ok: {path}")
' .github/workflows/*.yml
else
  # Soft on purpose, even in CI: GitHub refuses to run a workflow it cannot
  # parse, so this only buys an earlier, clearer error. Not worth turning CI red
  # over a missing library on a runner image.
  printf '%s\n' "warning: PyYAML not found, skipping workflow YAML check" >&2
fi

python3 .github/scripts/test_render_formula.py

# Hard in CI like the ruby check, not soft like the PyYAML one: a missing jq
# does not merely lose an earlier error message here, it silently drops a test
# suite. jq is a dependency of that suite alone — `gh --jq` in the script under
# test uses gh's own built-in jq, so nothing in a real run needs this.
if command -v jq >/dev/null 2>&1; then
  .github/scripts/test_rerun_unacquired.sh
else
  require jq
fi
