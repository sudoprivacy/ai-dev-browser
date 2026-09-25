"""browser_connect surfaces a build identity so a re-tester knows WHICH code.

In a repo-direct / editable run the packaged version lags the working tree
(setuptools-scm resolves it at build time), which had a re-tester unsure whether
they were testing new code. `_build_info` always reports `version` and, from a
git checkout, the live `git_commit` (the unambiguous signal).
"""

from __future__ import annotations

from ai_dev_browser.core.browser import _build_info


def test_build_info_always_has_version():
    info = _build_info()
    assert isinstance(info, dict)
    assert isinstance(info.get("version"), str) and info["version"]


def test_build_info_has_git_commit_in_a_checkout():
    # The test suite runs from the git checkout, so the live commit is present
    # and is a short hex sha. (Installed-package envs without .git omit it.)
    info = _build_info()
    sha = info.get("git_commit")
    assert sha is not None, "expected a git_commit when run from the repo"
    assert 6 <= len(sha) <= 12 and all(c in "0123456789abcdef" for c in sha)
