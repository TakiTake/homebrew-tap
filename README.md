# homebrew-tap

Homebrew tap for [TakiTake](https://github.com/TakiTake)'s tools.

```sh
brew install TakiTake/tap/<formula>
```

## Formulae

- [`pall8t`](Formula/pall8t.rb) — run AI coding agents in [apple/container](https://github.com/apple/container) sandboxes. See [TakiTake/pall8t](https://github.com/TakiTake/pall8t).
- [`vpnp`](Formula/vpnp.rb) — AWS Client VPN on macOS without breaking [apple/container](https://github.com/apple/container). See [TakiTake/vpnp](https://github.com/TakiTake/vpnp).
- [`openvpn-aws`](Formula/openvpn-aws.rb) — prebuilt patched OpenVPN for AWS Client VPN SAML federation (used by vpnp). See [TakiTake/openvpn-aws](https://github.com/TakiTake/openvpn-aws).

## Automated updates

[`update-formula.yml`](.github/workflows/update-formula.yml) polls the upstream
repositories hourly and opens a PR when a formula falls behind the latest
release. It is pull-based on purpose: a push-based design would need a token
with write access to this tap stored in each upstream repository, so this way
no cross-repo credential exists at all.

Every update lands as a PR for review — the last checkpoint before a change
reaches `brew upgrade` users. Run it on demand from the Actions tab, or locally
without touching git state:

```sh
DRY_RUN=1 .github/scripts/update-formula.sh <formula>   # show what would change
.github/scripts/validate.sh                             # what CI checks
.github/scripts/brew-check.sh                           # brew style + audit (needs brew)
```

`CHECK_ONLY=1` answers only "is an update available?" through the exit status
(0 yes, 100 no). Unlike `DRY_RUN` it queries GitHub for existing PRs, so it
needs an authenticated `gh`; without one it fails rather than guessing.

`brew-check.sh` stages this checkout as `takitake/tap-check` — a scratch tap
name, so it cannot disturb a real `takitake/tap` you have installed.

GitHub does not start workflow runs for pull requests opened with
`GITHUB_TOKEN`, so automated PRs show no checks. That is not the same as
unchecked: the workflow runs them itself, before the PR exists.

It runs as two jobs for that reason. `detect` polls on `ubuntu-latest` and
answers only "is there work?" — the same script in `CHECK_ONLY` mode, so the
question is decided by exactly the code that would do the work. `update` then
runs on `macos-latest`, where it renders the formula and gates it on `brew
style` and `brew audit` before committing, so a formula Homebrew rejects never
becomes a PR at all.

That gate covers style, component order and deprecated APIs. It does *not* cover
version ordering: Homebrew's revision and version-scheme audits require
`brew audit --git`, and they could not run here anyway, since the gate
deliberately runs before the commit exists. Keeping `pkg_version` monotonic is
`render_formula.py`'s job, and its tests are what hold that line.

The split exists because the poll finds nothing on roughly 23 of every 24 runs,
and paying macOS setup hourly to check something that changes a few times a
month is not worth it. `detect` never pushes, so push and PR creation stay
together in one job and no half-finished git state can cross the boundary.
