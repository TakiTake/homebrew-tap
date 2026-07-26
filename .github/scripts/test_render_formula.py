#!/usr/bin/env python3
"""Tests for render_formula and the tag -> version/revision mapping.

Run: python3 .github/scripts/test_render_formula.py
"""

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
import render_formula  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = HERE / "update-formula.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "update-formula.yml"


@contextlib.contextmanager
def sourceable(*names):
    """Expose the named bash functions, taken verbatim from the real script.

    Sourcing the real definitions is the point — a copy in the test could pass
    while the script it claims to describe had drifted.

    Extraction is done here in Python and written to an ordinary file, rather
    than `source <(sed -n …)`. That idiom is unreliable under bash 3.2, which is
    /bin/bash on macOS and therefore what the update job runs, and it fails by
    defining nothing at all — so every test using it reported the function as
    "command not found" rather than pointing at the extraction. Doing the work
    in Python also removes the GNU/BSD sed difference from the test path.
    """
    text = SCRIPT.read_text()
    parts = []
    for name in names:
        match = re.search(
            rf"^{re.escape(name)}\(\)\s*\{{\n.*?^\}}", text, flags=re.M | re.S
        )
        if not match:
            raise AssertionError(f"{name}() not found in {SCRIPT}")
        parts.append(match.group(0))

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8"
    )
    try:
        handle.write("\n".join(parts) + "\n")
        handle.close()
        yield handle.name
    finally:
        os.unlink(handle.name)

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
  sha256 "{OLD_SHA}"
  license "GPL-2.0-only"
