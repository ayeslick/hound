"""Tests for graph build CLI handling when ingestion finds no files."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import typer

from commands import graph as graph_cmd


class TestGraphBuildNoFiles(unittest.TestCase):
    """Ensure the graph build command provides actionable guidance when empty."""

    def setUp(self) -> None:
        self.temp_home = Path(tempfile.mkdtemp())
        self.projects_root = self.temp_home / ".hound" / "projects"
        self.project_id = "emptyproj"
        self.project_dir = self.projects_root / self.project_id
        self.repo_path = self.temp_home / "repo"

        self.repo_path.mkdir(parents=True, exist_ok=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        project_config = {"source_path": str(self.repo_path)}
        (self.project_dir / "project.json").write_text(json.dumps(project_config))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_home, ignore_errors=True)

    @patch("commands.graph.RepositoryManifest.walk_repository", return_value=([], []))
    @patch("commands.graph.load_config", return_value={})
    def test_empty_manifest_prompts_source_path_check(self, _load_config, _walk_repo):
        """An empty manifest should mention the repo path and source_path guidance."""
        with patch("pathlib.Path.home", return_value=self.temp_home):
            with patch.object(graph_cmd.console, "print") as mock_print:
                with self.assertRaises(typer.Exit) as exit_ctx:
                    graph_cmd.build(
                        self.project_id,
                        file_filter=None,
                        ignore_filter=None,
                        with_spec=None,
                        graph_spec=None,
                        refine_existing=False,
                    )

        self.assertEqual(exit_ctx.exception.exit_code, 2)

        rendered = [
            " ".join(str(arg) for arg in call.args)
            for call in mock_print.call_args_list
        ]

        resolved_repo = str(self.repo_path.resolve())
        self.assertTrue(
            any(resolved_repo in message for message in rendered),
            "Expected error output to include the resolved repository path.",
        )
        self.assertTrue(
            any("source_path" in message for message in rendered),
            "Expected guidance to explicitly mention checking the project's source_path.",
        )


if __name__ == "__main__":
    unittest.main()
