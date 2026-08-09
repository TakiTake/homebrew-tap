#!/usr/bin/env bash
#
# Tests for rerun-unacquired.sh.
#
# What is worth pinning here is the decision, not the plumbing: which runs get a
# second attempt and which stay red. Both halves matter — a rerun that never
# fires leaves the flake in place, and one that fires too eagerly buries a real
# failure behind a green retry.
#
# `gh` is stubbed by a script on PATH that answers from fixtures and records
# reruns. It shells out to real jq so the `--jq` expressions in the script under
# test are actually evaluated: those expressions are where the job filter lives,
# and a stub that answered them itself would test nothing.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

failures=0

report() {
  if [ "$1" = "ok" ]; then
    echo "ok: $2"
  else
    printf '::error::%s\n' "FAIL: $2 — $3" >&2
    failures=$((failures + 1))
  fi
}

# Written per case into a fresh directory. `check-runs/<id>` maps to the fixture
# `<id>.json`, mirroring how the script derives the annotations endpoint from a
# job's check_run_url.
UNACQUIRED_ANNOTATIONS='[{"message":"The job was not acquired by Runner of type hosted even after multiple attempts"}]'
GENUINE_ANNOTATIONS='[{"message":"Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/checkout"},{"message":"Process completed with exit code 1."}]'

job() {
  # name, conclusion, check-run id
  printf '{"name":"%s","conclusion":"%s","check_run_url":"https://api.github.com/repos/o/r/check-runs/%s"}' \
    "$1" "$2" "$3"
}

write_stub() {
  local dir="$1"
  cat > "${dir}/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  api)
    shift
    endpoint=""
    jq_expr="."
    while [ $# -gt 0 ]; do
      case "$1" in
        --paginate) ;;
        --jq) shift; jq_expr="$1" ;;
        -*) echo "stub gh: unexpected flag $1" >&2; exit 64 ;;
        *) endpoint="$1" ;;
      esac
      shift
    done
    case "$endpoint" in
      */jobs\?*) fixture="${FIXTURES}/jobs.json" ;;
      */annotations)
        without=${endpoint%/annotations}
        fixture="${FIXTURES}/${without##*/}.json"
        ;;
      *) echo "stub gh: unexpected endpoint ${endpoint}" >&2; exit 64 ;;
    esac
    [ -f "$fixture" ] || { echo "stub gh: no fixture ${fixture}" >&2; exit 64; }
    jq -r "$jq_expr" < "$fixture"
    ;;
  run)
    [ "${2:-}" = "rerun" ] || { echo "stub gh: unexpected run ${2:-}" >&2; exit 64; }
    echo "$3" >> "$RERUN_LOG"
    ;;
  *) echo "stub gh: unexpected command ${1:-}" >&2; exit 64 ;;
esac
STUB
  chmod +x "${dir}/gh"
}

# name, expected ("rerun" | "no-rerun"), jobs JSON array, then id=annotations pairs
run_case() {
  local name="$1" expected="$2" jobs="$3"
  shift 3

  local dir
  dir="$(mktemp -d)"
  mkdir -p "${dir}/bin" "${dir}/fixtures"
  printf '{"jobs":%s}' "$jobs" > "${dir}/fixtures/jobs.json"
  local pair
  for pair in "$@"; do
    printf '%s' "${pair#*=}" > "${dir}/fixtures/${pair%%=*}.json"
  done
  write_stub "${dir}/bin"

  local rc=0 output=""
  # `env` rather than exporting into this shell: each case gets its own PATH and
  # its own rerun log, so a stub left over from a previous case cannot answer.
  output="$(PATH="${dir}/bin:${PATH}" FIXTURES="${dir}/fixtures" \
    RERUN_LOG="${dir}/reruns" GH_TOKEN=t REPO=o/r RUN_ID=4242 \
    ./rerun-unacquired.sh 2>&1)" || rc=$?

  local reran="no-rerun"
  [ -s "${dir}/reruns" ] && reran="rerun"

  if [ "$rc" -ne 0 ]; then
    report fail "$name" "exited ${rc}: ${output}"
  elif [ "$reran" != "$expected" ]; then
    report fail "$name" "expected ${expected}, got ${reran}: ${output}"
  else
    report ok "$name"
  fi
  rm -rf "$dir"
}

# The observed flake: the job never started, so it is reported cancelled with
# the acquisition annotation, and its dependent was skipped.
run_case "unacquired job is rerun" rerun \
  "[$(job detect cancelled 1),$(job update skipped 9)]" \
  "1=${UNACQUIRED_ANNOTATIONS}"

# The case that must stay red. Nothing else in this repository would notice if
# rerunning quietly swallowed it.
run_case "genuine failure is left alone" no-rerun \
  "[$(job update failure 2)]" \
  "2=${GENUINE_ANNOTATIONS}"

# A real failure listed first must not stop the search: the annotation that
# decides this can be on any job in the run.
run_case "unacquired job found after a genuine one" rerun \
  "[$(job audit failure 2),$(job test cancelled 1)]" \
  "2=${GENUINE_ANNOTATIONS}" "1=${UNACQUIRED_ANNOTATIONS}"

# Failure with nothing to inspect — the job list filter yields nothing, and the
# read loop must survive the empty input rather than dying under `set -e`.
run_case "no failed jobs means no rerun" no-rerun \
  "[$(job test success 3)]"

if [ "$failures" -ne 0 ]; then
  printf '::error::%s\n' "${failures} rerun-unacquired test(s) failed" >&2
  exit 1
fi
echo "ok: .github/scripts/rerun-unacquired.sh"
