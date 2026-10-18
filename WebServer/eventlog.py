import os
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

    def record(self, data, merge_within_seconds=None):
        """With merge_within_seconds, an identical entry (same fields)
        first recorded less than that long ago is not added again - its
        'count' goes up and 'last' holds the latest occurrence instead.
        Keeps a permanently failing sensor from filling the whole log
        (200 entries = ~24 KB of RAM on the ESP32) with copies of itself,
        while 'timestamp' stays the first occurrence, so a persisting
        error still gets a fresh entry once per window."""
        now = time.time()
        if merge_within_seconds is not None:
            existing = self._find_recent(data, now - merge_within_seconds)
            if existing is not None:
                existing['count'] = existing.get('count', 1) + 1
                existing['last'] = now
                self._save()
                return
        entry = dict(data)
        entry['timestamp'] = now
        self._entries.append(entry)
        if len(self._entries) > _MAX_ENTRIES:
            self._entries = self._entries[-_MAX_ENTRIES:]
        self._save()

    def _find_recent(self, data, cutoff):
        for entry in reversed(self._entries):
            if entry.get('timestamp', 0) <= cutoff:
                return None  # entries are chronological, the rest is older
            if all(entry.get(key) == value for key, value in data.items()):
                return entry
        return None

    def stream_to(self, send, chunk_size=512):
        """Sends the raw JSON file in small chunks via send(bytes), never
        holding the whole file in RAM at once - a full log is ~17 KB, far
        more than the ESP32 can reliably allocate in one piece."""
        try:
            f = open(self._path, 'rb')
        except OSError:
            send(b'[]')  # nothing recorded yet
            return
        try:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                send(chunk)
        finally:
            f.close()

    def _save(self):
        with open(self._path, 'w') as f:
            ujson.dump(self._entries, f)

    def entries_within(self, seconds=_DEFAULT_WINDOW_SECONDS):
        cutoff = time.time() - seconds
        return [e for e in self._entries if e.get('timestamp', 0) >= cutoff]

    def count_within(self, seconds=_DEFAULT_WINDOW_SECONDS):
        return sum(e.get('count', 1) for e in self.entries_within(seconds))

    def file_size(self):
        try:
            return os.stat(self._path)[6]
        except OSError:
            return 0

    def delete_older_than(self, seconds):
        """Removes every entry older than `seconds` ago. Returns how many
        entries were removed. Used by the manual "Logs bereinigen" button
        on /statistics."""
        cutoff = time.time() - seconds
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get('timestamp', 0) >= cutoff]
        removed = before - len(self._entries)
        if removed:
            with open(self._path, 'w') as f:
                ujson.dump(self._entries, f)
        return removed

    def trim_oldest_to_free(self, target_bytes):
        """Removes the oldest entries until roughly `target_bytes` have
        been freed, estimated from the average entry size. Returns the
        actual number of bytes freed (measured, not estimated) so callers
        enforcing a shared budget across several logs know how much more
        they still need from elsewhere."""
        if not self._entries or target_bytes <= 0:
            return 0
        size_before = self.file_size()
        if size_before <= 0:
            return 0
        avg_entry_size = size_before / len(self._entries)
        entries_to_remove = min(len(self._entries), max(1, int(target_bytes / avg_entry_size) + 1))
        self._entries = self._entries[entries_to_remove:]
        with open(self._path, 'w') as f:
            ujson.dump(self._entries, f)
        return size_before - self.file_size()


def enforce_storage_budget(logs, max_percent, free_bytes):
    """Keeps the combined file size of `logs` under max_percent of the
    space that isn't already committed to other (non-log) data, so the
    logs can't be the reason the flash fills up completely.

    The budget is deliberately based on *headroom* (currently free space
    plus what the logs themselves already occupy), not on total flash
    capacity: a fixed share of total capacity stays the same size no
    matter how much room non-log data actually leaves, so if that grows
    the logs could still be "within budget" while there's barely any
    free space left at all. Tying the budget to current headroom instead
    means at least (100 - max_percent)% of it always stays genuinely
    free, and the allowed log footprint automatically shrinks as free
    space shrinks for any other reason."""
    current_log_bytes = sum(log.file_size() for log in logs)
    headroom = free_bytes + current_log_bytes
    budget_bytes = headroom * max_percent / 100
    overshoot = current_log_bytes - budget_bytes
    if overshoot <= 0:
        return
    for log in sorted(logs, key=lambda l: l.file_size(), reverse=True):
        if overshoot <= 0:
            break
        overshoot -= log.trim_oldest_to_free(overshoot)
