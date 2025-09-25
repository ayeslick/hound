import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from commands.project import ProjectManager, project as project_cmd


@pytest.fixture
def temp_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_set_source_updates_registry_and_config(temp_home, tmp_path):
    src_old = tmp_path / "src_old"
    src_old.mkdir()
    src_new = tmp_path / "src_new"
    src_new.mkdir()

    manager = ProjectManager()
    manager.create_project("demo", str(src_old))

    runner = CliRunner()
    result = runner.invoke(project_cmd, ["set-source", "demo", str(src_new)])

    assert result.exit_code == 0
    assert "Source path updated" in result.output
    assert "re-run ingestion" in result.output.lower()

    project_dir = temp_home / ".hound" / "projects" / "demo"
    config = json.loads((project_dir / "project.json").read_text())
    assert config["source_path"] == str(src_new.resolve())

    registry_path = temp_home / ".hound" / "projects" / "registry.json"
    registry = json.loads(registry_path.read_text())
    assert registry["projects"]["demo"]["source_path"] == str(src_new.resolve())


def test_set_source_rejects_missing_path(temp_home, tmp_path):
    src_old = tmp_path / "old"
    src_old.mkdir()
    missing = tmp_path / "missing"

    manager = ProjectManager()
    manager.create_project("demo", str(src_old))

    runner = CliRunner()
    result = runner.invoke(project_cmd, ["set-source", "demo", str(missing)])

    assert result.exit_code == 1
    assert "Source path does not exist" in result.output

    project_dir = temp_home / ".hound" / "projects" / "demo"
    config = json.loads((project_dir / "project.json").read_text())
    assert config["source_path"] == str(src_old.resolve())

    registry_path = temp_home / ".hound" / "projects" / "registry.json"
    registry = json.loads(registry_path.read_text())
    assert registry["projects"]["demo"]["source_path"] == str(src_old.resolve())
