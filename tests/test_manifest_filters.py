"""Tests for include/ignore pattern handling in RepositoryManifest."""

from pathlib import Path

from ingest.manifest import RepositoryManifest, normalize_patterns


def _write_file(path: Path, content: str = "print('hello world')\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_normalize_patterns_deduplicates_and_strips() -> None:
    patterns = normalize_patterns([" ./src/app.py ", "./src/app.py", "src/app.py", None, ""])
    assert patterns == ["src/app.py"]


def test_repository_manifest_glob_includes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_file(repo / "src" / "module" / "app.py")
    _write_file(repo / "src" / "module" / "helper.py")
    _write_file(repo / "tests" / "test_app.py")

    manifest = RepositoryManifest(
        str(repo),
        config={"file_extensions": [".py"]},
        file_filter=["src/**/*.py"],
    )

    _cards, files = manifest.walk_repository()
    relpaths = sorted(Path(f.relpath).as_posix() for f in files)
    assert relpaths == ["src/module/app.py", "src/module/helper.py"]


def test_repository_manifest_ignore_patterns(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_file(repo / "src" / "module" / "app.py")
    _write_file(repo / "src" / "module" / "helper.py")
    _write_file(repo / "tests" / "test_app.py")
    _write_file(repo / "src" / "module" / "utils" / "tool.py")

    manifest = RepositoryManifest(
        str(repo),
        config={"file_extensions": [".py"]},
        ignore_patterns=["tests/**/*.py", "src/**/utils/*.py"],
    )

    _cards, files = manifest.walk_repository()
    relpaths = sorted(Path(f.relpath).as_posix() for f in files)
    assert relpaths == ["src/module/app.py", "src/module/helper.py"]


def test_repository_manifest_include_and_ignore(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_file(repo / "src" / "module" / "app.py")
    _write_file(repo / "src" / "module" / "utils" / "tool.py")
    _write_file(repo / "tests" / "test_app.py")

    manifest = RepositoryManifest(
        str(repo),
        config={"file_extensions": [".py"]},
        file_filter=["src/**/*.py", "tests/**/*.py"],
        ignore_patterns=["**/utils/*.py"],
    )

    _cards, files = manifest.walk_repository()
    relpaths = sorted(Path(f.relpath).as_posix() for f in files)
    assert relpaths == ["src/module/app.py", "tests/test_app.py"]
