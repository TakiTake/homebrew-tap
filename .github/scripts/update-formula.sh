#!/usr/bin/env bash
#
# Update a single formula to the latest upstream release, and open a PR.
#
# Polls public release metadata only: no credential with write access to the
# upstream repositories exists anywhere in this design. The token used here is
# the workflow's own GITHUB_TOKEN, scoped to this repository.
#
# Usage:  update-formula.sh <formula>
# Env:    DRY_RUN=1     render and validate, but touch no git state
#         CHECK_ONLY=1  as DRY_RUN, but answer a single question through the
#                       exit status: 0 = an update is available, 100 = nothing
#                       to do. Used by the cheap ubuntu detector half of the
#                       two-job split, so that "is there work?" is decided by
#                       exactly the code that would do the work — a separate
#                       detector could drift, and the direction that matters
#                       (detector says no, script would have said yes) is a
#                       silently missed update. Unlike DRY_RUN it does query
#                       for existing PRs, or an open PR would re-trigger the
#                       expensive half every hour.
#         BREW_AUDIT=1  additionally gate the rendered formula on brew style
#                       and brew audit. Needs a runner with brew.
#         BASE_SHA      commit every update branch is cut from (default: HEAD).
#                       The workflow pins this once so that a run updating
#                       several formulae does not stack one PR on top of another.
#
set -euo pipefail

# Distinct from `die`'s 1, so the detector can tell "nothing to do" apart from
# "this run broke". Anything else must fail the job rather than read as no-op.
readonly EXIT_NOTHING_TO_DO=100

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# `gh` resolves the repository from the working directory, so anchor there
# rather than inheriting whatever the caller happened to be in.
cd "$REPO_ROOT"

die() { printf '::error::%s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*" >&2; }

# Treat 0/false/no as off, so DRY_RUN=0 means what it looks like it means.
is_true() {
  case "${1:-}" in
    "" | 0 | false | False | FALSE | no | No | NO | off | OFF) return 1 ;;
    *) return 0 ;;
  esac
}

if is_true "${DRY_RUN:-}"; then dry_run=1; else dry_run=0; fi
if is_true "${CHECK_ONLY:-}"; then check_only=1; else check_only=0; fi

# Mutually exclusive rather than "one of them wins": set together, DRY_RUN's
# shortcut in skip_if_already_handled would suppress the existing-PR check while
# CHECK_ONLY still reported an update as available — work pending for a branch
# whose PR is already open.
if [[ "$dry_run" -eq 1 && "$check_only" -eq 1 ]]; then
  die "set DRY_RUN or CHECK_ONLY, not both: they disagree about whether to check for an existing PR"
fi
# Both modes stop short of touching git; they differ only in what they report.
no_git=0
if [[ "$dry_run" -eq 1 || "$check_only" -eq 1 ]]; then no_git=1; fi

# The brew gate inspects the formula in the working tree, which the read-only
# modes deliberately never write. Asking for it here would render, pass, and
# report success having audited the *previous* formula — a false green from a
# gate that was requested and silently did not run. Refuse instead.
if [[ "$no_git" -eq 1 ]] && is_true "${BREW_AUDIT:-}"; then
  die "BREW_AUDIT cannot apply in a read-only mode: it gates the formula in the working tree, which DRY_RUN and CHECK_ONLY do not touch. Drop BREW_AUDIT, or run .github/scripts/brew-check.sh directly."
fi

# --- hardcoded formula table -------------------------------------------------
# Never derived from workflow input. Adding a formula is a reviewed commit here.
formula_config() {
  case "$1" in
    pall8t)
      repo="TakiTake/pall8t"
      asset_template="pall8t-@TAG@-aarch64-apple-darwin.tar.gz"
      has_sha256_asset=1
      ;;
    vpnp)
      repo="TakiTake/vpnp"
      asset_template="vpnp-@TAG@-aarch64-apple-darwin.tar.gz"
      has_sha256_asset=0
      ;;
    openvpn-aws)
      repo="TakiTake/openvpn-aws"
      asset_template="openvpn-aws-@TAG@-aarch64-apple-darwin.tar.gz"
      has_sha256_asset=0
      ;;
    *)
      die "unknown formula: $1"
      ;;
  esac
}

# --- helpers -----------------------------------------------------------------
gh_api() {
  local url="https://api.github.com/$1"
  # Built as one never-empty array rather than a separate `auth` array that is
  # empty when unauthenticated: expanding an empty array under `set -u` is an
  # error in bash 3.2, which is what /bin/bash is on macOS — and this script now
  # runs there.
  local -a curl_args=(
    -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28"
  )
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl_args+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl "${curl_args[@]}" "$url"
}

