"""Tests for session tracker coverage handling."""

from pathlib import Path

from analysis.session_tracker import SessionTracker


def _make_tracker(tmp_path: Path) -> SessionTracker:
    tracker = SessionTracker(tmp_path, "test_session")
    tracker.coverage.total_nodes = 1
    tracker.coverage.total_cards = 2
    tracker.coverage.known_card_ids = {"cardA", "cardB"}
    tracker.coverage.register_node_cards("node1", {"cardA", "cardB"}, "Graph")
    # Directly seed file-to-card mapping to simulate manifest data
    tracker._file_to_cards = {
        "src/foo.sol": ["cardA"],
        "src/bar.sol": ["cardB"],
    }
    return tracker


def test_track_card_visit_resolves_paths(tmp_path):
    tracker = _make_tracker(tmp_path)

    # Provide an absolute path to ensure suffix matching works
    absolute = tmp_path / "src" / "foo.sol"
    tracker.track_card_visit(absolute)

    stats = tracker.get_coverage_stats()
    assert "cardA" in stats["visited_card_ids"]
    node = next(entry for entry in stats["node_card_summary"] if entry["node_id"] == "node1")
    assert node["visited_cards"] == 1


def test_track_cards_batch_uses_same_resolution(tmp_path):
    tracker = _make_tracker(tmp_path)

    tracker.track_cards_batch(["src/foo.sol", tmp_path / "src" / "bar.sol"])

    stats = tracker.get_coverage_stats()
    assert {"cardA", "cardB"}.issubset(set(stats["visited_card_ids"]))
    node = next(entry for entry in stats["node_card_summary"] if entry["node_id"] == "node1")
    assert node["visited_cards"] == 2
