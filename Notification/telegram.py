import errno
import select
import socket
import time
import ujson
import urequests

from GpioControl.LedControl import led_error_twinkle
from Notification import config as notification_config
from WebServer.errorlog import CATEGORY_EXTERNAL_API, record_exception

_HOST = 'api.telegram.org'
# With the internet down but the WLAN up, urequests blocked the main loop
# for 18 s in connect() (measured on the device - settimeout() is ignored
# there) - beyond the 15 s watchdog, so the board rebooted every ~22 s for
# as long as the outage lasted. A short, time-limited connection test
# first catches that case. urequests itself stays: it is frozen into the
# MicroPython 1.16 firmware (lives in flash), while an own HTTPS client in
# RAM cost enough memory that web pages no longer rendered on this board.
CONNECT_TIMEOUT_MS = 5000
# After a failed send, don't try again for this long - otherwise every
# notification in the same loop iteration would wait out its own timeout.
RETRY_AFTER_FAILURE_MS = 5 * 60 * 1000

_IN_PROGRESS = (errno.EINPROGRESS, getattr(errno, 'EAGAIN', 11))
_address_cache = {}


def check_reachable(host, port=443):
    """Raises OSError unless a TCP connection to host succeeds within
    CONNECT_TIMEOUT_MS."""
    if host not in _address_cache:
        # DNS can't be time-limited on MicroPython, so resolve once and
        # reuse - Telegram's address doesn't change between messages.
        _address_cache[host] = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    try:
        sock.setblocking(False)
        try:
            sock.connect(_address_cache[host])
        except OSError as exc:
            if exc.args[0] not in _IN_PROGRESS:
                raise
        poller = select.poll()
        poller.register(sock, select.POLLOUT | select.POLLERR | select.POLLHUP)
        events = poller.poll(CONNECT_TIMEOUT_MS)
        if not events or events[0][1] & (select.POLLERR | select.POLLHUP):
            raise OSError('Telegram: keine Verbindung innerhalb von {} s'.format(CONNECT_TIMEOUT_MS // 1000))
    except OSError:
        _address_cache.pop(host, None)  # maybe the address changed, resolve again next time
        raise
    finally:
        sock.close()


class Telegram:
    def __init__(self, project_name="--not set--", morning_hour_message=8 - 2, afternoon_hour_message=16 - 2,
                 error_log=None, notification_log=None, logging_settings=None):
        self._project_name = project_name
        self._morning_message = morning_hour_message
        self._afternoon_message = afternoon_hour_message
        self._error_log = error_log
        self._notification_log = notification_log
        self._logging_settings = logging_settings
        self._retry_at = None

    def set_project_name(self, project_name):
        self._project_name = project_name

    def notify(self, message):
        """Returns True if the message was handed to Telegram."""
        if message == None:
            message = "-- no message --"
        now = time.ticks_ms()
        if self._retry_at is not None and time.ticks_diff(now, self._retry_at) < 0:
            return False

        url = 'https://' + _HOST + '/bot' + notification_config.BOT_TOKEN + '/sendMessage'
        payload = {'chat_id': '-' + notification_config.CHAT_ID, 'text': message}
        # urequests' json= kwarg sizes Content-Length by character count, not
        # UTF-8 byte count, which truncates the request body (and silently
        # drops chat_id) whenever the text contains multi-byte characters
        # like "°". Encoding to bytes ourselves avoids that miscalculation.
        body = ujson.dumps(payload).encode('utf-8')
        try:
            check_reachable(_HOST)
            res = urequests.post(url, data=body, headers={'Content-Type': 'application/json'})
            status = res.status_code
            res.close()
            if status != 200:
                raise OSError('Telegram HTTP {}'.format(status))
            print("Telegram OK")
            if self._notification_log is not None:
                self._notification_log.record({})
            self._retry_at = None
            return True
        except Exception as ow_exc:
            print("Telegram notify failed:", ow_exc)
            record_exception(self._error_log, CATEGORY_EXTERNAL_API, ow_exc, logging_settings=self._logging_settings)
            led_error_twinkle(22, 23, 100, 5)
            self._retry_at = time.ticks_add(now, RETRY_AFTER_FAILURE_MS)
            return False

    def send_aquarium_notification(self, ambient_temperature, water_temperature, first_run, message_send_counter):
        message = self._project_name + " - Wassertemperatur: " + str(
            water_temperature) + "°C, Umgebungstemperatur " + str(
            ambient_temperature) + "°C"

        hour = time.gmtime()[3]
        if first_run:
            message = "Neustart - " + message
            self.notify(message)
            # Fallback, if the first run is after the morning_hour_message
            # if the message_send_counter is not updated, _is_allowed_to_send_notification fails
            if self._morning_message < hour <= self._afternoon_message:
                message_send_counter = message_send_counter + 1
            return message_send_counter

        if self._is_allowed_to_send_notification(hour, message_send_counter):
            self.notify(message)
            message_send_counter = message_send_counter + 1

        if message_send_counter > 1:
            message_send_counter = 0

        return message_send_counter

    def _is_allowed_to_send_notification(self, hour, message_send_counter):
        return ((hour == self._morning_message and message_send_counter == 0) or (
                hour == self._afternoon_message and message_send_counter == 1))