# Syntax-check the rendered formula. Required everywhere except a local dry run
# on a machine without Ruby — CI runners always have it, so the gate never
# silently degrades where it matters.
validate_ruby() {
  if command -v ruby >/dev/null 2>&1; then
    ruby -c "$1" >/dev/null
    return
  fi
  # Either read-only mode, run by hand on a machine without ruby. Still gated on
  # CI being unset, so the check never degrades where it is load-bearing.
  if [[ "$no_git" -eq 1 && -z "${CI:-}" ]]; then
    log "==> warning: ruby not found, skipping syntax check (read-only run)"
    return 0
  fi
  die "ruby is required to validate the rendered formula"
}

# Homebrew-level validation, on top of `ruby -c`. A syntax check proves the file
# parses; brew style and brew audit understand component order, dependency order
# and deprecated APIs that it cannot see. Off by default so the ubuntu detector
# and local dry runs stay cheap; the macOS half of the split sets BREW_AUDIT=1,
# and there a missing brew is a broken workflow rather than a reason to skip.
# Called after the formula has been rewritten, so brew-check.sh re-stages the
# tap from the working tree each time — a stale copy would audit the previous
# contents and pass.
validate_brew() {
  is_true "${BREW_AUDIT:-}" || return 0
  log "==> ${formula}: brew style / brew audit"
  "${REPO_ROOT}/.github/scripts/brew-check.sh" "$formula" \
    || die "${formula}: Homebrew rejected the rendered formula"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Parse the release payload once. Emits three tab-separated fields: the tag, the
# asset's download URL, and the sha256 the API publishes for it (empty if the
# release predates asset digests). The sidecar `.sha256` URL follows on line 2.
read_release() {
  python3 - "$1" "$2" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as fh:
    release = json.load(fh)
wanted = sys.argv[2]

def find(name):
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            digest = asset.get("digest") or ""
            digest = digest[7:] if digest.startswith("sha256:") else ""
            return asset.get("browser_download_url", ""), digest
    return "", ""

url, digest = find(wanted)
sidecar, _ = find(f"{wanted}.sha256")
print(f'{release.get("tag_name", "")}\t{url}\t{digest}')
print(sidecar)
PY
}

# No pipe on purpose: `sed ... | head -1` would let head close the pipe early and
# take the whole script down with SIGPIPE under `pipefail`.
formula_field() {
  local matches
  matches="$(sed -n "s/^[[:space:]]*$2[[:space:]]\{1,\}\"\(.*\)\"\$/\1/p" "$1")"
  printf '%s\n' "${matches%%$'\n'*}"
}

# `revision` is the one unquoted field.
formula_revision() {
  local matches
  matches="$(sed -n "s/^[[:space:]]*revision[[:space:]]\{1,\}\([0-9]\{1,\}\)\$/\1/p" "$1")"
  printf '%s\n' "${matches%%$'\n'*}"
}

up_to_date() {
  log "==> ${formula}: $1"
  [[ "$check_only" -eq 1 ]] && exit "$EXIT_NOTHING_TO_DO"
  exit 0
}

# Exit 0 if this branch has already been handled — an open or closed PR, or a
# branch sitting on origin. --state all is deliberate: a PR closed by a human is
# a decision, not an invitation to reopen it on the next hourly run. Both checks
# fail closed, so a transient API error is never read as "nothing exists".
skip_if_already_handled() {
  local candidate="$1" existing_pr ls_rc=0
  # Deliberately not skipped under CHECK_ONLY: an open PR is exactly the case
  # the detector exists to suppress.
  [[ "$dry_run" -eq 1 ]] && return 0

  if ! existing_pr="$(gh pr list --state all --head "$candidate" --json number \
      --jq '.[].number' 2>"${workdir}/gh.err")"; then
    die "${formula}: could not query existing PRs for ${candidate}: $(<"${workdir}/gh.err")"
  fi
  [[ -n "$existing_pr" ]] && up_to_date "PR for ${candidate} already exists, nothing to do"

  git -C "$REPO_ROOT" ls-remote --exit-code --heads origin "$candidate" >/dev/null 2>&1 || ls_rc=$?
  case "$ls_rc" in
    # The PR check above already returned, so a branch here has no PR attached:
    # a push that got stranded when PR creation failed. Reporting that as
    # "nothing to do" would drop the formula from automation behind a green
    # run, so make it loud instead.
    0) die "${formula}: branch ${candidate} is on origin with no PR — a previous run was interrupted after pushing. Delete the branch to let this retry." ;;
    2) return 0 ;; # no such ref upstream — the expected path
    *) die "${formula}: could not query origin for ${candidate} (git exit ${ls_rc})" ;;
  esac
}

