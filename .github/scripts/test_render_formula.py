#!/usr/bin/env python3
"""Tests for render_formula and the tag -> version/revision mapping.

Run: python3 .github/scripts/test_render_formula.py
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
import render_formula  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = HERE / "update-formula.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "update-formula.yml"

OLD_SHA = "a" * 64
NEW_SHA = "b" * 64

SIMPLE = f'''class Vpnp < Formula
  desc "d"
  homepage "https://github.com/TakiTake/vpnp"
  url "https://github.com/TakiTake/vpnp/releases/download/v0.1.0/vpnp-v0.1.0-aarch64-apple-darwin.tar.gz"
  sha256 "{OLD_SHA}"
  license "MIT"
end
'''

VERSIONED = f'''class OpenvpnAws < Formula
  desc "d"
  homepage "https://github.com/TakiTake/openvpn-aws"
  url "https://github.com/TakiTake/openvpn-aws/releases/download/v2.7.5-0/openvpn-aws-v2.7.5-0-aarch64-apple-darwin.tar.gz"
  version "2.7.5"
  sha256 "{OLD_SHA}"
  license "GPL-2.0-only"
end
'''


def url_for(tag, repo="TakiTake/vpnp"):
    return f"https://github.com/{repo}/releases/download/{tag}/asset-{tag}.tar.gz"


def env(tag="v0.2.0", sha=NEW_SHA, version=None, revision=0, repo="TakiTake/vpnp"):
    """Build a renderer environment. `version` set => explicit-version formula."""
    out = {
        "NEW_URL": url_for(tag, repo),
        "NEW_SHA256": sha,
        "EXPLICIT_VERSION": "1" if version else "0",
    }
    if version:
        out["NEW_VERSION"] = version
        out["NEW_REVISION"] = str(revision)
    return out


def versioned(tag, version, revision=0, sha=NEW_SHA):
    return env(
        tag=tag, sha=sha, version=version, revision=revision, repo="TakiTake/openvpn-aws"
    )


def revision_of(text):
    found = re.findall(r"^\s*revision\s+(\d+)$", text, flags=re.M)
    return int(found[0]) if found else 0


class TestRender(unittest.TestCase):
    def test_updates_url_and_sha(self):
        out = render_formula.render(SIMPLE, env())
        self.assertIn(f'  url "{url_for("v0.2.0")}"', out)
        self.assertIn(f'  sha256 "{NEW_SHA}"', out)
        self.assertNotIn(OLD_SHA, out)
        self.assertIn('license "MIT"', out)

    def test_preserves_indentation(self):
        out = render_formula.render(SIMPLE, env())
        for line in out.splitlines():
            if line.strip().startswith(("url ", "sha256 ")):
                self.assertTrue(line.startswith("  ") and line[2] != " ", line)

    def test_version_line_untouched_when_not_explicit(self):
        out = render_formula.render(VERSIONED, env(tag="v2.7.6-0"))
        self.assertIn('version "2.7.5"', out)

    def test_explicit_version_updated(self):
        out = render_formula.render(VERSIONED, versioned("v2.7.6-0", "2.7.6"))
        self.assertIn('version "2.7.6"', out)
        self.assertEqual(revision_of(out), 0)

    def test_build_number_becomes_a_revision_line(self):
        out = render_formula.render(VERSIONED, versioned("v2.7.5-1", "2.7.5", 1))
        self.assertEqual(revision_of(out), 1)

    def test_revision_goes_after_license(self):
        """Homebrew's ComponentsOrder is url, version, sha256, license, revision."""
        out = render_formula.render(VERSIONED, versioned("v2.7.5-1", "2.7.5", 1))
        lines = [line.strip() for line in out.splitlines()]
        self.assertEqual(
            lines.index("revision 1"), lines.index('license "GPL-2.0-only"') + 1
        )

    def test_revision_falls_back_to_sha256_without_a_license(self):
        no_license = VERSIONED.replace('  license "GPL-2.0-only"\n', "")
        out = render_formula.render(no_license, versioned("v2.7.5-1", "2.7.5", 1))
        lines = [line.strip() for line in out.splitlines()]
        self.assertEqual(
            lines.index("revision 1"), lines.index(f'sha256 "{NEW_SHA}"') + 1
        )

    def test_revision_reset_on_a_new_upstream_version(self):
        withrev = render_formula.render(VERSIONED, versioned("v2.7.5-2", "2.7.5", 2))
        self.assertEqual(revision_of(withrev), 2)
        bumped = render_formula.render(withrev, versioned("v2.7.6-0", "2.7.6"))
        self.assertNotIn("revision", bumped)
        self.assertIn('version "2.7.6"', bumped)

    def test_only_one_revision_line_ever(self):
        once = render_formula.render(VERSIONED, versioned("v2.7.5-1", "2.7.5", 1))
        twice = render_formula.render(
            once, versioned("v2.7.5-2", "2.7.5", 2, sha="c" * 64)
        )
        self.assertEqual(len(re.findall(r"revision \d+", twice)), 1)
        self.assertEqual(revision_of(twice), 2)

    def test_a_new_tag_carrying_identical_bytes_leaves_the_revision_alone(self):
        """Same binary, so there is nothing for `brew upgrade` to deliver."""
        once = render_formula.render(VERSIONED, versioned("v2.7.5-1", "2.7.5", 1))
        twice = render_formula.render(once, versioned("v2.7.5-2", "2.7.5", 2))
        self.assertEqual(revision_of(twice), 1)

    def test_missing_url_line_is_fatal(self):
        with self.assertRaises(SystemExit):
            render_formula.render(SIMPLE.replace('  url "', '  #url "'), env())

    def test_missing_version_line_is_fatal_when_expected(self):
        with self.assertRaises(SystemExit):
            render_formula.render(SIMPLE, versioned("v1.0.0", "1.0"))

    def test_ambiguous_url_lines_are_fatal(self):
        doubled = SIMPLE.replace('  license "MIT"\n', '  url "https://x/y.tar.gz"\n')
        with self.assertRaises(SystemExit):
            render_formula.render(doubled, env())

    def test_real_formulae_render(self):
        for name in ("pall8t", "vpnp"):
            text = (ROOT / "Formula" / f"{name}.rb").read_text()
            out = render_formula.render(text, env(tag="v999.0.0"))
            self.assertIn(f'  url "{url_for("v999.0.0")}"', out, name)
        # A version the formula can never legitimately reach, so this test does
        # not start failing the day the bot lands a real upgrade.
        text = (ROOT / "Formula" / "openvpn-aws.rb").read_text()
        out = render_formula.render(text, versioned("v999.0.0-0", "999.0.0"))
        self.assertIn('version "999.0.0"', out)


