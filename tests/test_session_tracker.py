"""Tests for session tracker coverage mapping and card tracking."""

import json
from pathlib import Path

from analysis.session_tracker import SessionTracker


def _create_test_environment(tmp_path: Path):
    session_dir = tmp_path / "session"
    graphs_dir = tmp_path / "graphs"
    manifest_dir = tmp_path / "manifest"
    repo_root = tmp_path / "repo"

    graphs_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    (repo_root / "src/module").mkdir(parents=True)

    graph_data = {
        "nodes": [
            {"id": "node_a", "source_refs": ["card1", "card2"]},
            {"id": "node_b", "source_refs": ["card2"]},
        ]
    }
    with open(graphs_dir / "graph_test.json", "w") as f:
        json.dump(graph_data, f)

    manifest_data = {"repository": str(repo_root), "num_cards": 2}
    with open(manifest_dir / "manifest.json", "w") as f:
        json.dump(manifest_data, f)

    cards = [
        {"id": "card1", "relpath": "src/module/file1.sol"},
        {"id": "card2", "relpath": "src/module/file2.sol"},
    ]
    with open(manifest_dir / "cards.jsonl", "w") as f:
        for card in cards:
            f.write(json.dumps(card) + "\n")

    return session_dir, graphs_dir, manifest_dir, repo_root


def test_session_tracker_per_node_card_coverage(tmp_path):
    session_dir, graphs_dir, manifest_dir, repo_root = _create_test_environment(tmp_path)

    tracker = SessionTracker(session_dir, "session")
    tracker.initialize_coverage(graphs_dir, manifest_dir)

    assert tracker.coverage.node_card_mapping["node_a"] == {"card1", "card2"}
    assert tracker.coverage.node_card_mapping["node_b"] == {"card2"}
    assert tracker.coverage.card_to_nodes["card2"] == {"node_a", "node_b"}

    tracker.track_card_visit(str(repo_root / "src/module/file1.sol"))

    stats = tracker.get_coverage_stats()
    assert stats["cards"]["visited"] == 1
    assert stats["per_node_card_coverage"]["node_a"]["visited"] == 1
    assert stats["per_node_card_coverage"]["node_a"]["unvisited_card_ids"] == ["card2"]
    assert stats["per_node_card_coverage"]["node_b"]["visited"] == 0
    assert stats["visited_cards_per_node"]["node_a"] == ["card1"]
    assert stats["visited_cards_per_node"]["node_b"] == []

    tracker.initialize_coverage(graphs_dir, manifest_dir)
    assert tracker.coverage.visited_cards_per_node["node_a"] == {"card1"}

    tracker.track_card_visit("card2")

    stats = tracker.get_coverage_stats()
    assert set(stats["visited_card_ids"]) == {"card1", "card2"}
    assert stats["per_node_card_coverage"]["node_a"]["visited"] == 2
    assert stats["per_node_card_coverage"]["node_a"]["unvisited"] == 0
    assert stats["per_node_card_coverage"]["node_b"]["visited"] == 1
    assert stats["visited_cards_per_node"]["node_b"] == ["card2"]


def test_track_cards_batch_maps_paths_and_ids(tmp_path):
    session_dir, graphs_dir, manifest_dir, repo_root = _create_test_environment(tmp_path)

    tracker = SessionTracker(session_dir, "batch")
    tracker.initialize_coverage(graphs_dir, manifest_dir)

    tracker.track_cards_batch([
        "src/module/file1.sol",
        str((repo_root / "src/module/file2.sol").resolve()),
    ])

    stats = tracker.get_coverage_stats()
    assert stats["cards"]["visited"] == 2
    assert stats["per_node_card_coverage"]["node_a"]["visited"] == 2
    assert stats["per_node_card_coverage"]["node_b"]["visited"] == 1
    assert tracker.coverage.visited_cards_per_node["node_a"] == {"card1", "card2"}
    assert tracker.coverage.visited_cards_per_node["node_b"] == {"card2"}
