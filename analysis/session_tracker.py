"""Session tracker with coverage tracking for audit sessions."""

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionCoverage:
    """Track coverage statistics for a session."""
    visited_nodes: set[str] = field(default_factory=set)
    visited_cards: set[str] = field(default_factory=set)
    total_nodes: int = 0
    total_cards: int = 0
    # Per-node/card visit counts
    node_visit_counts: dict[str, int] = field(default_factory=dict)
    card_visit_counts: dict[str, int] = field(default_factory=dict)
    # Known IDs to bound coverage
    known_node_ids: set[str] = field(default_factory=set)
    known_card_ids: set[str] = field(default_factory=set)
    # Node -> cards mapping and visit tracking
    node_card_mapping: dict[str, set[str]] = field(default_factory=dict)
    visited_cards_per_node: dict[str, set[str]] = field(default_factory=dict)
    card_to_nodes: dict[str, set[str]] = field(default_factory=dict)
    
    def add_node(self, node_id: str):
        """Mark a node as visited."""
        self.visited_nodes.add(node_id)
        self.node_visit_counts[node_id] = int(self.node_visit_counts.get(node_id, 0)) + 1
    
    def add_card(self, card_id: str):
        """Mark a card as visited."""
        cid = str(card_id)
        self.visited_cards.add(cid)
        self.card_visit_counts[cid] = int(self.card_visit_counts.get(cid, 0)) + 1

    def register_node_cards(
        self,
        node_id: str,
        card_ids: Iterable[str],
        previously_visited: Iterable[str] | None = None,
    ) -> None:
        """Associate a node with its cards and retain past visits when possible."""

        nid = str(node_id)
        new_cards = {str(cid) for cid in card_ids if cid}

        # Remove stale back-references before updating the mapping
        old_cards = self.node_card_mapping.get(nid, set())
        if old_cards:
            removed = old_cards - new_cards
            for cid in removed:
                nodes = self.card_to_nodes.get(cid)
                if nodes:
                    nodes.discard(nid)
                    if not nodes:
                        self.card_to_nodes.pop(cid, None)

        self.node_card_mapping[nid] = new_cards
        for cid in new_cards:
            self.card_to_nodes.setdefault(cid, set()).add(nid)

        visited_seed = (
            {str(cid) for cid in previously_visited if cid}
            if previously_visited is not None
            else set(self.visited_cards_per_node.get(nid, set()))
        )
        self.visited_cards_per_node[nid] = visited_seed & new_cards

    def add_card_for_node(self, node_id: str, card_id: str) -> None:
        """Record that a card associated with a node was visited."""

        nid = str(node_id)
        cid = str(card_id)
        # Only track cards that are known to belong to the node
        node_cards = self.node_card_mapping.get(nid)
        if node_cards is not None and node_cards and cid not in node_cards:
            return
        if nid not in self.node_card_mapping:
            return
        self.visited_cards_per_node.setdefault(nid, set()).add(cid)

    def get_nodes_for_card(self, card_id: str) -> set[str]:
        """Return all nodes that reference the given card."""

        return set(self.card_to_nodes.get(str(card_id), set()))

    def get_stats(self) -> dict[str, Any]:
        """Get coverage statistics bounded to known IDs to avoid >100%."""
        # Default totals
        nodes_total = len(self.known_node_ids) if self.known_node_ids else self.total_nodes
        cards_total = len(self.known_card_ids) if self.known_card_ids else self.total_cards
        # Bound visited to known sets when available
        nodes_visited = len(self.visited_nodes & self.known_node_ids) if self.known_node_ids else len(self.visited_nodes)
        cards_visited = len(self.visited_cards & self.known_card_ids) if self.known_card_ids else len(self.visited_cards)
        
        def pct(a: int, b: int) -> float:
            return round((a / b * 100.0) if b else 0.0, 1)
        
        per_node_card_coverage: dict[str, Any] = {}
        for node_id, cards in self.node_card_mapping.items():
            visited = self.visited_cards_per_node.get(node_id, set()) & cards
            unvisited = cards - visited
            per_node_card_coverage[node_id] = {
                'card_ids': sorted(cards),
                'visited_card_ids': sorted(visited),
                'unvisited_card_ids': sorted(unvisited),
                'visited': len(visited),
                'total': len(cards),
                'unvisited': len(unvisited),
            }

        return {
            'nodes': {
                'visited': nodes_visited,
                'total': nodes_total,
                'percent': pct(nodes_visited, nodes_total)
            },
            'cards': {
                'visited': cards_visited,
                'total': cards_total,
                'percent': pct(cards_visited, cards_total)
            },
            'visited_node_ids': list(self.visited_nodes),
            'visited_card_ids': list(self.visited_cards),
            'node_visit_counts': dict(self.node_visit_counts),
            'node_card_mapping': {nid: sorted(cards) for nid, cards in self.node_card_mapping.items()},
            'visited_cards_per_node': {
                nid: sorted(cards) for nid, cards in self.visited_cards_per_node.items()
            },
            'per_node_card_coverage': per_node_card_coverage,
        }


