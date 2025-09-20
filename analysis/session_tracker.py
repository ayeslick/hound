"""Session tracker with coverage tracking for audit sessions."""

import json
import threading
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
    # Node → cards mapping harvested from knowledge graphs
    node_card_map: dict[str, set[str]] = field(default_factory=dict)
    # Node → primary graph mapping for focus area annotations
    node_graph_map: dict[str, str] = field(default_factory=dict)
    
    def add_node(self, node_id: str):
        """Mark a node as visited."""
        self.visited_nodes.add(node_id)
        self.node_visit_counts[node_id] = int(self.node_visit_counts.get(node_id, 0)) + 1
    
    def add_card(self, card_id: str):
        """Mark a card as visited."""
        self.visited_cards.add(card_id)
        self.card_visit_counts[card_id] = int(self.card_visit_counts.get(card_id, 0)) + 1

    def register_node_cards(self, node_id: str, card_ids: set[str] | list[str] | tuple[str, ...], graph: str | None = None):
        """Associate cards with a node for card-aware coverage metrics."""

        if not node_id:
            return

        if graph:
            try:
                self.node_graph_map.setdefault(str(node_id), str(graph))
            except Exception:
                pass

        if not card_ids:
            # Still ensure the node is tracked for graph mapping even if no cards
            self.node_card_map.setdefault(str(node_id), set())
            return

        target = self.node_card_map.setdefault(str(node_id), set())
        for cid in card_ids:
            if not cid:
                continue
            try:
                target.add(str(cid))
            except Exception:
                continue

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
        
        node_card_summary: list[dict[str, Any]] = []
        visited_cards_set = set(self.visited_cards)
        all_nodes = set(self.node_graph_map.keys()) | set(self.node_card_map.keys())

        for node_id in sorted(all_nodes):
            cards_for_node = self.node_card_map.get(node_id, set())
            if not isinstance(cards_for_node, set):
                cards_for_node = set(cards_for_node or [])
            total_cards = len(cards_for_node)
            visited_cards = len(cards_for_node & visited_cards_set)
            unvisited_cards = max(total_cards - visited_cards, 0)
            coverage_percent = pct(visited_cards, total_cards) if total_cards else (100.0 if node_id in self.visited_nodes else 0.0)
            node_card_summary.append({
                'node_id': node_id,
                'graph': self.node_graph_map.get(node_id),
                'total_cards': total_cards,
                'visited_cards': visited_cards,
                'unvisited_cards': unvisited_cards,
                'coverage_percent': coverage_percent,
                'visit_count': int(self.node_visit_counts.get(node_id, 0)),
            })

        # Sort summary by coverage gaps (largest remaining card count first)
        node_card_summary.sort(key=lambda x: (x['unvisited_cards'], x['total_cards'], -x['coverage_percent']), reverse=True)

        top_unvisited_nodes = [entry for entry in node_card_summary if entry['unvisited_cards'] > 0]
        fully_covered_nodes = [
            entry for entry in node_card_summary
            if entry['total_cards'] > 0 and entry['unvisited_cards'] == 0
        ]
        fully_covered_nodes.sort(key=lambda x: (x['total_cards'], -x['visit_count']), reverse=True)

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
            'node_card_summary': node_card_summary,
            'top_unvisited_nodes': top_unvisited_nodes[:20],
            'fully_covered_nodes': fully_covered_nodes[:20],
            'node_card_map': {node: sorted(list(cards)) for node, cards in self.node_card_map.items()},
            'node_graph_map': dict(self.node_graph_map),
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
            node_card_map = cov_data.get('node_card_map', {})
            if isinstance(node_card_map, dict):
                rebuilt: dict[str, set[str]] = {}
                for node_id, card_list in node_card_map.items():
                    try:
                        rebuilt[str(node_id)] = {str(cid) for cid in (card_list or []) if cid}
                    except Exception:
                        continue
                if rebuilt:
                    self.coverage.node_card_map = rebuilt
            node_graph_map = cov_data.get('node_graph_map', {})
            if isinstance(node_graph_map, dict):
                try:
                    self.coverage.node_graph_map = {str(k): str(v) for k, v in node_graph_map.items() if v is not None}
                except Exception:
                    pass
    
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
        # Reset derived metadata so stale entries from previous runs are cleared
        self.coverage.node_card_map = {}
        self.coverage.node_graph_map = {}
        self.coverage.known_node_ids = set()
        self.coverage.known_card_ids = set()

        def _cards_from_node(node: dict[str, Any]) -> set[str]:
            """Extract card identifiers referenced by a graph node."""

            card_ids: set[str] = set()

            if isinstance(node, dict):
                for key in ('source_refs', 'refs'):
                    refs = node.get(key)
                    if isinstance(refs, list):
                        for ref in refs:
                            if isinstance(ref, str):
                                card_ids.add(ref)
                            elif isinstance(ref, dict):
                                for cand in ('card_id', 'id', 'ref'):
                                    val = ref.get(cand)
                                    if isinstance(val, str):
                                        card_ids.add(val)

                cards_field = node.get('cards')
                if isinstance(cards_field, list):
                    for entry in cards_field:
                        if isinstance(entry, dict):
                            for cand in ('card_id', 'id'):
                                val = entry.get(cand)
                                if isinstance(val, str):
                                    card_ids.add(val)

                artifacts = node.get('artifacts')
                if isinstance(artifacts, list):
                    for art in artifacts:
                        if not isinstance(art, dict):
                            continue
                        art_type = str(art.get('type', '')).lower()
                        if art_type and all(tok not in art_type for tok in ('code', 'card', 'source')):
                            continue
                        for cand in ('card_id', 'id', 'ref'):
                            val = art.get(cand)
                            if isinstance(val, str):
                                card_ids.add(val)

            return {str(cid) for cid in card_ids if cid}

        # Count nodes from graphs and record known IDs
        total_nodes = 0
        if graphs_dir.exists():
            for graph_file in graphs_dir.glob("graph_*.json"):
                try:
                    with open(graph_file) as f:
                        graph_data = json.load(f)
                        nodes = graph_data.get('nodes', [])
                        graph_name = (
                            graph_data.get('name')
                            or graph_data.get('internal_name')
                            or graph_file.stem.replace('graph_', '')
                        )
                        total_nodes += len(nodes)
                        for n in nodes or []:
                            nid = n.get('id')
                            if nid is not None:
                                sid = str(nid)
                                self.coverage.known_node_ids.add(sid)
                                node_cards = _cards_from_node(n)
                                if node_cards:
                                    for cid in node_cards:
                                        self.coverage.known_card_ids.add(str(cid))
                                self.coverage.register_node_cards(sid, node_cards, graph_name)
                            else:
                                label = n.get('label') if isinstance(n, dict) else None
                                if isinstance(label, str) and label:
                                    self.coverage.register_node_cards(label, set(), graph_name)
                except Exception:
                    pass
        
        # Count cards from manifest
        total_cards = 0
        manifest_file = manifest_dir / "manifest.json" if manifest_dir.exists() else None
        if manifest_file and manifest_file.exists():
            try:
                with open(manifest_file) as f:
                    manifest_data = json.load(f)
                    # Try both formats - num_cards or files array
                    if 'num_cards' in manifest_data:
                        total_cards = manifest_data['num_cards']
                    elif 'files' in manifest_data:
                        total_cards = len(manifest_data['files'])
            except Exception:
                pass
        
        # Build known card IDs and file->cards mapping for accurate tracking
        try:
            self._file_to_cards: dict[str, list[str]] = {}
            cards_jsonl = manifest_dir / 'cards.jsonl'
            if cards_jsonl.exists():
                with open(cards_jsonl) as f:
                    for line in f:
                        try:
                            card = json.loads(line)
                            cid = card.get('id')
                            rel = card.get('relpath')
                            if cid:
                                self.coverage.known_card_ids.add(str(cid))
                            if rel and cid:
                                self._file_to_cards.setdefault(rel, []).append(str(cid))
                        except Exception:
                            continue
            files_json = manifest_dir / 'files.json'
            if files_json.exists():
                with open(files_json) as f:
                    files_list = json.load(f)
                if isinstance(files_list, list):
                    for fi in files_list:
                        rel = fi.get('relpath')
                        cids = fi.get('card_ids', []) or []
                        if rel and cids:
                            self._file_to_cards[rel] = [str(x) for x in cids]
                            for x in cids:
                                self.coverage.known_card_ids.add(str(x))
        except Exception:
            pass

        self.coverage.total_nodes = total_nodes
        self.coverage.total_cards = total_cards
        self._save()
    
    def track_node_visit(self, node_id: str):
        """Track that a node was visited during investigation."""
        with self.lock:
            self.coverage.add_node(node_id)
            self._save()
    
    def _record_card_visit(self, card_ref: str | Path | None):
        """Internal helper to record a card visit without touching the lock."""

        if not card_ref:
            return

        try:
            ref_str = str(card_ref)
        except Exception:
            ref_str = card_ref  # type: ignore[assignment]

        if not ref_str:
            return

        ids: list[str] = []
        mapping = getattr(self, '_file_to_cards', None)
        if isinstance(mapping, dict):
            normalized = ref_str.replace('\\', '/').strip()
            candidates: list[str] = []

            def _add_candidate(value: str | None):
                if not value:
                    return
                sval = str(value)
                if not sval:
                    return
                if sval not in candidates:
                    candidates.append(sval)

            _add_candidate(normalized)
            _add_candidate(normalized.lstrip('/'))
            _add_candidate(normalized.lstrip('./'))
            try:
                path_obj = Path(ref_str)
                _add_candidate(path_obj.as_posix())
                if path_obj.is_absolute():
                    _add_candidate(path_obj.name)
                    # Try to match by suffix against stored keys
                    suffix = path_obj.as_posix().lstrip('/')
                    _add_candidate(suffix)
            except Exception:
                pass

            for cand in candidates:
                matches = mapping.get(cand)
                if matches:
                    ids = [str(x) for x in matches if x]
                    if ids:
                        break

            if not ids:
                # Fall back to suffix matching if direct lookup failed
                for stored_key, stored_ids in mapping.items():
                    if not stored_key:
                        continue
                    try:
                        key_str = str(stored_key)
                    except Exception:
                        continue
                    key_norm = key_str.replace('\\', '/')
                    if normalized.endswith(key_norm) or key_norm.endswith(normalized):
                        if stored_ids:
                            ids = [str(x) for x in stored_ids if x]
                            if ids:
                                break

        if not ids and ref_str in getattr(self.coverage, 'known_card_ids', set()):
            ids = [ref_str]

        if ids:
            for cid in ids:
                self.coverage.add_card(cid)
        else:
            # Fall back to recording the reference string
            self.coverage.add_card(ref_str)

    def track_card_visit(self, card_path: str | Path):
        """Track that a code card was analyzed."""
        with self.lock:
            self._record_card_visit(card_path)
            self._save()
    
    def track_nodes_batch(self, node_ids: list[str]):
        """Track multiple nodes visited at once."""
        with self.lock:
            for node_id in node_ids:
                self.coverage.add_node(node_id)
            self._save()
    
    def track_cards_batch(self, card_paths: list[str | Path]):
        """Track multiple cards analyzed at once."""
        with self.lock:
            for card_path in card_paths:
                self._record_card_visit(card_path)
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
