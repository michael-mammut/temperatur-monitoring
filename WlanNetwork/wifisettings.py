import ujson

_PATH = 'wifi_settings.json'

# WPA2-PSK passphrases are 8-63 ASCII characters (IEEE 802.11i); an empty
# password is only valid for an open (unencrypted) network.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 63
MAX_SSID_LENGTH = 32  # hard limit from the 802.11 spec


class WifiSettings:
    """Persists WLAN credentials entered via the /wifi-settings page to a
    JSON file on flash, so a change survives a reboot without re-flashing
    WlanNetwork/config.py.

    The credentials are stored in plain text. There is no way around this:
    the device has to present the real WPA2 passphrase over the air to
    authenticate, and MicroPython's network.WLAN.connect() only accepts
    that passphrase, not a pre-derived key - every WiFi client device
    (routers, smart plugs, etc.) stores it the same way for the same
    reason. Treat this file, and WlanNetwork/config.py, as sensitive.
    """

    def __init__(self, default_ssid, default_password):
        self._ssid = default_ssid
        self._password = default_password
        try:
            with open(_PATH) as f:
                data = ujson.load(f)
            self._ssid = data.get('ssid', default_ssid)
            self._password = data.get('password', default_password)
        except OSError:
            pass  # no override file yet, keep the defaults from config.py

    def get_ssid(self):
        return self._ssid

    def get_password(self):
        return self._password

    def set_credentials(self, ssid, password):
        self._ssid = ssid
        self._password = password
        with open(_PATH, 'w') as f:
            ujson.dump({'ssid': ssid, 'password': password}, f)


def validate_ssid(ssid):
    if not ssid:
        return "SSID darf nicht leer sein."
    encoded_len = len(ssid.encode('utf-8'))
    if encoded_len > MAX_SSID_LENGTH:
        return "SSID ist zu lang (max. %d Bytes)." % MAX_SSID_LENGTH
    return None


def validate_password(password):
    if password == '':
        return None  # empty = open network, explicitly allowed
    encoded_len = len(password.encode('utf-8'))
    if encoded_len < MIN_PASSWORD_LENGTH or encoded_len > MAX_PASSWORD_LENGTH:
        return "WLAN-Passwort muss zwischen %d und %d Zeichen lang sein." % (
            MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH)
    return None