# Tags are <upstream version>-<build number>. The build number maps onto
# Homebrew's `revision`, not onto the version: a rebuild of the same upstream
# version must still register as an upgrade for `brew upgrade`.
derive_version_and_revision() {
  new_version="${1#v}"
  new_revision=0
  if [[ "$new_version" =~ ^(.+)-([0-9]+)$ ]]; then
    new_version="${BASH_REMATCH[1]}"
    new_revision="${BASH_REMATCH[2]}"
  fi
}

# --- main --------------------------------------------------------------------
formula="${1:?usage: update-formula.sh <formula>}"
formula_config "$formula"
formula_path="${REPO_ROOT}/Formula/${formula}.rb"
[[ -f "$formula_path" ]] || die "no such formula file: ${formula_path}"

# The update path rewrites git state and its recovery paths use
# `checkout --force`. Refuse to run on top of someone's unsaved work — and check
# before doing any network work, so the failure is immediate and obvious.
if [[ "$no_git" -eq 0 ]] && ! git -C "$REPO_ROOT" diff --quiet HEAD --; then
  die "${formula}: working tree has uncommitted changes; refusing to touch git state (use DRY_RUN=1)"
fi

# Explicit templates: BSD mktemp wants one, and this now runs on macOS too.
release_json="$(mktemp "${TMPDIR:-/tmp}/update-formula.XXXXXX")"
workdir="$(mktemp -d "${TMPDIR:-/tmp}/update-formula.XXXXXX")"

# Set once, and covers every exit path. `orig_ref` is set only once the
# git-mutating section starts, so before that this degrades to removing the
# temporary files.
pushed=0
cleanup() {
  local rc=$?
  if [[ "$rc" -ne 0 && "$pushed" -eq 1 ]]; then
    # A pushed branch with no PR is worse than no branch: the fail-closed guard
    # would treat the formula as handled and skip it on every future run.
    if [[ -n "$(gh pr list --state all --head "$branch" --json number --jq '.[].number' 2>/dev/null)" ]]; then
      log "==> ${formula}: a PR for ${branch} exists after all, leaving the branch alone"
      rm -rf "$release_json" "$workdir"
      return
    fi
    log "==> ${formula}: opening the PR failed, deleting ${branch} from origin"
    git -C "$REPO_ROOT" push origin --delete "$branch" >/dev/null 2>&1 \
      || log "==> ${formula}: could not delete ${branch} from origin — delete it by hand, or the next run will skip this formula"
  fi
  if [[ -n "${orig_ref:-}" ]]; then
    git -C "$REPO_ROOT" checkout --force "$orig_ref" >/dev/null 2>&1 \
      || git -C "$REPO_ROOT" checkout --force --detach "$base_sha" >/dev/null 2>&1 \
      || true
  fi
  rm -rf "$release_json" "$workdir"
}
trap cleanup EXIT

log "==> ${formula}: fetching latest release of ${repo}"
gh_api "repos/${repo}/releases/latest" >"$release_json" \
  || die "${formula}: failed to query releases for ${repo}"

IFS=$'\t' read -r tag _ _ < <(read_release "$release_json" "") || true
[[ -n "${tag:-}" ]] || die "${formula}: release has no tag_name"

# Validate before the tag reaches a filename, a URL, or a git ref — and keep it
# narrow deliberately. Homebrew derives each formula's version from the url via
# a long ordered chain of parsers, and render_formula.py has to predict that
# derivation to decide whether a revision resets or climbs. Rather than try to
# reimplement the chain, admit only the two shapes whose derivation has been
# confirmed against a real `brew` — <digits.digits...> with an optional
# `-<build>` suffix. Anything else (a prerelease tail, a date, a trailing
# hyphen) stops the run for a human to look at, which is the right outcome
# anyway: `releases/latest` already excludes prereleases, so such a tag arriving
# here means something unusual happened upstream.
readonly TAG_PATTERN='^v[0-9]+(\.[0-9]+){1,3}(-[0-9]+)?$'
[[ "$tag" =~ $TAG_PATTERN ]] \
  || die "${formula}: tag '${tag}' does not match ${TAG_PATTERN}"

