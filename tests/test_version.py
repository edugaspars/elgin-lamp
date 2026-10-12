"""Versão calculada pelas tags: +1 no patch por commit, minor novo a cada release."""

import subprocess

import pytest

from lampdesk import version


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    if version._git("--version") is None:
        pytest.skip("git indisponível")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


def commit(repo, n=1):
    for _ in range(n):
        git(repo, "commit", "-q", "--allow-empty", "-m", "c")


def test_before_first_release(repo):
    commit(repo, 3)
    assert version.from_git(repo) == "1.0.0-dev"
    assert version.next_release(repo) == "1.0.0"


def test_commits_bump_patch_and_release_bumps_minor(repo):
    commit(repo)
    git(repo, "tag", "v1.0.0")
    assert version.from_git(repo) == "1.0.0"
    commit(repo, 2)
    assert version.from_git(repo) == "1.0.2"
    assert version.next_release(repo) == "1.1.0"
    git(repo, "tag", "v1.1.0")  # o merge publica a release e zera o patch
    assert version.from_git(repo) == "1.1.0"
    commit(repo)
    assert version.from_git(repo) == "1.1.1"
    assert version.next_release(repo) == "1.2.0"


def test_ignores_unrelated_tags(repo):
    commit(repo)
    git(repo, "tag", "v1.0.0")
    git(repo, "tag", "experimento")
    commit(repo)
    assert version.from_git(repo) == "1.0.1"
    assert version.parse("v1.2") is None
