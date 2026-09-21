import socket
from pathlib import Path

import pytest

from ship.caddy import atomic_caddy_commands, fragment
from ship.errors import ShipError
from ship.state import (
    allocate_port,
    atomic_write_state,
    deployment_lock,
    load_state,
    port_is_available,
)


def test_port_allocation_is_stable_and_skips_allocated() -> None:
    apps = {"one": {"port": 10000}, "two": {"port": 10002}}
    assert allocate_port("one", apps, 10000, 10003) == 10000
    assert allocate_port("three", apps, 10000, 10003) == 10001


def test_port_collision_detection() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        assert not port_is_available(port)


def test_caddy_fragment() -> None:
    assert fragment("medicine.apps.teemusaha.com", 10001) == (
        "medicine.apps.teemusaha.com {\n    reverse_proxy 127.0.0.1:10001\n}\n"
    )


def test_caddy_atomic_update_order() -> None:
    commands = atomic_caddy_commands("medicine", "/safe/medicine.caddy")
    assert commands[0][0] == "install"
    assert commands[1][:2] == ["caddy", "validate"]
    assert commands[2][0] == "mv"
    assert commands[3] == ["systemctl", "reload", "caddy"]


def test_atomic_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state/apps.json"
    state = {"version": 1, "apps": {"medicine": {"port": 10000}}}
    atomic_write_state(path, state)
    assert load_state(path) == state
    assert path.stat().st_mode & 0o777 == 0o600


def test_deployment_lock(tmp_path: Path) -> None:
    with (
        deployment_lock(tmp_path, "medicine"),
        pytest.raises(ShipError, match="in progress"),
        deployment_lock(tmp_path, "medicine"),
    ):
        pass
    with deployment_lock(tmp_path, "medicine"):
        pass