# The asset name is only knowable once the tag is, so re-read the payload now
# that the template can be filled in. Cheap: the file is already on disk.
asset_name="${asset_template//@TAG@/$tag}"
expected_url="https://github.com/${repo}/releases/download/${tag}/${asset_name}"
{
  IFS=$'\t' read -r tag download_url api_sha256
  read -r published_sha_url
} < <(read_release "$release_json" "$asset_name")

# Resolve the asset through the release payload rather than trusting the URL we
# just built, so a missing asset fails loudly instead of 404-ing mid-download.
[[ -n "${download_url:-}" ]] || die "${formula}: release ${tag} has no asset named ${asset_name}"
[[ "$download_url" == "$expected_url" ]] \
  || die "${formula}: asset URL ${download_url} is not the expected ${expected_url}"

current_url="$(formula_field "$formula_path" url)"
current_sha256="$(formula_field "$formula_path" sha256)"

# Idempotence, cheapest checks first. The URL alone is not enough: an asset
# re-uploaded under an unchanged tag would leave the formula pinned to a stale
# hash forever, and `brew install` would then fail for everyone. When the API
# publishes a digest we can settle it without downloading.
if [[ "$current_url" == "$expected_url" && -n "${api_sha256:-}" \
      && "$current_sha256" == "$api_sha256" ]]; then
  up_to_date "already at ${tag}, nothing to do"
fi

# When the formula is simply behind, the branch name depends only on the tag —
# so check for an existing PR before downloading anything. Otherwise every
# hourly run would re-fetch the asset for as long as a PR sits open.
if [[ "$current_url" != "$expected_url" ]]; then
  skip_if_already_handled "update/${formula}-${tag}"
fi

log "==> ${formula}: downloading ${asset_name}"
curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 -o "${workdir}/${asset_name}" "$download_url" \
  || die "${formula}: download failed for ${download_url}"
new_sha256="$(sha256_of "${workdir}/${asset_name}")"

if [[ -n "${api_sha256:-}" && "$new_sha256" != "$api_sha256" ]]; then
  die "${formula}: download does not match the digest the API published — computed ${new_sha256}, expected ${api_sha256}"
fi

if [[ "$current_url" == "$expected_url" && "$current_sha256" == "$new_sha256" ]]; then
  up_to_date "already at ${tag}, nothing to do"
fi

# The `.sha256` sidecar ships from the same release as the tarball, so this
# detects a corrupted or truncated transfer — not a tampered release. Upstream
# authenticity is explicitly out of scope (issue #1, non-goals).
if [[ "$has_sha256_asset" -eq 1 ]]; then
  [[ -n "${published_sha_url:-}" ]] \
    || die "${formula}: release ${tag} is missing the expected ${asset_name}.sha256"
  curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 -o "${workdir}/published.sha256" "$published_sha_url" \
    || die "${formula}: download failed for ${published_sha_url}"
  published_sha256="$(grep -oiE '[0-9a-f]{64}' "${workdir}/published.sha256" || true)"
  published_sha256="$(printf '%s' "${published_sha256%%$'\n'*}" | tr 'A-F' 'a-f')"
  [[ -n "$published_sha256" ]] \
    || die "${formula}: could not find a sha256 in ${asset_name}.sha256"
  [[ "$published_sha256" == "$new_sha256" ]] \
    || die "${formula}: sha256 mismatch — computed ${new_sha256}, published ${published_sha256}"
  log "==> ${formula}: sha256 matches the checksum published alongside the asset"
fi

# A same-tag re-upload is a genuinely new change, so its branch must not collide
# with the one whose PR shipped the original asset.
branch="update/${formula}-${tag}"
if [[ "$current_url" == "$expected_url" ]]; then
  branch="update/${formula}-${tag}-${new_sha256:0:8}"
  log "==> ${formula}: asset for ${tag} changed under an unchanged tag"
  skip_if_already_handled "$branch"
fi

derive_version_and_revision "$tag"

render() {
  NEW_URL="$expected_url" NEW_SHA256="$new_sha256" \
  NEW_REVISION="$new_revision" \
  python3 "${REPO_ROOT}/.github/scripts/render_formula.py" "$1" "$2"
}

