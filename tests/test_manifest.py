from pathlib import Path

import pytest
from conftest import write_app

from ship.errors import ValidationError
from ship.manifest import derive_domain, load_manifest, validate_name, validate_relative_file


def test_manifest_parsing_and_domain_derivation(tmp_path: Path) -> None:
    write_app(tmp_path)
    manifest = load_manifest(tmp_path / "ship.toml", "apps.teemusaha.com")
    assert manifest.name == "medicine"
    assert manifest.domain == "medicine.apps.teemusaha.com"
    assert manifest.data.enabled


@pytest.mark.parametrize(
    "name", ["../bad", "Bad", "bad name", "bad_name", "-bad", "bad;rm", "bad--name", ""]
)
def test_unsafe_names(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_name(name)


@pytest.mark.parametrize("path", ["../.env", "/tmp/env", "a/../../b", "", ".", "a\\b"])
def test_unsafe_environment_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        validate_relative_file(path, "environment.file")


def test_domain_derivation() -> None:
    assert derive_domain("hello", "apps.teemusaha.com") == "hello.apps.teemusaha.com"


def test_rejects_unrelated_domain(tmp_path: Path) -> None:
    write_app(tmp_path)
    manifest = tmp_path / "ship.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'name = "medicine"', 'name = "medicine"\ndomain = "evil.example.com"'
        )
    )
    with pytest.raises(ValidationError, match="domain must be medicine"):
        load_manifest(manifest, "apps.teemusaha.com")


def test_resource_validation(tmp_path: Path) -> None:
    write_app(tmp_path)
    manifest = tmp_path / "ship.toml"
    manifest.write_text(manifest.read_text().replace("cpus = 0.5", "cpus = 0"))
    with pytest.raises(ValidationError, match="cpus"):
        load_manifest(manifest, "apps.teemusaha.com")
