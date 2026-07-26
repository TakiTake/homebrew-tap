#!/usr/bin/env bash
#
# Run Homebrew's own checks against this checkout.
#
# brew resolves a formula through the tap it is installed in, never through a
# path — `brew audit <path>` is disabled outright — so the working tree has to
# be staged as a real tap first. That staging carries a trap worth keeping in
# one place: `cp -R` into an existing directory nests the copy one level down,
# leaving brew to inspect an empty tap. Both `brew style` and `brew audit`
# succeed on a tap with no formulae, so the mistake reads as a pass.
#
# Usage: brew-check.sh [formula ...]
#        With no arguments, checks every formula in the tap.
#
set -euo pipefail

# Assigned before `readonly`, which would otherwise mask a failing `cd` and
# leave REPO_ROOT empty — staging would then copy the wrong tree (SC2155).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly REPO_ROOT
# Deliberately NOT takitake/tap. That is where `brew tap takitake/tap` installs
# the real thing, and this script begins by `rm -rf`-ing its target — run on a
# maintainer's Mac it would replace their tap clone with a copy of the working
# tree, mid-update, on a branch that does not exist on origin. A separate name
# makes that collision impossible rather than merely guarded against.
# Lowercase, because that is how Homebrew refers to a tap once installed and how
# the Taps directory has to be named.
readonly TAP="takitake/tap-check"
readonly TAP_PATH="takitake/homebrew-tap-check"

# Belt and braces, not load-bearing: brew only auto-updates for install,
# outdated, upgrade, bundle, release and `tap` with arguments, so neither of the
# commands below would trigger it and neither can have the staged tap's git
# state reset underneath it. Set anyway, because that list is Homebrew's to
# change and the failure it would cause here — auditing the *previous* formula
# contents and reporting a pass — is silent.
export HOMEBREW_NO_AUTO_UPDATE=1

die() { printf '::error::%s\n' "$*" >&2; exit 1; }

command -v brew >/dev/null 2>&1 || die "brew is not installed"

tap_dir="$(brew --repository)/Library/Taps/${TAP_PATH}"
rm -rf "$tap_dir"
mkdir -p "$tap_dir"
cp -R "${REPO_ROOT}/." "$tap_dir/"

# Having just described how staging can silently produce an empty tap, check it
# — and compare contents, not a file count, which cannot tell a stale copy from
# a current one.
count="$(find "${tap_dir}/Formula" -name '*.rb' | wc -l | tr -d ' ')"
[[ "$count" -gt 0 ]] || die "staged no formulae as ${TAP}"
diff -r "${REPO_ROOT}/Formula" "${tap_dir}/Formula" >/dev/null \
  || die "staged tap does not match the working tree; brew would audit stale formulae"
echo "==> staged ${count} formulae as ${TAP}"

# Both commands, always: `brew audit --tap` implies --skip-style, and whether
# that implication also holds for a named formula is not worth depending on.
# Also load-bearing for bash 3.2, where expanding `"$@"` with no positional
# parameters under `set -u` is fatal: the loop below is only ever reached with
# at least one argument.
if [[ "$#" -eq 0 ]]; then
  # Whole tap — used by CI, where an unrelated formula that has drifted should
  # still turn the build red.
  #
  # Note this also lints .github/workflows with actionlint and shellcheck, since
  # the staged tap is a copy of the whole repository. That is free coverage and
  # has already earned its keep, but it means a `brew style` failure here can
  # point at a YAML file rather than a formula. The named-formula path below
  # inspects only the formula, so the update workflow is unaffected.
  brew style "$TAP" || die "brew style found offenses in ${TAP}"
  brew audit --tap "$TAP" || die "brew audit found problems in ${TAP}"
  exit 0
fi

# Named formulae — used by the update workflow, where an unrelated formula that
# is already failing must not block this one's update PR.
#
# Confirmed against a real brew: `brew-check.sh openvpn-aws` staged 3 formulae
# and reported "1 file inspected, no offenses detected", so a tap installed by
# `cp -R` resolves, the scratch tap name works, and the audit really is scoped
# to the named formula rather than quietly widening to the whole tap.
for formula in "$@"; do
  [[ -f "${tap_dir}/Formula/${formula}.rb" ]] \
    || die "no such formula in the staged tap: ${formula}"
  brew style "${TAP}/${formula}" || die "brew style rejected ${formula}"
  brew audit "${TAP}/${formula}" || die "brew audit rejected ${formula}"
done