if [[ "$no_git" -eq 1 ]]; then
  render "$formula_path" "${workdir}/rendered.rb" || die "${formula}: render failed"
  validate_ruby "${workdir}/rendered.rb" \
    || die "${formula}: rendered formula is not valid Ruby"
  # Rendering is the last thing that can rule an update out, so only report one
  # as available once it has actually produced a valid formula. brew validation
  # is deliberately not run here: the detector has no brew, and re-checking on
  # the macOS half is the point of the split.
  if [[ "$check_only" -eq 1 ]]; then
    log "==> ${formula}: an update to ${tag} is available"
    exit 0
  fi
  log "==> ${formula}: would update to ${tag} (dry run)"
  diff -u "$formula_path" "${workdir}/rendered.rb" || true
  exit 0
fi

base_sha="${BASE_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
git -C "$REPO_ROOT" rev-parse --verify --quiet "${base_sha}^{commit}" >/dev/null \
  || die "${formula}: BASE_SHA ${base_sha} is not a commit in this repository"

# Where to put HEAD back. On a runner this is a detached base_sha either way,
# but locally it returns the developer to the branch they were on. Setting it
# also arms the checkout-restoring half of the EXIT trap.
orig_ref="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD || echo "$base_sha")"

git -C "$REPO_ROOT" checkout -B "$branch" "$base_sha" >/dev/null 2>&1 \
  || die "${formula}: could not create branch ${branch}"

render "$formula_path" "${workdir}/rendered.rb" || die "${formula}: render failed"
cp "${workdir}/rendered.rb" "$formula_path"

validate_ruby "$formula_path" || die "${formula}: rendered formula is not valid Ruby"
# Before the commit, so a formula brew rejects never becomes a PR at all. This
# is the whole reason the expensive half of the split runs on macOS.
validate_brew

if git -C "$REPO_ROOT" diff --quiet -- "Formula/${formula}.rb"; then
  log "==> ${formula}: render produced no change, nothing to do"
  exit 0
fi

# The version is what this script derived from the tag; Homebrew derives its own
# from the url and nothing here cross-checks the two, so say where it came from
# rather than implying it is Homebrew's. The revision is read back off the
# rendered formula because the renderer may raise it past the build number to
# keep pkg_version moving after a same-tag re-upload.
version_note=$'\n''- version: `'"${new_version}"'` (derived from the tag)'
rendered_revision="$(formula_revision "$formula_path")"
if [[ -n "$rendered_revision" ]]; then
  version_note+=$'\n''- revision: `'"${rendered_revision}"'` (raises pkg_version so `brew upgrade` picks this up)'
fi
sha_note="computed from the downloaded asset"
if [[ "$has_sha256_asset" -eq 1 ]]; then
  sha_note="${sha_note}, and matches the \`.sha256\` published alongside it"
fi

# The PR page will show no checks at all (see the body below), so spell out what
# did run — otherwise "no checks" reads as "unchecked".
checks_note="ran \`validate.sh\` against the base commit and syntax-checked the rendered formula"
if is_true "${BREW_AUDIT:-}"; then
  # No "on macOS" here: this is keyed on BREW_AUDIT, which says nothing about
  # the OS, and a local run would then write a claim about a runner into the PR.
  checks_note="${checks_note}, then gated it on \`brew style\` and \`brew audit\` before committing"
fi

git -C "$REPO_ROOT" add "Formula/${formula}.rb"
git -C "$REPO_ROOT" commit -m "${formula}: update to ${tag}" \
  -m "Automated update from ${repo} release ${tag}." >/dev/null
git -C "$REPO_ROOT" push --set-upstream origin "$branch" >/dev/null
pushed=1

gh pr create \
  --base "${GITHUB_REF_NAME:-main}" \
  --head "$branch" \
  --title "${formula}: update to ${tag}" \
  --body "Automated update from [\`${repo}\`](https://github.com/${repo}/releases/tag/${tag}) release \`${tag}\`.

- asset: \`${asset_name}\`
- sha256: \`${new_sha256}\` (${sha_note})${version_note}

Opened by \`.github/workflows/update-formula.yml\`, which polls public release
metadata on a schedule. The checksum above confirms the download was not
corrupted in transit; it is not a proof of upstream authenticity.

GitHub does not start workflow runs for pull requests opened by \`GITHUB_TOKEN\`,
so this PR shows no checks. That is not the same as unchecked — the workflow run
that opened it ${checks_note}. Please review before merging: this is the last
checkpoint before the change reaches \`brew upgrade\` users."

pushed=0
log "==> ${formula}: opened PR for ${tag}"
