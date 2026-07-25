#!/usr/bin/env python3
"""Rewrite a Homebrew formula's url/sha256 (and version/revision) in place.

Two invariants, both enforced here rather than left to review:

  * Every substitution matches exactly once. A formula that has drifted away
    from the shape this script expects fails loudly instead of being silently
    half-updated.
  * The rendered formula's pkg_version is strictly greater than the one it
    replaces. `brew upgrade` orders installs by pkg_version — version plus
    revision — so a render that fails to increase it produces an update that
    users silently never receive, however correct the url and sha256 are.

Usage: render_formula.py <src> <dst>
Env:   NEW_URL, NEW_SHA256, EXPLICIT_VERSION, NEW_VERSION, NEW_REVISION
"""

import os
import re
import sys

URL_RE = r'^([ \t]*)url\s+"[^"]*"$'
SHA_RE = r'^([ \t]*)sha256\s+"[^"]*"$'
VERSION_RE = r'^([ \t]*)version\s+"[^"]*"$'
REVISION_RE = r"^[ \t]*revision\s+\d+\n"

# Read-only counterparts, capturing the value rather than the indent.
URL_VALUE_RE = r'^[ \t]*url\s+"([^"]*)"$'
SHA_VALUE_RE = r'^[ \t]*sha256\s+"([^"]*)"$'
VERSION_VALUE_RE = r'^[ \t]*version\s+"([^"]*)"$'
REVISION_VALUE_RE = r"^[ \t]*revision\s+(\d+)$"

TAG_IN_URL_RE = r"/releases/download/([^/]+)/"


def replace_one(pattern, repl, text, what):
    found = re.findall(pattern, text, flags=re.M)
    if len(found) != 1:
        sys.exit(f"expected exactly one {what} line, found {len(found)}")
    return re.sub(pattern, repl, text, count=1, flags=re.M)


def first_value(text, pattern, default=None):
    found = re.findall(pattern, text, flags=re.M)
    return found[0] if found else default


# A trailing alphabetic component usually marks a prerelease (2.8.0rc1 < 2.8.0),
# but a bare patch letter is a bump, not a prerelease — OpenSSL's 1.1.1w > 1.1.1
# being the case that matters for a formula tracking a statically linked
# OpenSSL. Only the words below are read as "earlier than the plain version".
PRERELEASE_TOKENS = frozenset(
    ("alpha", "beta", "rc", "pre", "preview", "dev", "snapshot", "nightly")
)


def tokenize(version):
    return [int(t) if t.isdigit() else t for t in re.findall(r"\d+|[A-Za-z]+", version)]


def compare_versions(left, right):
    """Order two version-ish strings: -1, 0 or 1.

    Close enough to Homebrew's ordering for the one question asked of it — is
    this release newer than the one already pinned? A numeric component sorts
    above an alphabetic one, so 2.8.0 correctly beats 2.8.0rc1.
    """
    a, b = tokenize(left), tokenize(right)
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        if isinstance(x, int):
            return 1
        if isinstance(y, int):
            return -1
        return -1 if x < y else 1

    if len(a) == len(b):
        return 0
    shared = min(len(a), len(b))
    extra = a[shared] if len(a) > len(b) else b[shared]
    sign = 1 if len(a) > len(b) else -1
    if isinstance(extra, int):
        return sign
    return -sign if extra.lower() in PRERELEASE_TOKENS else sign


def tag_of(url):
    match = re.search(TAG_IN_URL_RE, url or "")
    return match.group(1) if match else None


def resolve_revision(*, version_changed, sha_changed, old_revision, derived_revision):
    """Pick a revision that keeps pkg_version moving forward.

    Keyed on the version, not on the tag. A new version resets the revision —
    not a downgrade even when the number drops, because the version ahead of it
    went up. But two different tags can map to the *same* version: v2.7.5-3 and
    v2.7.5-4 both render version 2.7.5, and a same-tag re-upload in between may
    already have raised the revision past the build number. Whenever the version
    holds still, the revision is the only thing that can register the new bytes,
    so it has to strictly increase.
    """
    if version_changed:
        return derived_revision
    if not sha_changed:
        return old_revision
    return max(derived_revision, old_revision + 1)


