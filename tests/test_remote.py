from pathlib import Path

import pytest

from ship.errors import CommandError
from ship.remote import RSYNC_EXCLUDES, rsync_args, ssh_args


def test_rsync_exclusion_rules(tmp_path: Path) -> None:
    args = rsync_args(tmp_path, "deploy@example.com", "/srv/ship/releases/app/id")
    assert "--protect-args" not in args  # Unsupported by macOS's bundled rsync 2.6.9.
    for excluded in (".git", ".env.*", "*.duckdb", "data", "node_modules"):
        assert excluded in RSYNC_EXCLUDES
        assert excluded in args


def test_remote_command_construction_quotes_each_argument() -> None:
    args = ssh_args("deploy@example.com", ["printf", "%s", "hello world; $(touch /tmp/no)"])
    assert args[:2] == ["ssh", "-o"]
    assert args[-2] == "deploy@example.com"
    assert args[-1] == "printf %s 'hello world; $(touch /tmp/no)'"


@pytest.mark.parametrize("target", ["-oProxyCommand=bad", "a b", "a;bad", "x\ncommand"])
def test_ssh_target_safety(target: str) -> None:
    with pytest.raises(CommandError):
        ssh_args(target, ["true"])


def test_ssh_rejects_newline_argument() -> None:
    with pytest.raises(CommandError):
        ssh_args("deploy@example.com", ["printf", "bad\ncommand"])


def test_rsync_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(CommandError):
        rsync_args(tmp_path, "deploy@example.com", "/srv/ship/../root")
