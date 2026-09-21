from pathlib import Path

import pytest

from ship.config import Config, load_config
from ship.errors import ValidationError


def test_toml_parsing_and_precedence(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('ssh_target = "file@example"\nport_start = 11000\n')
    config = load_config(
        path=path,
        environ={"SHIP_SSH_TARGET": "env@example", "SHIP_PORT_START": "12000"},
        overrides={"ssh_target": "option@example"},
    )
    assert config.ssh_target == "option@example"
    assert config.port_start == 12000
    assert config.base_domain == Config().base_domain


def test_rejects_unknown_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("password = 'never'\n")
    with pytest.raises(ValidationError, match="unknown config"):
        load_config(path=path, environ={})


def test_environment_integer_validation() -> None:
    with pytest.raises(ValidationError, match="SHIP_PORT_START"):
        load_config(path=Path("/missing"), environ={"SHIP_PORT_START": "nope"})
