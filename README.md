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
```

GitHub does not start workflow runs for pull requests opened with
`GITHUB_TOKEN`, so automated PRs show no checks — `validate.sh` runs inside the
job that creates them instead.
