"""JSON-file review store — deliberately simple and fully decoupled from the
main backend's MongoDB. Survives restarts, fine for demo/hackathon scale."""

import json
import threading

from .config import get_settings
from .schemas import ReviewItem


class ReviewStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._reviews: dict[str, ReviewItem] = {}
        self.participant_ids: dict[str, str] = {}
        self.processed_run_ids: set[str] = set()
        self._load()

    def _load(self):
        path = get_settings().store_path
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._reviews = {
                r["id"]: ReviewItem.model_validate(r) for r in data.get("reviews", [])
            }
            self.participant_ids = data.get("participant_ids", {})
            self.processed_run_ids = set(data.get("processed_run_ids", []))
        except (json.JSONDecodeError, KeyError, ValueError):
            # Corrupt store — start fresh rather than crash the service.
            self._reviews = {}

    def _save(self):
        path = get_settings().store_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "reviews": [r.model_dump() for r in self._reviews.values()],
                    "participant_ids": self.participant_ids,
                    "processed_run_ids": sorted(self.processed_run_ids),
                },
                indent=2,
            )
        )

    def add(self, item: ReviewItem):
        with self._lock:
            self._reviews[item.id] = item
            self.processed_run_ids.add(item.run_id)
            self._save()

    def get(self, review_id: str) -> ReviewItem | None:
        return self._reviews.get(review_id)

    def update(self, item: ReviewItem):
        with self._lock:
            self._reviews[item.id] = item
            self._save()

    def list(self) -> list[ReviewItem]:
        order = {"needs_attention": 0, "review": 1, "routine": 2}
        return sorted(
            self._reviews.values(),
            key=lambda r: (order[r.priority], r.received_at),
        )

    def has_processed(self, run_id: str) -> bool:
        return run_id in self.processed_run_ids


_store: ReviewStore | None = None


def get_store() -> ReviewStore:
    global _store
    if _store is None:
        _store = ReviewStore()
    return _store
