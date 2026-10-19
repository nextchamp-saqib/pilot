"""Commands that run Frappe code get the bench's Redis while the bench is stopped."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from pilot.commands import Command
from pilot.commands.apps.install import InstallAppCommand
from pilot.commands.apps.uninstall import UninstallAppCommand
from pilot.commands.runtime.frappe import FrappeCommand
from pilot.commands.runtime.start import RunCommand
from pilot.commands.sites.create import NewSiteCommand
from pilot.commands.sites.drop import DropSiteCommand
from pilot.core.bench import Bench
from pilot.managers.redis import RedisManager
from tests.pilot.commands.test_commands import make_bench


@dataclass(kw_only=True)
class _Probe(Command):
    name: ClassVar[str] = "probe"

    def run(self) -> None:
        self.ran_with_redis = self.bench.redis_up  # type: ignore[union-attr]


def _serving(bench: Bench) -> contextlib.AbstractContextManager[None]:
    @contextlib.contextmanager
    def serve():
        bench.redis_up = True  # type: ignore[attr-defined]
        yield
        bench.redis_up = False  # type: ignore[attr-defined]

    return serve()


@pytest.mark.parametrize("needs_redis", [True, False])
def test_execute_serves_redis_only_for_a_command_that_needs_it(tmp_path: Path, needs_redis: bool) -> None:
    bench = make_bench(tmp_path)
    bench.redis_up = False  # type: ignore[attr-defined]
    command = _Probe(bench=bench)
    command.needs_redis = needs_redis  # type: ignore[misc]

    with patch.object(Bench, "running_redis", _serving):
        command.execute()

    assert command.ran_with_redis is needs_redis
    assert bench.redis_up is False  # type: ignore[attr-defined]


def test_site_commands_need_redis_and_start_does_not() -> None:
    for command in (NewSiteCommand, InstallAppCommand, UninstallAppCommand, DropSiteCommand, FrappeCommand):
        assert command.needs_redis, command.name
    assert not RunCommand.needs_redis


def test_a_production_bench_never_starts_its_own_redis(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    bench.config.production.enabled = True

    with patch.object(RedisManager, "running") as running, bench.running_redis():
        pass

    running.assert_not_called()


def test_a_dev_bench_serves_redis_for_the_duration(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)

    with patch.object(RedisManager, "running") as running, bench.running_redis():
        pass

    running.assert_called_once()