class TestUpgradeOrdering(unittest.TestCase):
    """Homebrew orders installs by pkg_version. A render that fails to increase
    it produces an update users silently never receive."""

    def test_older_tag_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(VERSIONED, versioned("v2.7.4-0", "2.7.4"))
        self.assertIn("downgrade", str(cm.exception))

    def test_lower_build_number_is_refused(self):
        withrev = render_formula.render(VERSIONED, versioned("v2.7.5-3", "2.7.5", 3))
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(withrev, versioned("v2.7.5-1", "2.7.5", 1))
        self.assertIn("downgrade", str(cm.exception))

    def test_reupload_under_the_same_tag_bumps_the_revision(self):
        """The tag cannot change, so only a revision can carry the new bytes."""
        out = render_formula.render(VERSIONED, versioned("v2.7.5-0", "2.7.5", 0))
        self.assertEqual(revision_of(out), 1)
        self.assertIn(f'sha256 "{NEW_SHA}"', out)

    def test_reupload_bumps_revision_without_an_explicit_version_too(self):
        """pall8t/vpnp derive their version from the URL, so a same-tag
        re-upload has no other way to register as an upgrade."""
        out = render_formula.render(SIMPLE, env(tag="v0.1.0"))
        self.assertEqual(revision_of(out), 1)

    def test_repeated_reuploads_keep_climbing(self):
        first = render_formula.render(VERSIONED, versioned("v2.7.5-0", "2.7.5", 0))
        second = render_formula.render(
            first, versioned("v2.7.5-0", "2.7.5", 0, sha="c" * 64)
        )
        self.assertEqual(revision_of(second), 2)

    def test_new_tag_mapping_to_the_same_version_still_climbs(self):
        """v2.7.5-3 and v2.7.5-4 are different tags but the same version, so the
        build number alone cannot be trusted to raise pkg_version — a re-upload
        may already have pushed the revision past it."""
        at3 = render_formula.render(VERSIONED, versioned("v2.7.5-3", "2.7.5", 3))
        self.assertEqual(revision_of(at3), 3)
        # A re-upload under v2.7.5-3 raises the revision to 4.
        reuploaded = render_formula.render(
            at3, versioned("v2.7.5-3", "2.7.5", 3, sha="c" * 64)
        )
        self.assertEqual(revision_of(reuploaded), 4)
        # Upstream then ships v2.7.5-4, whose build number is only 4. Taking it
        # verbatim would leave pkg_version flat at 2.7.5_4.
        at4 = render_formula.render(
            reuploaded, versioned("v2.7.5-4", "2.7.5", 4, sha="d" * 64)
        )
        self.assertGreater(revision_of(at4), revision_of(reuploaded))

    def test_url_only_change_is_allowed(self):
        """An asset renamed upstream with identical bytes: the url must still be
        corrected, and it must not be treated as a hard error."""
        renamed = SIMPLE.replace(
            "vpnp-v0.1.0-aarch64-apple-darwin.tar.gz",
            "vpnp-v0.1.0-arm64-macos.tar.gz",
        )
        out = render_formula.render(renamed, env(tag="v0.1.0", sha=OLD_SHA))
        self.assertIn(f'  url "{url_for("v0.1.0")}"', out)
        self.assertEqual(revision_of(out), 0)

    def test_no_change_at_all_is_refused(self):
        rendered = render_formula.render(SIMPLE, env())
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(rendered, env())
        self.assertIn("nothing to update", str(cm.exception))


    def test_version_downgrade_is_refused_even_when_tags_tokenize_equal(self):
        """v1.0.0 and v1.0-0 tokenize identically but derive different versions,
        so the tag comparison alone waves the downgrade through."""
        at_1_0_0 = VERSIONED.replace("v2.7.5-0", "v1.0.0").replace(
            'version "2.7.5"', 'version "1.0.0"'
        )
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(at_1_0_0, versioned("v1.0-0", "1.0"))
        self.assertIn("downgrade", str(cm.exception))

    def test_unrecognisable_url_is_fatal_rather_than_unguarded(self):
        """A url with no release tag used to disable the downgrade check."""
        sourced = SIMPLE.replace(
            "https://github.com/TakiTake/vpnp/releases/download/v0.1.0/vpnp-v0.1.0-aarch64-apple-darwin.tar.gz",
            "https://example.com/archive/vpnp-0.1.0.tar.gz",
        )
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(sourced, env())
        self.assertIn("release tag", str(cm.exception))


