CATEGORY_SYSTEM = 'system'
CATEGORY_HARDWARE = 'hardware'
CATEGORY_NETWORK = 'network'
CATEGORY_EXTERNAL_API = 'external_api'

# The same error (category + code + message) recurring within this window
# is merged into one log entry with a counter instead of a new entry each.
MERGE_WINDOW_SECONDS = 12 * 60 * 60

ALL_CATEGORIES = (CATEGORY_SYSTEM, CATEGORY_HARDWARE, CATEGORY_NETWORK, CATEGORY_EXTERNAL_API)

CATEGORY_LABELS = {
    CATEGORY_SYSTEM: 'System',
    CATEGORY_HARDWARE: 'Hardware',
    CATEGORY_NETWORK: 'Netzwerk',
    CATEGORY_EXTERNAL_API: 'Externe APIs',
}


def record_exception(error_log, category, exc, logging_settings=None):
    """Records an exception with its type name as the error code, e.g.
    "OSError: [Errno 2] ENOENT" - a meaningful code without inventing a
    separate numbering scheme. No-op if error_log is None, so passing it
    is entirely optional for every caller. Also a no-op if logging for
    this category has been switched off via /settings."""
    if error_log is None:
        return
    if logging_settings is not None and not logging_settings.is_enabled(category):
        return
    error_log.record({
        'category': category,
        'code': type(exc).__name__,
        'message': str(exc)[:200],
    }, merge_within_seconds=MERGE_WINDOW_SECONDS)