def render(text, env):
    new_url = env["NEW_URL"]
    new_sha256 = env["NEW_SHA256"]
    explicit_version = env.get("EXPLICIT_VERSION") == "1"

    old_url = first_value(text, URL_VALUE_RE)
    old_sha256 = first_value(text, SHA_VALUE_RE)
    old_revision = int(first_value(text, REVISION_VALUE_RE, default="0"))
    old_tag, new_tag = tag_of(old_url), tag_of(new_url)

    # Every other unexpected shape in this file is fatal; this one used to
    # degrade to skipping the downgrade check entirely, which is the wrong way
    # for a guard to fail.
    if not old_tag or not new_tag:
        sys.exit(
            f"cannot locate a release tag in the url ({old_url!r} -> {new_url!r}), "
            f"so an upgrade cannot be distinguished from a downgrade"
        )

    downgrade = (
        f"refusing to downgrade: {old_tag} -> {new_tag}. The GitHub API reports "
        f"the most recently published release, not the highest version, so this "
        f"is probably a deleted release or one flipped to prerelease"
    )
    if compare_versions(new_tag, old_tag) < 0:
        sys.exit(downgrade)

    # The tag comparison is not enough on its own: tags and versions are not the
    # same axis. v1.0.0 and v1.0-0 are different tags that tokenize identically,
    # yet derive versions 1.0.0 and 1.0 — a downgrade the tag check waves past.
    if explicit_version:
        old_version = first_value(text, VERSION_VALUE_RE)
        if old_version and compare_versions(env["NEW_VERSION"], old_version) < 0:
            sys.exit(f"{downgrade} (version {old_version} -> {env['NEW_VERSION']})")

    sha_changed = old_sha256 != new_sha256
    if old_url == new_url and not sha_changed:
        sys.exit("nothing to update: url and sha256 both already current")

    # For a formula with an explicit `version`, that line is the version. For
    # the others Homebrew derives it from the URL, so the tag stands in for it.
    if explicit_version:
        version_changed = first_value(text, VERSION_VALUE_RE) != env["NEW_VERSION"]
    else:
        version_changed = old_tag != new_tag

    revision = resolve_revision(
        version_changed=version_changed,
        sha_changed=sha_changed,
        old_revision=old_revision,
        derived_revision=int(env.get("NEW_REVISION") or 0),
    )

    text = replace_one(URL_RE, lambda m: f'{m.group(1)}url "{new_url}"', text, "url")
    text = replace_one(
        SHA_RE, lambda m: f'{m.group(1)}sha256 "{new_sha256}"', text, "sha256"
    )
    if explicit_version:
        text = replace_one(
            VERSION_RE,
            lambda m: f'{m.group(1)}version "{env["NEW_VERSION"]}"',
            text,
            "version",
        )
    return set_revision(text, revision)


def set_revision(text, revision):
    existing = re.findall(REVISION_RE, text, flags=re.M)
    if len(existing) > 1:
        sys.exit(f"expected at most one revision line, found {len(existing)}")

    if existing:
        if revision:
            return re.sub(
                REVISION_RE,
                lambda m: re.sub(r"\d+", str(revision), m.group(0)),
                text,
                count=1,
                flags=re.M,
            )
        # revision 0 is the absence of a revision line, not `revision 0`.
        return re.sub(REVISION_RE, "", text, count=1, flags=re.M)

    if not revision:
        return text

    # Homebrew's ComponentsOrder is url, version, sha256, license, revision — so
    # anchor to `license` and fall back to `sha256` for a formula without one.
    for anchor in (r'^([ \t]*)(license\s+.*\n)', r'^([ \t]*)(sha256\s+"[^"]*"\n)'):
        text, count = re.subn(
            anchor,
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}revision {revision}\n",
            text,
            count=1,
            flags=re.M,
        )
        if count:
            return text
    sys.exit("could not find a license or sha256 line to place `revision` after")


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: render_formula.py <src> <dst>")
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    rendered = render(text, os.environ)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(rendered)


if __name__ == "__main__":
    main()
