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

No formula here declares a `version`: Homebrew derives it from the URL, and
`brew audit` rejects a stanza that merely restates what it already found. It
strips a `-<build>` suffix while doing so, mapping v2.7.5-0 and v2.7.5-1 both to
2.7.5 — which is why `revision` has to carry rebuilds.

Usage: render_formula.py <src> <dst>
Env:   NEW_URL, NEW_SHA256, NEW_REVISION
"""

import os
import re
import sys

URL_RE = r'^([ \t]*)url\s+"[^"]*"$'
SHA_RE = r'^([ \t]*)sha256\s+"[^"]*"$'
REVISION_RE = r"^[ \t]*revision\s+\d+\n"

# Read-only counterparts, capturing the value rather than the indent.
URL_VALUE_RE = r'^[ \t]*url\s+"([^"]*)"$'
SHA_VALUE_RE = r'^[ \t]*sha256\s+"([^"]*)"$'
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


def version_of(tag):
    """The version Homebrew derives from a tag: the tag minus its build number.

    v2.7.5-0 and v2.7.5-1 are two builds of the same version, so this is the
    axis `revision` has to move on. A prerelease tail like -rc1 is part of the
    version rather than a build number, so only a trailing all-digit run is cut.
    """
    return re.sub(r"-\d+$", "", tag)


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

    # Nothing here rewrites a `version` line any more, so one that exists would
    # be left behind while url and sha256 advance — the formula would ship new
    # bytes under the old pkg_version, which is the one failure this file is
    # built to prevent. Refuse rather than silently ignore it.
    if re.search(r"^[ \t]*version\s", text, flags=re.M):
        sys.exit(
            "this formula declares a `version`, which brew audit rejects as "
            "redundant with the version scanned from the url. Remove it, or — if "
            "a url ever stops parsing and the stanza is genuinely needed — teach "
            "this script to rewrite it again before re-adding it"
        )

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
    # Both axes, because neither catches the other's case. Raw tags catch a
    # build-number drop (v2.7.5-3 -> v2.7.5-1), which the derived versions see
    # as equal. Derived versions catch a tag whose *shape* changes (v1.0.0 ->
    # v1.0-0), which tokenizes identically as a raw tag but means 1.0.0 -> 1.0.
    if compare_versions(new_tag, old_tag) < 0:
        sys.exit(downgrade)
    if compare_versions(version_of(new_tag), version_of(old_tag)) < 0:
        sys.exit(f"{downgrade} (version {version_of(old_tag)} -> {version_of(new_tag)})")

    sha_changed = old_sha256 != new_sha256
    if old_url == new_url and not sha_changed:
        sys.exit("nothing to update: url and sha256 both already current")

    # Keyed on the derived version, not the raw tag: v2.7.5-3 -> v2.7.5-4 is a
    # new tag but the same version, so the revision still has to climb.
    version_changed = version_of(old_tag) != version_of(new_tag)

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