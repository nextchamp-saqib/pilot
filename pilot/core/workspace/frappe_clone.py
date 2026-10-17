from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pilot.config.bench import FRAMEWORK_REPO
from pilot.exceptions import BenchError, CommandError
from pilot.internal.git import git_env
from pilot.utils import run_command

_GITHUB_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")


class FrappeClone:
    """The one Frappe repository that dev benches check Frappe out of, each bench as a
    detached git worktree. A bare repository: its only branches are the ones a developer
    makes in it, so `develop` always means origin's."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def exists(self) -> bool:
        return (self.path / "HEAD").exists()

    def create(self) -> None:
        run_command(["git", "init", "--quiet", "--bare", str(self.path)])
        self.git("remote", "add", "origin", FRAMEWORK_REPO)

    def add_worktree(self, path: Path, branch: str, on_progress: Callable[[str], None]) -> None:
        if not self.exists:
            on_progress(f"Creating the shared Frappe clone at {self.path}...")
            self.create()
        commit = self.get_commit(branch, on_progress)
        self.git("worktree", "add", "--detach", str(path), commit, stream_output=True)

    def get_commit(self, branch: str, on_progress: Callable[[str], None]) -> str:
        """The tip of `branch`: a branch of this clone, `owner:branch` on that owner's fork
        of Frappe on GitHub, or else a branch of origin, fetched first."""
        owner, _, name = branch.rpartition(":")
        if owner:
            return self.fetch(self.add_fork(owner), name, on_progress)
        local = self.get_ref_commit(f"refs/heads/{branch}")
        return local or self.fetch("origin", branch, on_progress)

    def add_fork(self, owner: str) -> str:
        if not _GITHUB_OWNER.fullmatch(owner):
            raise BenchError(f"'{owner}' is not a GitHub user or organization.")
        if owner not in self.git("remote").split():
            self.git("remote", "add", owner, f"https://github.com/{owner}/frappe")
        return owner

    def fetch(self, remote: str, branch: str, on_progress: Callable[[str], None]) -> str:
        ref = f"refs/remotes/{remote}/{branch}"
        on_progress(f"Fetching Frappe {branch} from {remote}...")
        try:
            self.git("fetch", remote, f"+refs/heads/{branch}:{ref}", stream_output=True)
        except CommandError as error:
            raise BenchError(f"Could not fetch Frappe branch '{branch}' from {remote}.") from error
        return self.get_ref_commit(ref)

    def get_ref_commit(self, ref: str) -> str:
        try:
            return self.git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        except CommandError:
            return ""

    def prune_worktrees(self) -> None:
        """Forget worktrees whose folders are gone, such as a dropped bench's apps/frappe."""
        if self.exists:
            self.git("worktree", "prune")

    def git(self, *args: str, stream_output: bool = False) -> str:
        result = run_command(["git", "-C", str(self.path), *args], env=git_env(), stream_output=stream_output)
        return (result.stdout or b"").decode().strip()
