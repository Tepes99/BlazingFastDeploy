import datetime as dt
from pathlib import Path

import pytest
from conftest import FakeRunner, write_app

from ship.config import Config
from ship.deploy import deploy, is_git_tracked, release_id, replace_production
from ship.runner import Result


def test_release_id_contains_timestamp_and_sha(tmp_path: Path) -> None:
    runner = FakeRunner([Result(("git",), 0, "abcdef123456\n")])
    value = release_id(tmp_path, runner, dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC))
    assert value == "20260102T030405Z-abcdef123456"


def test_tracked_environment_detection(tmp_path: Path) -> None:
    env = tmp_path / ".env.production"
    env.write_text("SECRET=x")
    assert is_git_tracked(env, tmp_path, FakeRunner([Result(("git",), 0)]))
    assert not is_git_tracked(env, tmp_path, FakeRunner([Result(("git",), 1)]))


def test_deploy_dry_run_does_not_use_ssh(tmp_path: Path) -> None:
    write_app(tmp_path, environment=True)
    runner = FakeRunner([Result(("git",), 1)])
    result = deploy(tmp_path, Config(), runner, dry_run=True)
    assert result["dry_run"] is True
    assert any("candidate" in item for item in result["containers"])
    assert all(call[0] == "git" for call in runner.calls)
    assert "TOKEN=secret" not in str(result)


class Backend:
    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.events: list[str] = []

    def _event(self, name: str) -> None:
        self.events.append(name)
        if self.fail == name:
            raise RuntimeError(name)

    def start_candidate(self) -> None:
        self._event("start_candidate")

    def check_candidate(self) -> None:
        self._event("check_candidate")

    def stop_candidate(self) -> None:
        self._event("stop_candidate")

    def stop_previous(self) -> None:
        self._event("stop_previous")

    def start_production(self) -> None:
        self._event("start_production")

    def check_production(self) -> None:
        self._event("check_production")

    def restore_previous(self) -> None:
        self._event("restore_previous")


def test_candidate_failure_keeps_production() -> None:
    backend = Backend("check_candidate")
    with pytest.raises(RuntimeError):
        replace_production(backend)
    assert backend.events == ["start_candidate", "check_candidate", "stop_candidate"]


def test_production_failure_recovers_previous() -> None:
    backend = Backend("check_production")
    with pytest.raises(RuntimeError):
        replace_production(backend)
    assert backend.events[-1] == "restore_previous"
    assert backend.events.index("stop_previous") > backend.events.index("stop_candidate")


def test_persistent_data_is_not_in_release_plan(tmp_path: Path) -> None:
    write_app(tmp_path)
    result = deploy(tmp_path, Config(), FakeRunner([Result(("git",), 1)]), dry_run=True)
    assert result["remote_directories"][1] == "/srv/ship/apps/medicine/data"
    assert not result["remote_directories"][1].startswith("/srv/ship/releases/")
