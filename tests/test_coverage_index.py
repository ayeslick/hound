"""Tests for CoverageIndex utility methods."""

from __future__ import annotations

import json

from analysis.coverage_index import CoverageIndex


def test_compute_stats_streams_jsonl(tmp_path):
    graphs_dir = tmp_path / "graphs"
    manifest_dir = tmp_path / "manifest"
    graphs_dir.mkdir()
    manifest_dir.mkdir()

    (graphs_dir / "graph_Test.json").write_text(json.dumps({
        "nodes": [
            {"id": "n1"},
            {"id": "n2"},
        ]
    }))

    cards_path = manifest_dir / "cards.jsonl"
    with cards_path.open("w", encoding="utf-8") as fh:
        for cid in ("card-1", "card-2", "card-3"):
            fh.write(json.dumps({"id": cid}) + "\n")

    cov = CoverageIndex(tmp_path / "coverage_index.json", agent_id="tester")
    cov.touch_node("n1")
    cov.touch_card("card-2")

    stats = cov.compute_stats(graphs_dir, manifest_dir)

    assert stats["nodes"]["total"] == 2
    assert stats["nodes"]["visited"] == 1
    assert stats["cards"]["total"] == 3
    assert stats["cards"]["visited"] == 1
