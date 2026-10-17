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


def enforce_storage_budget(logs, max_percent, total_storage_bytes):
    """Keeps the combined file size of `logs` under max_percent of
    total_storage_bytes by trimming the oldest entries from the largest
    log(s) first, so a chatty log can't crowd out flash space needed for
    everything else on the device."""
    budget_bytes = total_storage_bytes * max_percent / 100
    overshoot = sum(log.file_size() for log in logs) - budget_bytes
    if overshoot <= 0:
        return
    for log in sorted(logs, key=lambda l: l.file_size(), reverse=True):
        if overshoot <= 0:
            break
        overshoot -= log.trim_oldest_to_free(overshoot)
