CATEGORY_SYSTEM = 'system'
CATEGORY_HARDWARE = 'hardware'
CATEGORY_NETWORK = 'network'
CATEGORY_EXTERNAL_API = 'external_api'

CATEGORY_LABELS = {
    CATEGORY_SYSTEM: 'System',
    CATEGORY_HARDWARE: 'Hardware',
    CATEGORY_NETWORK: 'Netzwerk',
    CATEGORY_EXTERNAL_API: 'Externe APIs',
}


def record_exception(error_log, category, exc):
    """Records an exception with its type name as the error code, e.g.
    "OSError: [Errno 2] ENOENT" - a meaningful code without inventing a
    separate numbering scheme. No-op if error_log is None, so passing it
    is entirely optional for every caller."""
    if error_log is None:
        return
    error_log.record({
        'category': category,
        'code': type(exc).__name__,
        'message': str(exc)[:200],
    })
