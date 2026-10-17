import time
import ujson

# Hard cap independent of age, so a crash loop or burst of notifications
# can't grow the file (and the JSON parse/dump cost) without bound.
_MAX_ENTRIES = 200
_DEFAULT_WINDOW_SECONDS = 30 * 24 * 60 * 60  # 30 days


class EventLog:
    """Append-only, persisted log of timestamped events (errors sent
    notifications, ...), capped by count and queryable by age."""

    def __init__(self, path):
        self._path = path
        self._entries = []
        try:
            with open(self._path) as f:
                self._entries = ujson.load(f)
        except (OSError, ValueError):
            self._entries = []

    def record(self, data):
        entry = dict(data)
        entry['timestamp'] = time.time()
        self._entries.append(entry)
        if len(self._entries) > _MAX_ENTRIES:
            self._entries = self._entries[-_MAX_ENTRIES:]
        with open(self._path, 'w') as f:
            ujson.dump(self._entries, f)

    def entries_within(self, seconds=_DEFAULT_WINDOW_SECONDS):
        cutoff = time.time() - seconds
        return [e for e in self._entries if e.get('timestamp', 0) >= cutoff]

    def count_within(self, seconds=_DEFAULT_WINDOW_SECONDS):
        return len(self.entries_within(seconds))