end
'''


def url_for(tag, repo="TakiTake/vpnp"):
    return f"https://github.com/{repo}/releases/download/{tag}/asset-{tag}.tar.gz"


def env(tag="v0.2.0", sha=NEW_SHA, revision=0, repo="TakiTake/vpnp"):
    return {
        "NEW_URL": url_for(tag, repo),
        "NEW_SHA256": sha,
        "NEW_REVISION": str(revision),
    }


def versioned(tag, revision=0, sha=NEW_SHA):
    """A release of openvpn-aws, whose tags carry a -<build> suffix."""
    return env(tag=tag, sha=sha, revision=revision, repo="TakiTake/openvpn-aws")


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

    def test_new_upstream_version_clears_the_revision(self):
        out = render_formula.render(VERSIONED, versioned("v2.7.6-0"))
        self.assertEqual(revision_of(out), 0)

    def test_build_number_becomes_a_revision_line(self):
        out = render_formula.render(VERSIONED, versioned("v2.7.5-1", 1))
        self.assertEqual(revision_of(out), 1)

    def test_revision_goes_after_license(self):
        """Homebrew's ComponentsOrder is url, version, sha256, license, revision."""
        out = render_formula.render(VERSIONED, versioned("v2.7.5-1", 1))
        lines = [line.strip() for line in out.splitlines()]
        self.assertEqual(
            lines.index("revision 1"), lines.index('license "GPL-2.0-only"') + 1
        )

    def test_revision_falls_back_to_sha256_without_a_license(self):
        no_license = VERSIONED.replace('  license "GPL-2.0-only"\n', "")
        out = render_formula.render(no_license, versioned("v2.7.5-1", 1))
        lines = [line.strip() for line in out.splitlines()]
        self.assertEqual(
            lines.index("revision 1"), lines.index(f'sha256 "{NEW_SHA}"') + 1
        )

    def test_revision_reset_on_a_new_upstream_version(self):
        withrev = render_formula.render(VERSIONED, versioned("v2.7.5-2", 2))
        self.assertEqual(revision_of(withrev), 2)
        bumped = render_formula.render(withrev, versioned("v2.7.6-0"))
        self.assertNotIn("revision", bumped)
        self.assertIn("v2.7.6-0", bumped)

    def test_only_one_revision_line_ever(self):
        once = render_formula.render(VERSIONED, versioned("v2.7.5-1", 1))
        twice = render_formula.render(
            once, versioned("v2.7.5-2", 2, sha="c" * 64)
        )
        self.assertEqual(len(re.findall(r"revision \d+", twice)), 1)
        self.assertEqual(revision_of(twice), 2)

    def test_a_new_tag_carrying_identical_bytes_leaves_the_revision_alone(self):
        """Same binary, so there is nothing for `brew upgrade` to deliver."""
        once = render_formula.render(VERSIONED, versioned("v2.7.5-1", 1))
        twice = render_formula.render(once, versioned("v2.7.5-2", 2))
        self.assertEqual(revision_of(twice), 1)

    def test_missing_url_line_is_fatal(self):
        with self.assertRaises(SystemExit):
            render_formula.render(SIMPLE.replace('  url "', '  #url "'), env())

    def test_a_version_stanza_is_refused(self):
        """Nothing rewrites a `version` line any more, so one that exists would
        be left stale while url and sha256 advance — ship new bytes under the
        old pkg_version. brew audit rejects it too; fail rather than ignore."""
        with_version = SIMPLE.replace("  sha256", '  version "0.1.0"\n  sha256')
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(with_version, env())
        self.assertIn("version", str(cm.exception))

    def test_prose_mentioning_version_is_not_a_stanza(self):
        """A caveats heredoc line starting with the word must not halt the run."""
        with_caveat = SIMPLE.replace(
            "end\n",
            '  def caveats\n    <<~EOS\n      version 2 of the config is required\n'
            "    EOS\n  end\nend\n",
        )
        out = render_formula.render(with_caveat, env())
        self.assertIn("version 2 of the config is required", out)

    def test_ambiguous_url_lines_are_fatal(self):
        doubled = SIMPLE.replace('  license "MIT"\n', '  url "https://x/y.tar.gz"\n')
        with self.assertRaises(SystemExit):
            render_formula.render(doubled, env())

    def test_real_formulae_render(self):
        for name in ("pall8t", "vpnp"):
            text = (ROOT / "Formula" / f"{name}.rb").read_text()
            out = render_formula.render(text, env(tag="v999.0.0"))
            self.assertIn(f'  url "{url_for("v999.0.0")}"', out, name)
        # A tag the formula can never legitimately reach, so this test does not
        # start failing the day the bot lands a real upgrade.
        text = (ROOT / "Formula" / "openvpn-aws.rb").read_text()
        out = render_formula.render(text, versioned("v999.0.0-0"))
        self.assertIn("v999.0.0-0", out)


class TestUpgradeOrdering(unittest.TestCase):
    """Homebrew orders installs by pkg_version. A render that fails to increase
    it produces an update users silently never receive."""

    def test_older_tag_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(VERSIONED, versioned("v2.7.4-0"))
        self.assertIn("downgrade", str(cm.exception))

    def test_lower_build_number_is_refused(self):
        withrev = render_formula.render(VERSIONED, versioned("v2.7.5-3", 3))
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(withrev, versioned("v2.7.5-1", 1))
        self.assertIn("downgrade", str(cm.exception))

    def test_reupload_under_the_same_tag_bumps_the_revision(self):
        """The tag cannot change, so only a revision can carry the new bytes."""
        out = render_formula.render(VERSIONED, versioned("v2.7.5-0", 0))
        self.assertEqual(revision_of(out), 1)
        self.assertIn(f'sha256 "{NEW_SHA}"', out)

    def test_reupload_bumps_revision_on_a_revisionless_formula(self):
        """pall8t/vpnp derive their version from the URL, so a same-tag
        re-upload has no other way to register as an upgrade."""
        out = render_formula.render(SIMPLE, env(tag="v0.1.0"))
        self.assertEqual(revision_of(out), 1)

    def test_repeated_reuploads_keep_climbing(self):
        first = render_formula.render(VERSIONED, versioned("v2.7.5-0", 0))
        second = render_formula.render(
            first, versioned("v2.7.5-0", 0, sha="c" * 64)
        )
        self.assertEqual(revision_of(second), 2)

    def test_new_tag_mapping_to_the_same_version_still_climbs(self):
        """v2.7.5-3 and v2.7.5-4 are different tags but the same version, so the
        build number alone cannot be trusted to raise pkg_version — a re-upload
        may already have pushed the revision past it."""
        at3 = render_formula.render(VERSIONED, versioned("v2.7.5-3", 3))
        self.assertEqual(revision_of(at3), 3)
        # A re-upload under v2.7.5-3 raises the revision to 4.
        reuploaded = render_formula.render(
            at3, versioned("v2.7.5-3", 3, sha="c" * 64)
        )
        self.assertEqual(revision_of(reuploaded), 4)
        # Upstream then ships v2.7.5-4, whose build number is only 4. Taking it
        # verbatim would leave pkg_version flat at 2.7.5_4.
        at4 = render_formula.render(
            reuploaded, versioned("v2.7.5-4", 4, sha="d" * 64)
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
        at_1_0_0 = VERSIONED.replace("v2.7.5-0", "v1.0.0")
        with self.assertRaises(SystemExit) as cm:
            render_formula.render(at_1_0_0, versioned("v1.0-0"))
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


class TestVersionOf(unittest.TestCase):
    """`version_of` decides whether a revision resets or climbs, so its exact
    shape matters: it must strip a build number and nothing else.

    Read the two tables carefully — they claim different things. GATED holds
    tags update-formula.sh admits, so those answers must equal what Homebrew
    derives from the url. Entries marked `brew:` were observed directly on a
    real brew; the rest are the parser's reading of shapes no upstream here has
    published yet. Do not promote one to `brew:` without running the command.
    UNGATED holds tags the gate refuses; those entries pin the regex only and
    are NOT assertions about Homebrew. Homebrew in fact disagrees with several
    of them (its winning parser captures up to the next hyphen rather than
    stripping a trailing build number), which is exactly why the gate refuses
    them — see TestTagValidation.test_rejects_tags_homebrew_reads_differently.
    """

    # brew: Version.detect on the real asset url returned exactly this.
    #   brew ruby -e 'p Version.detect("<url>").to_s'
    GATED = {
        "v2.7.5-0": "v2.7.5",  # brew: 2.7.5 (via `brew audit` redundancy report)
        "v2.7.5-1": "v2.7.5",  # brew: 2.7.5 — the rebuild case revision rests on
        "v2.7.5-10": "v2.7.5",
        "v2.7.5": "v2.7.5",
        "v0.2.0": "v0.2.0",
        "v1.2.3.4": "v1.2.3.4",
        "v1.0-0": "v1.0",
    }

    UNGATED = {
        "v2.8.0-rc1": "v2.8.0-rc1",
        "v2.8.0-rc1-2": "v2.8.0-rc1",
        "v2.7.5-0-beta": "v2.7.5-0-beta",  # brew reads 2.7.5
        "v2.7.5-": "v2.7.5-",  # brew reads 2.7.5
    }

    CASES = {**GATED, **UNGATED}

    def test_strips_only_a_trailing_build_number(self):
        for tag, want in self.CASES.items():
            with self.subTest(tag=tag):
                self.assertEqual(render_formula.version_of(tag), want)

    def test_agrees_with_the_shell_derivation(self):
        """The renderer and update-formula.sh must decompose a tag identically,
        or the revision resolved here does not match the build number passed in."""
        derive = TestTagDerivation().derive
        for tag in self.CASES:
            with self.subTest(tag=tag):
                self.assertEqual(render_formula.version_of(tag).lstrip("v"), derive(tag)[0])


class TestTagDerivation(unittest.TestCase):
    """The tag -> (version, revision) mapping, sourced from the real script so
    this cannot drift away from what actually runs."""

    def derive(self, tag):
        with sourceable("derive_version_and_revision") as functions:
            out = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; '
                    'derive_version_and_revision "$2"; '
                    "printf '%s %s\\n' \"$new_version\" \"$new_revision\"",
                    "_",
                    functions,
                    tag,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        # Assert rather than unpack: the sequence above ends in printf, so a
        # function that failed to load still exits 0 and yields a blank line.
        fields = out.stdout.split()
        self.assertEqual(
            len(fields), 2, f"derive produced {out.stdout!r}, stderr={out.stderr!r}"
        )
        version, revision = fields
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

    PATTERN = re.compile(r"^v[0-9]+(\.[0-9]+){1,3}(-[0-9]+)?$")

    def accepts(self, tag):
        return bool(self.PATTERN.match(tag))

    def test_accepts_real_tags(self):
        for tag in ("v0.1.0", "v0.2.0", "v2.7.5-0", "v10.0.0", "v2.7.5-12", "v1.0"):
            self.assertTrue(self.accepts(tag), tag)

    def test_rejects_tags_whose_homebrew_version_is_unverified(self):
        """The gate is narrow on purpose: render_formula.version_of has to
        predict Homebrew's url-derived version, and only these shapes have been
        checked against a real brew. A prerelease reaching `brew upgrade` users
        would be a bad outcome even if the prediction happened to hold."""
        for tag in ("v2.8.0-rc1", "v10.0.0-rc1", "v1.1.1w", "v2026-07-25"):
            self.assertFalse(self.accepts(tag), tag)

    def test_rejects_tags_homebrew_reads_differently(self):
        r"""Each of these is a tag where version_of and Homebrew disagree.

        Homebrew derives the version with StemParser(/-v?(\d[^-]+)/), which
        captures up to the NEXT HYPHEN rather than stripping a trailing build
        number — the two rules agree on v2.7.5-0 and part ways here. Letting one
        through resets the revision on a version Homebrew considers unchanged,
        which is a pkg_version that fails to climb (or drops, if a same-tag
        re-upload had already raised it). The gate is what makes version_of's
        model safe, so these must stay rejected.
        """
        for tag in (
            "v1.0.0-hotfix1",  # brew: 1.0.0
            "v1.0.0-dev",  # brew: 1.0.0
            "v1.0.0-snapshot",  # brew: 1.0.0
            "v1.0.0-p1",  # brew: 1.0.0
            "v1.0.0-post1",  # brew: 1.0.0
            "v2.7.5-0-beta",  # brew: 2.7.5
            "v2.7.5-",  # brew: 2.7.5
            "v2.7.5-0-1",  # brew: 0-1
            "v1-0",  # brew: no parser matches at all
            "v9-0",  # brew: no parser matches at all
            "v2.8.0-rc100",  # brew: 2.8.0-rc10 (suffix takes at most 2 digits)
            "v2.8.0-beta100",  # brew: 2.8.0-beta10
            "v1.0.0-preview",  # brew: 1.0.0-pre (truncated mid-word)
        ):
            self.assertFalse(self.accepts(tag), tag)

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
        self.assertIn(r"^v[0-9]+(\.[0-9]+){1,3}(-[0-9]+)?$", text)


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
        """The list is hardcoded in several places; drift between them is silent.

        A formula missing from a workflow loop is simply never checked, and one
        missing from the dispatch options cannot be run on demand.

        There is one loop per job since the detect/update split — the detect job
        decides what needs work and the update job acts on it, and a formula
        present in only one of them would either never be detected or be
        detected and then silently dropped. So every loop must carry the full
        table, not just one of them.
        """
        text = WORKFLOW.read_text()
        loops = [
            set(m.split())
            for m in re.findall(r"for formula in ([^;]+);", text)
            if not any(c in m for c in "/*")  # skip the `Formula/*.rb` glob loop
        ]
        self.assertGreaterEqual(len(loops), 1, "expected a formula-name loop")
        for loop in loops:
            self.assertEqual(loop, self.script_table())
        block = re.search(r"^\s+options:\n((?:\s+- \S+\n)+)", text, flags=re.M).group(1)
        options = set(re.findall(r"- (\S+)", block))
        self.assertEqual(options - {"all"}, self.script_table())
        self.assertIn("all", options)

    def test_detect_job_matches_the_scripts_nothing_to_do_status(self):
        """The split communicates through an exit status, so both halves have to
        agree on the number. If the script's constant moved and the workflow's
        `100)` case did not, every up-to-date formula would be reported as a
        failed one — an hourly red build for a no-op run."""
        declared = re.search(
            r"^readonly EXIT_NOTHING_TO_DO=(\d+)", SCRIPT.read_text(), flags=re.M
        )
        self.assertIsNotNone(declared, "script no longer declares EXIT_NOTHING_TO_DO")
        self.assertRegex(
            WORKFLOW.read_text(),
            rf"(?m)^\s*{declared.group(1)}\)",
            "the detect job does not handle the script's nothing-to-do status",
        )

    def test_only_the_brew_capable_job_asks_for_brew_validation(self):
        """BREW_AUDIT on the ubuntu detector would abort every run: the script
        treats a missing brew as a broken workflow, not as something to skip."""
        text = WORKFLOW.read_text()
        detect, update = text.split("  update:", 1)
        self.assertIn("CHECK_ONLY=1", detect)
        self.assertNotIn("BREW_AUDIT", detect)
        self.assertIn("BREW_AUDIT: 1", update)
        self.assertIn("macos", update)

    def test_a_single_broken_formula_does_not_block_the_others(self):
        """A bare `if:` implies success(), so one formula failing detection would
        skip the update job entirely — including for formulae detect *did* find
        updates for. A stranded branch is a hard error until a human clears it,
        so without this the whole tap stops updating over one bad formula."""
        gate = re.search(
            r"^    if: (.+)$", WORKFLOW.read_text(), flags=re.M
        )
        self.assertIsNotNone(gate, "the update job has no `if:` gate")
        self.assertIn(
            "!cancelled()",
            gate.group(1),
            "the update job's `if:` implies success() and will skip on a partial failure",
        )

    def test_brew_audit_is_refused_where_it_cannot_apply(self):
        """BREW_AUDIT gates the formula in the working tree, which the read-only
        modes never write. Accepting it there would audit the *previous* contents
        and pass — a gate that was asked for, silently did nothing, and reported
        success."""
        for mode in ("DRY_RUN", "CHECK_ONLY"):
            with self.subTest(mode=mode):
                proc = subprocess.run(
                    [str(SCRIPT), "vpnp"],
                    capture_output=True,
                    text=True,
                    env={**os.environ, mode: "1", "BREW_AUDIT": "1"},
                    cwd=str(ROOT),
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("BREW_AUDIT cannot apply", proc.stderr)

    def test_mktemp_calls_pass_a_template(self):
        """BSD mktemp requires one, and the update job now runs on macOS. Without
        it the script dies on its first temp file, before doing anything."""
        calls = re.findall(r"\$\(mktemp[^)]*\)", SCRIPT.read_text())
        self.assertTrue(calls, "no mktemp calls found — has the script changed?")
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("XXXXXX", call, "mktemp call has no template")

    def test_no_empty_array_expansion_in_shell_run_blocks(self):
        """`arr=()` plus `${#arr[@]}` under `set -u` aborts on bash 3.2, which is
        /bin/bash on macOS — and the update job runs there. The failing path is
        the one where nothing failed, so it breaks on success while passing every
        test written on Linux.

        Read this as pinning known shapes, not as proof of 3.2 compatibility.
        Nothing in this repo executes under bash 3.2 — `validate.sh` runs
        `bash -n` with whatever bash the runner has, and `-n` would not catch
        this class anyway, since it is a runtime expansion error. A conditional
        `arr+=(x)` with no empty initialiser is equally fatal and is not
        detectable this way at all.
        """
        targets = sorted(HERE.glob("*.sh")) + sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertTrue(targets)
        for path in targets:
            text = path.read_text()
            # No `$` anchor and `declare` included: `arr=()  # reset` and
            # `declare -a arr=()` are the same hazard and were both missed.
            empty = set(re.findall(r"^\s*(?:local|declare|typeset)?\s*-?a?\s*(\w+)=\(\s*\)", text, flags=re.M))
            for name in empty:
                with self.subTest(file=path.name, array=name):
                    self.assertNotRegex(
                        text,
                        rf"\$\{{[#!]?{name}\[[@*]\]",
                        f"{name} is initialised empty and then expanded",
                    )

    def test_no_assignment_masks_a_command_failure(self):
        """`export X="$(cmd)"` and `readonly X="$(cmd)"` return the *declaration's*
        status, not the command's, so `set -e` never sees the failure (SC2155).
        The concrete bite: `readonly REPO_ROOT="$(cd … && pwd)"` with a failing cd
        leaves REPO_ROOT empty, and `cd ""` then succeeds — the script carries on
        against the wrong directory instead of stopping. Caught in CI by the
        actionlint pass that `brew style` runs over the staged tap, but only for
        workflows; this covers the scripts too."""
        targets = sorted(HERE.glob("*.sh")) + sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        pattern = re.compile(r"^\s*(?:export|readonly|local|declare|typeset)\s+\w+=\"?\$\(", re.M)
        for path in targets:
            with self.subTest(file=path.name):
                self.assertEqual(
                    pattern.findall(path.read_text()),
                    [],
                    "assignment masks the command's exit status; split the declaration",
                )

    def test_brew_check_guards_dollar_at_before_expanding_it(self):
        """`"$@"` with no positional parameters is also fatal under `set -u` on
        bash 3.2. brew-check.sh is safe only because the no-argument case exits
        first — an incidental guarantee that nothing else pins, so deleting that
        early return would leave every test green and break the macOS job."""
        text = (HERE / "brew-check.sh").read_text()
        guard = text.find('"$#" -eq 0')
        use = text.find('in "$@"')
        self.assertNotEqual(guard, -1, "brew-check.sh no longer guards on $#")
        self.assertNotEqual(use, -1, "brew-check.sh no longer iterates \"$@\"")
        self.assertLess(guard, use, '"$@" is expanded before $# is checked')
        self.assertIn("exit 0", text[guard:use], "the no-argument branch no longer returns")

    def test_dry_run_is_not_truthy_for_zero(self):
        with sourceable("is_true") as functions:
            for value, expected in (("1", 0), ("", 1), ("0", 1), ("false", 1), ("yes", 0)):
                out = subprocess.run(
                    ["bash", "-c", 'source "$1"; ' f'is_true "{value}"', "_", functions],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    out.returncode,
                    expected,
                    f"DRY_RUN={value!r}, stderr={out.stderr!r}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