class TestCompareVersions(unittest.TestCase):
    def test_patch_letters_are_bumps_not_prereleases(self):
        """OpenSSL-style: 1.1.1w is newer than 1.1.1, unlike 2.8.0rc1."""
        self.assertEqual(render_formula.compare_versions("v1.1.1w", "v1.1.1"), 1)
        self.assertEqual(render_formula.compare_versions("v2.7.5a", "v2.7.5"), 1)
        self.assertEqual(render_formula.compare_versions("v2.8.0rc1", "v2.8.0"), -1)
        self.assertEqual(render_formula.compare_versions("v2.8.0beta", "v2.8.0"), -1)

    def test_ordering(self):
        cases = [
            ("v2.7.5", "v2.7.4", 1),
            ("v2.7.4", "v2.7.5", -1),
            ("v2.7.5", "v2.7.5", 0),
            ("v2.7.5-1", "v2.7.5-0", 1),
            ("v2.10.0", "v2.9.0", 1),  # numeric, not lexicographic
            ("v2.8.0", "v2.8.0-rc1", 1),  # a release beats its prerelease
            ("v2.8.0-rc2", "v2.8.0-rc1", 1),
            ("v0.2.0", "v0.1.0", 1),
            ("v10.0.0", "v9.0.0", 1),
        ]
        for left, right, want in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(render_formula.compare_versions(left, right), want)


