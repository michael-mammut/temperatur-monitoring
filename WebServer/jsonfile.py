import ujson


def load_dict(path):
    """The JSON object stored in `path`, or None if the file is missing,
    corrupt or holds something else than an object (e.g. `null`).

    Every settings class loads its file at boot. A file half-written when
    the power failed - wifi_settings.json is saved right before the reboot
    that applies new WLAN credentials - used to raise from the constructor
    and stop the boot before WLAN or web server came up, fixable only via
    USB. Callers keep their defaults on None instead."""
    try:
        with open(path) as f:
            data = ujson.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
