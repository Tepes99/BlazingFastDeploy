import json
from pathlib import Path

import pytest

from ship.cli import _confirm, _removal_plan, execute
from ship.config import Config


def test_init_json_output_contains_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert execute(["init", "--name", "demo", "--example", "fastapi", "--dry-run", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert "TOKEN=" not in json.dumps(output)


def test_remove_dry_run_preserves_data_by_default() -> None:
    result = _removal_plan(Config(), "medicine", False)
    assert result["deleted_paths"] == []
    assert "/srv/ship/apps/medicine/secrets" in result["preserved"]
    assert "/srv/ship/releases/medicine" in result["preserved"]


def test_remove_delete_data_shows_exact_path() -> None:
    result = _removal_plan(Config(), "medicine", True)
    assert result["deleted_paths"] == ["/srv/ship/apps/medicine/data"]


def test_noninteractive_confirmation_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert not _confirm("delete?")


def test_destructive_remove_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ship.cli._confirm", lambda prompt: False)
    with pytest.raises(Exception, match="cancelled"):
        execute(["remove", "medicine", "--delete-data"])