class TestTagDerivation(unittest.TestCase):
    """The tag -> (version, revision) mapping, sourced from the real script so
    this cannot drift away from what actually runs."""

    def derive(self, tag):
        out = subprocess.run(
            [
                "bash",
                "-c",
                'source <(sed -n "/^derive_version_and_revision()/,/^}/p" "$1"); '
                'derive_version_and_revision "$2"; '
                "printf '%s %s\\n' \"$new_version\" \"$new_revision\"",
                "_",
                str(SCRIPT),
                tag,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        version, revision = out.stdout.split()
        return version, int(revision)

    def test_build_number_becomes_revision(self):
        self.assertEqual(self.derive("v2.7.5-0"), ("2.7.5", 0))
        self.assertEqual(self.derive("v2.7.5-1"), ("2.7.5", 1))
        self.assertEqual(self.derive("v2.7.5-12"), ("2.7.5", 12))

    def test_plain_tag_has_no_revision(self):
        self.assertEqual(self.derive("v2.8.0"), ("2.8.0", 0))

    def test_prerelease_suffix_is_kept_in_version(self):
        self.assertEqual(self.derive("v2.8.0-rc1"), ("2.8.0-rc1", 0))
        self.assertEqual(self.derive("v2.8.0-rc1-2"), ("2.8.0-rc1", 2))


class TestTagValidation(unittest.TestCase):
    """The regex gate that runs before a tag reaches a URL, filename or git ref."""

    PATTERN = re.compile(r"^v[0-9][A-Za-z0-9.-]*$")

    def accepts(self, tag):
        return bool(self.PATTERN.match(tag))

    def test_accepts_real_tags(self):
        for tag in ("v0.1.0", "v0.2.0", "v2.7.5-0", "v10.0.0-rc1"):
            self.assertTrue(self.accepts(tag), tag)

    def test_rejects_dangerous_tags(self):
        for tag in (
            "v1.0.0/../../etc",
            "v1.0.0 rm -rf /",
            "v1.0.0;whoami",
            "v1.0.0$(id)",
            "../v1.0.0",
            "release-1.0",
            "v",
            "",
            "v1.0.0\nv2.0.0",
        ):
            self.assertFalse(self.accepts(tag), tag)

    def test_pattern_matches_the_script(self):
        """The gate under test must be the gate the script actually applies."""
        text = SCRIPT.read_text()
        self.assertIn(r"^v[0-9][A-Za-z0-9.-]*$", text)


class TestScriptGuards(unittest.TestCase):
    def script_table(self):
        body = SCRIPT.read_text().split("formula_config() {", 1)[1].split("\n}", 1)[0]
        return set(re.findall(r"^    ([a-z0-9-]+)\)$", body, flags=re.M))

    def test_unknown_formula_is_rejected(self):
        out = subprocess.run(
            ["bash", str(SCRIPT), "definitely-not-a-formula"],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "DRY_RUN": "1"},
        )
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("unknown formula", out.stderr)

    def test_every_table_entry_has_a_formula_file(self):
        """A typo'd or stale table entry fails at 3am; catch it here instead.

        Deliberately a subset check, not equality: adding a formula to the tap
        without wiring up automation for it is allowed, and must not turn CI red
        on an unrelated PR.
        """
        on_disk = {p.stem for p in (ROOT / "Formula").glob("*.rb")}
        self.assertTrue(self.script_table())
        self.assertLessEqual(self.script_table(), on_disk)

    def test_workflow_and_script_agree_on_the_formula_list(self):
        """The list is hardcoded in three places; drift between them is silent.

        A formula missing from the workflow loop is simply never checked, and
        one missing from the dispatch options cannot be run on demand.
        """
        text = WORKFLOW.read_text()
        loops = [
            set(m.split())
            for m in re.findall(r"for formula in ([^;]+);", text)
            if not any(c in m for c in "/*")  # skip the `Formula/*.rb` glob loop
        ]
        self.assertEqual(len(loops), 1, "expected exactly one formula-name loop")
        block = re.search(r"^\s+options:\n((?:\s+- \S+\n)+)", text, flags=re.M).group(1)
        options = set(re.findall(r"- (\S+)", block))
        self.assertEqual(loops[0], self.script_table())
        self.assertEqual(options - {"all"}, self.script_table())
        self.assertIn("all", options)

    def test_dry_run_is_not_truthy_for_zero(self):
        for value, expected in (("1", 0), ("", 1), ("0", 1), ("false", 1), ("yes", 0)):
            out = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source <(sed -n "/^is_true()/,/^}/p" "$1"); ' f'is_true "{value}"',
                    "_",
                    str(SCRIPT),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(out.returncode, expected, f"DRY_RUN={value!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
