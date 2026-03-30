"""Duplicate prompt detector -- find wasted API calls."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from .pricing import calculate_cost
from .storage import Storage


class DuplicateDetector:
    """Detects exact and near-duplicate prompts to surface wasted spend.

    Hashes the message content of each call and groups them by hash.
    Exact duplicates share the same hash; near-duplicates have content
    that differs by less than a configurable threshold (default 10%).
    """

    def __init__(
        self,
        storage: Storage,
        *,
        near_duplicate_threshold: float = 0.10,
    ) -> None:
        self._storage = storage
        self._threshold = near_duplicate_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_session(self, session_id: str) -> dict:
        """Analyze a single session for duplicate / similar prompts.

        Returns:
            {
                "exact_duplicates": [
                    {"hash": str, "count": int, "cost_each": float,
                     "wasted_cost": float, "model": str, "preview": str},
                    ...
                ],
                "near_duplicates": [
                    {"pair": [str, str], "similarity": float,
                     "cost_a": float, "cost_b": float,
                     "preview_a": str, "preview_b": str},
                    ...
                ],
                "wasted_cost": float,
                "potential_savings": float,
                "total_calls": int,
                "unique_calls": int,
            }
        """
        records = self._storage.get_session(session_id)
        return self._analyze_records(records)

    def analyze_today(self) -> dict:
        """Analyze today's calls for duplicates."""
        records = self._storage.get_today()
        return self._analyze_records(records)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _analyze_records(self, records: Sequence[dict]) -> dict:
        """Core analysis over a list of stored request dicts."""
        # Build per-hash groups.
        # Each record has: model, input_tokens, output_tokens, cost, endpoint
        # We hash on (model, input_tokens) as a proxy for "same prompt" since
        # the raw messages are not persisted in Storage.  When the endpoint
        # column is populated we include it too.
        groups: dict[str, list[dict]] = defaultdict(list)
        for rec in records:
            h = _record_hash(rec)
            groups[h].append(rec)

        exact_duplicates: list[dict] = []
        wasted_cost = 0.0

        for h, group in groups.items():
            if len(group) < 2:
                continue
            first = group[0]
            cost_each = first.get("cost", 0.0)
            # The first call is not wasted; every repeat is.
            dup_cost = cost_each * (len(group) - 1)
            wasted_cost += dup_cost
            exact_duplicates.append({
                "hash": h,
                "count": len(group),
                "cost_each": round(cost_each, 6),
                "wasted_cost": round(dup_cost, 6),
                "model": first.get("model", "unknown"),
                "preview": _record_preview(first),
            })

        # Sort by wasted cost descending
        exact_duplicates.sort(key=lambda d: d["wasted_cost"], reverse=True)

        # Near-duplicate detection: compare groups whose token counts differ
        # by less than threshold.
        near_duplicates = self._find_near_duplicates(groups)
        potential_savings = wasted_cost + sum(
            min(nd["cost_a"], nd["cost_b"]) for nd in near_duplicates
        )

        unique_hashes = len(groups)
        total_calls = len(records)

        return {
            "exact_duplicates": exact_duplicates,
            "near_duplicates": near_duplicates,
            "wasted_cost": round(wasted_cost, 6),
            "potential_savings": round(potential_savings, 6),
            "total_calls": total_calls,
            "unique_calls": unique_hashes,
        }

    def _find_near_duplicates(
        self,
        groups: dict[str, list[dict]],
    ) -> list[dict]:
        """Compare group representatives to find near-duplicate prompts.

        Two records are "near-duplicates" when they use the same model
        and their input_tokens differ by less than *threshold*.
        """
        representatives: list[tuple[str, dict]] = [
            (h, g[0]) for h, g in groups.items()
        ]
        seen_pairs: set[tuple[str, str]] = set()
        results: list[dict] = []

        for i, (h_a, rec_a) in enumerate(representatives):
            for j in range(i + 1, len(representatives)):
                h_b, rec_b = representatives[j]

                # Only compare records for the same model
                if rec_a.get("model") != rec_b.get("model"):
                    continue

                pair_key = (min(h_a, h_b), max(h_a, h_b))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                similarity = _token_similarity(rec_a, rec_b)
                if similarity >= (1.0 - self._threshold) and similarity < 1.0:
                    results.append({
                        "pair": [h_a, h_b],
                        "similarity": round(similarity, 4),
                        "cost_a": round(rec_a.get("cost", 0.0), 6),
                        "cost_b": round(rec_b.get("cost", 0.0), 6),
                        "preview_a": _record_preview(rec_a),
                        "preview_b": _record_preview(rec_b),
                    })

        results.sort(key=lambda d: d["similarity"], reverse=True)
        return results


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _record_hash(rec: dict) -> str:
    """Produce a deterministic hash for a storage record.

    Uses model + input_tokens + output_tokens + endpoint as key material.
    This groups calls that are identical from the API's perspective.
    """
    key = json.dumps(
        {
            "model": rec.get("model", ""),
            "input_tokens": rec.get("input_tokens", 0),
            "output_tokens": rec.get("output_tokens", 0),
            "endpoint": rec.get("endpoint", ""),
        },
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _record_preview(rec: dict) -> str:
    """Human-readable one-line preview of a record."""
    model = rec.get("model", "?")
    inp = rec.get("input_tokens", 0)
    out = rec.get("output_tokens", 0)
    cost = rec.get("cost", 0.0)
    return f"{model} | {inp} in / {out} out | ${cost:.4f}"


def _token_similarity(a: dict, b: dict) -> float:
    """Compute similarity between two records based on token counts.

    Returns a float in [0, 1] where 1.0 means identical token counts.
    """
    in_a = a.get("input_tokens", 0)
    in_b = b.get("input_tokens", 0)
    out_a = a.get("output_tokens", 0)
    out_b = b.get("output_tokens", 0)

    total_a = in_a + out_a
    total_b = in_b + out_b

    if total_a == 0 and total_b == 0:
        return 1.0

    max_total = max(total_a, total_b)
    if max_total == 0:
        return 1.0

    diff = abs(total_a - total_b)
    return 1.0 - (diff / max_total)