class SessionTracker:
    """Track an audit session including coverage, investigations, and planning."""
    
    def __init__(self, session_dir: Path, session_id: str):
        """Initialize session tracker.
        
        Args:
            session_dir: Directory to store session data
            session_id: Unique session identifier
        """
        self.session_dir = Path(session_dir)
        self.session_id = session_id
        self.session_file = self.session_dir / f"{session_id}.json"
        self.lock = threading.Lock()
        
        # Initialize or load session data
        self.session_data = self._load_or_init()
        
        # Initialize coverage tracker
        self.coverage = SessionCoverage()
        if 'coverage' in self.session_data:
            cov_data = self.session_data['coverage']
            self.coverage.visited_nodes = set(cov_data.get('visited_node_ids', []))
            self.coverage.visited_cards = set(cov_data.get('visited_card_ids', []))
            self.coverage.total_nodes = cov_data.get('nodes', {}).get('total', 0)
            self.coverage.total_cards = cov_data.get('cards', {}).get('total', 0)
            self.coverage.node_visit_counts = dict(cov_data.get('node_visit_counts', {}))

            node_card_mapping_data: dict[str, Iterable[str]] = {
                str(node_id): cards
                for node_id, cards in (cov_data.get('node_card_mapping') or {}).items()
            }
            visited_cards_per_node_data: dict[str, Iterable[str]] = {
                str(node_id): cards
                for node_id, cards in (cov_data.get('visited_cards_per_node') or {}).items()
            }
            if not node_card_mapping_data and 'per_node_card_coverage' in cov_data:
                for node_id, info in (cov_data.get('per_node_card_coverage') or {}).items():
                    cards = info.get('card_ids') or []
                    node_card_mapping_data[str(node_id)] = cards
                    visited_cards_per_node_data.setdefault(
                        str(node_id), info.get('visited_card_ids') or []
                    )
            for node_id, cards in node_card_mapping_data.items():
                self.coverage.register_node_cards(
                    node_id,
                    cards or [],
                    previously_visited=visited_cards_per_node_data.get(str(node_id), []),
                )
    
    def _load_or_init(self) -> dict[str, Any]:
        """Load existing session or initialize new one."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        if self.session_file.exists():
            try:
                with open(self.session_file) as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Initialize new session
        return {
            'session_id': self.session_id,
            'start_time': datetime.now().isoformat(),
            'status': 'active',
            'models': {},
            'investigations': [],
            'planning_history': [],
            'token_usage': {},
            'coverage': {}
        }
    
    def set_models(self, scout_model: str, strategist_model: str):
        """Set the models being used."""
        self.session_data['models'] = {
            'scout': scout_model,
            'strategist': strategist_model
        }
        self._save()
    
    def initialize_coverage(self, graphs_dir: Path, manifest_dir: Path):
        """Initialize coverage tracking by counting total nodes and cards.

        Args:
            graphs_dir: Directory containing graph files
            manifest_dir: Directory containing manifest files
        """
        known_node_ids: set[str] = set()
        node_card_map: dict[str, set[str]] = {}
        referenced_card_ids: set[str] = set()
        total_nodes = 0

        if graphs_dir.exists():
            for graph_file in graphs_dir.glob("graph_*.json"):
                try:
                    with open(graph_file) as f:
                        graph_data = json.load(f)
                except Exception:
                    continue

                nodes = graph_data.get('nodes', []) or []
                total_nodes += len(nodes)

                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    nid = node.get('id')
                    if nid is None:
                        continue

                    nid_str = str(nid)
                    known_node_ids.add(nid_str)

                    refs = node.get('source_refs') or node.get('refs') or []
                    node_cards = node_card_map.setdefault(nid_str, set())
                    for ref in refs:
                        card_id: str | None = None
                        if isinstance(ref, str):
                            card_id = ref
                        elif isinstance(ref, dict):
                            card_id = (
                                ref.get('card_id')
                                or ref.get('id')
                                or ref.get('card')
                                or ref.get('cardId')
                            )
                            if not card_id:
                                value = ref.get('value')
                                if isinstance(value, str):
                                    card_id = value
                        if card_id:
                            cid = str(card_id)
                            node_cards.add(cid)
                            referenced_card_ids.add(cid)

        manifest_file = manifest_dir / "manifest.json" if manifest_dir.exists() else None
        total_cards = 0
        self._repo_root = None
        if manifest_file and manifest_file.exists():
            try:
                with open(manifest_file) as f:
                    manifest_data = json.load(f)
            except Exception:
                manifest_data = None
            if isinstance(manifest_data, dict):
                num_cards = manifest_data.get('num_cards')
                files_list = manifest_data.get('files')
                if isinstance(num_cards, int):
                    total_cards = num_cards
                elif isinstance(files_list, list):
                    total_cards = len(files_list)

                repo_root = manifest_data.get('repository')
                if isinstance(repo_root, str):
                    self._repo_root = repo_root

        self._file_to_cards: dict[str, set[str]] = {}
        card_store_ids: set[str] = set()

        cards_jsonl = manifest_dir / 'cards.jsonl'
        if cards_jsonl.exists():
            try:
                with open(cards_jsonl) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            card = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(card, dict):
                            continue
                        cid = card.get('id')
                        cid_str = str(cid) if cid else None
                        if cid_str:
                            card_store_ids.add(cid_str)
                        rel_candidates = []
                        rel = card.get('relpath') or card.get('path')
                        if rel:
                            rel_candidates.append(rel)
                        metadata = card.get('metadata') or {}
                        if isinstance(metadata, dict):
                            rel_meta = metadata.get('relpath') or metadata.get('path')
                            if rel_meta:
                                rel_candidates.append(rel_meta)
                        if cid_str:
                            for rel_value in rel_candidates:
                                self._index_file_to_card(rel_value, cid_str)
            except Exception:
                pass

        files_json = manifest_dir / 'files.json'
        if files_json.exists():
            try:
                with open(files_json) as f:
                    files_list = json.load(f)
            except Exception:
                files_list = None
            if isinstance(files_list, list):
                for entry in files_list:
                    if not isinstance(entry, dict):
                        continue
                    rel = entry.get('relpath') or entry.get('path')
                    cids = entry.get('card_ids', []) or []
                    for cid in cids:
                        cid_str = str(cid)
                        card_store_ids.add(cid_str)
                        if rel:
                            self._index_file_to_card(rel, cid_str)

        known_card_ids = referenced_card_ids | card_store_ids

        previous_visits = {
            node_id: set(cards)
            for node_id, cards in self.coverage.visited_cards_per_node.items()
        }
        self.coverage.node_card_mapping = {}
        self.coverage.card_to_nodes = {}
        self.coverage.visited_cards_per_node = {}

        all_node_ids = set(node_card_map.keys()) | known_node_ids
        for node_id in all_node_ids:
            cards = node_card_map.get(node_id, set())
            previously_visited = previous_visits.get(node_id, set())
            self.coverage.register_node_cards(
                node_id,
                cards,
                previously_visited=previously_visited,
            )

        self.coverage.known_node_ids = known_node_ids
        self.coverage.known_card_ids = known_card_ids
        self.coverage.total_nodes = total_nodes
        self.coverage.total_cards = max(total_cards, len(known_card_ids))
        self._save()

    def _index_file_to_card(self, relpath: str | Path, card_id: str) -> None:
        """Index a card ID by a variety of path representations."""

        if not relpath or not card_id:
            return

        path_str = str(relpath)
        cid = str(card_id)
        if not path_str or not cid:
            return

        mapping = getattr(self, '_file_to_cards', None)
        if mapping is None:
            self._file_to_cards = {}
            mapping = self._file_to_cards

        variants: set[str] = set()
        normalized = path_str.replace('\\', '/')
        variants.update({path_str, normalized})

        for candidate in list(variants):
            variants.add(candidate.lstrip('/'))
            variants.add(candidate.lstrip('./'))

        try:
            posix = Path(path_str).as_posix()
            variants.update({posix, posix.lstrip('/'), posix.lstrip('./')})
        except Exception:
            pass

        repo_root = getattr(self, '_repo_root', None)
        if repo_root:
            try:
                repo_root_path = Path(repo_root)
                rel_path = Path(path_str)
                if rel_path.is_absolute():
                    try:
                        rel_to_root = rel_path.relative_to(repo_root_path)
                        rel_posix = rel_to_root.as_posix()
                        variants.update({rel_posix, rel_posix.lstrip('/'), rel_posix.lstrip('./')})
                    except Exception:
                        pass
                else:
                    abs_path = (repo_root_path / rel_path).resolve()
                    variants.add(abs_path.as_posix())
            except Exception:
                pass

        for key in {v for v in variants if v}:
            bucket = mapping.setdefault(key, set())
            bucket.add(cid)

    def _candidate_card_keys(self, identifier: str) -> set[str]:
        """Return possible lookup keys for a card identifier or path."""

        if identifier is None:
            return set()

        value = str(identifier)
        if not value:
            return set()

        variants: set[str] = {value, value.lstrip('./')}
        normalized = value.replace('\\', '/')
        variants.update({normalized, normalized.lstrip('/'), normalized.lstrip('./')})

        try:
            posix = Path(value).as_posix()
            variants.update({posix, posix.lstrip('/'), posix.lstrip('./')})
        except Exception:
            pass

        repo_root = getattr(self, '_repo_root', None)
        if repo_root:
            try:
                repo_root_path = Path(repo_root)
                value_path = Path(value)
                if value_path.is_absolute():
                    try:
                        rel = value_path.relative_to(repo_root_path)
                        rel_posix = rel.as_posix()
                        variants.update({rel_posix, rel_posix.lstrip('/'), rel_posix.lstrip('./')})
                    except Exception:
                        pass
                else:
                    abs_posix = (repo_root_path / value_path).resolve().as_posix()
                    variants.add(abs_posix)
            except Exception:
                pass

        return {v for v in variants if v}

    def _resolve_card_ids(self, identifier: str) -> set[str]:
        """Resolve a card identifier or path to known card IDs."""

        if identifier is None:
            return set()

        ident = str(identifier)
        resolved: set[str] = set()

        if ident in self.coverage.known_card_ids or ident in self.coverage.card_to_nodes:
            resolved.add(ident)

        mapping = getattr(self, '_file_to_cards', None)
        if mapping:
            for key in self._candidate_card_keys(ident):
                cards = mapping.get(key)
                if cards:
                    resolved.update(cards)

        return resolved

    def _record_card_visits(self, identifiers: Iterable[str]) -> None:
        """Apply visit tracking for one or more card identifiers."""

        for identifier in identifiers:
            if identifier is None:
                continue
            resolved_ids = self._resolve_card_ids(identifier)
            if resolved_ids:
                for cid in resolved_ids:
                    self.coverage.add_card(cid)
                    for node_id in self.coverage.get_nodes_for_card(cid):
                        self.coverage.add_card_for_node(node_id, cid)
            else:
                self.coverage.add_card(str(identifier))

    def track_node_visit(self, node_id: str):
        """Track that a node was visited during investigation."""
        with self.lock:
            self.coverage.add_node(node_id)
            self._save()
    
    def track_card_visit(self, card_path: str):
        """Track that a code card was analyzed."""
        with self.lock:
            self._record_card_visits([card_path])
            self._save()
    
    def track_nodes_batch(self, node_ids: list[str]):
        """Track multiple nodes visited at once."""
        with self.lock:
            for node_id in node_ids:
                self.coverage.add_node(node_id)
            self._save()
    
    def track_cards_batch(self, card_paths: list[str]):
        """Track multiple cards analyzed at once."""
        with self.lock:
            self._record_card_visits(card_paths)
            self._save()
    
    def add_investigation(self, investigation: dict[str, Any]):
        """Add an investigation to the session history."""
        with self.lock:
            self.session_data['investigations'].append({
                'timestamp': datetime.now().isoformat(),
                **investigation
            })
            self._save()
    
    def add_planning(self, plan_items: list[dict[str, Any]]):
        """Add a planning batch to the history."""
        with self.lock:
            self.session_data['planning_history'].append({
                'timestamp': datetime.now().isoformat(),
                'items': plan_items
            })
            self._save()
    
    def update_token_usage(self, tokens: dict[str, Any]):
        """Update token usage statistics."""
        with self.lock:
            # The token tracker passes a complex structure with total_usage, by_model, and history
            # We'll store the entire structure
            self.session_data['token_usage'] = tokens
            self._save()
    
    def get_coverage_stats(self) -> dict[str, Any]:
        """Get current coverage statistics."""
        return self.coverage.get_stats()
    
    def finalize(self, status: str = 'completed'):
        """Mark session as finalized."""
        with self.lock:
            self.session_data['status'] = status
            self.session_data['end_time'] = datetime.now().isoformat()
            self.session_data['coverage'] = self.coverage.get_stats()
            self._save()
    
    def set_status(self, status: str):
        """Set current session status without finalizing."""
        with self.lock:
            self.session_data['status'] = status
            # Do not touch end_time here; only set on finalize
            self._save()
    
    def _save(self):
        """Save session data to file (call within lock)."""
        try:
            # Include current coverage in saved data
            self.session_data['coverage'] = self.coverage.get_stats()
            
            with open(self.session_file, 'w') as f:
                json.dump(self.session_data, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: Failed to save session data: {e}")
