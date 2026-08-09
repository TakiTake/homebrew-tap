#!/usr/bin/env bash
#
# Reruns a workflow run that failed without ever reaching a runner.
#
# GitHub sometimes cannot hand a queued job to a hosted runner and eventually
# gives up. The job then ends `cancelled` with no steps, no runner name and no
# log; the run ends `failure`; and the only record of the cause is a check
# annotation reading "The job was not acquired by Runner of type hosted even
# after multiple attempts". Run 31124742050 is the case this was written for:
# `detect` sat unassigned for 15m48s on a schedule trigger, then died that way.
#
# Nothing in this repository causes that and nothing here can prevent it. But
# nothing ran either, so rerunning is always safe — that is the entire fix.
#
# Deliberately narrow: only that one annotation triggers a rerun. A broken tag,
# a formula that fails audit, a bug in these scripts — those must stay red, and
# rerunning them would only spend a second runner to hide them for an hour.
set -euo pipefail

die() { printf '::error::%s\n' "$*" >&2; exit 1; }

for var in GH_TOKEN REPO RUN_ID; do
  eval "value=\${${var}:-}"
  [ -n "$value" ] || die "${var} must be set"
done

# GitHub's exact wording could change; this substring is the part that names the
# condition. Matching too loosely is the dangerous direction — it would rerun
# real failures — so it stays anchored on "acquired by Runner".
marker="was not acquired by Runner"

# `cancelled` as well as `failure`: a job that never started is reported as
# cancelled, so filtering on failure alone would miss the only case this exists
# for. Successful and skipped jobs cannot carry the annotation.
check_runs="$(gh api --paginate \
  "repos/${REPO}/actions/runs/${RUN_ID}/jobs?per_page=100" \
  --jq '.jobs[] | select(.conclusion == "failure" or .conclusion == "cancelled") | .check_run_url')"

unacquired=""
while IFS= read -r check_run; do
  [ -n "$check_run" ] || continue
  # Captured rather than piped into `grep -q`: under `pipefail` a grep that
  # exits on its first match can SIGPIPE `gh` and leave the pipeline status at
  # 141, which would read as "no match" in exactly the case there was one.
  messages="$(gh api "${check_run}/annotations" --jq '.[].message')"
  case "$messages" in
    *"$marker"*) unacquired="$check_run"; break ;;
  esac
done <<EOF
${check_runs}
EOF

if [ -z "$unacquired" ]; then
  echo "run ${RUN_ID}: no job failed for want of a runner, leaving it red"
  exit 0
fi

echo "run ${RUN_ID}: ${unacquired} never reached a runner, rerunning"
# The whole run, not `--failed`. The jobs at issue conclude `cancelled`, and the
# rerun-failed-jobs API is defined in terms of failed ones; a full rerun has no
# such ambiguity. It is affordable because both watched workflows are safe to
# repeat: update-formula is a poll that re-checks for an already-open PR before
# opening one, and ci only reads.
gh run rerun "$RUN_ID" --repo "$REPO"
