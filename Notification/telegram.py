import ujson
import urequests
import time

from GpioControl.LedControl import led_error_twinkle
from Notification import config as notification_config
from WebServer.errorlog import CATEGORY_EXTERNAL_API, record_exception


class Telegram:
    def __init__(self, project_name="--not set--", morning_hour_message=8 - 2, afternoon_hour_message=16 - 2,
                 error_log=None, notification_log=None, logging_settings=None):
        self._project_name = project_name
        self._morning_message = morning_hour_message
        self._afternoon_message = afternoon_hour_message
        self._error_log = error_log
        self._notification_log = notification_log
        self._logging_settings = logging_settings

    def set_project_name(self, project_name):
        self._project_name = project_name

    def notify(self, message):
        """Returns True if the message was handed to Telegram."""
        if message == None:
            message = "-- no message --"

        url = 'https://api.telegram.org/bot' + notification_config.BOT_TOKEN + '/sendMessage'
        payload = {'chat_id': '-' + notification_config.CHAT_ID, 'text': message}
        # urequests' json= kwarg sizes Content-Length by character count, not
        # UTF-8 byte count, which truncates the request body (and silently
        # drops chat_id) whenever the text contains multi-byte characters
        # like "°". Encoding to bytes ourselves avoids that miscalculation.
        body = ujson.dumps(payload).encode('utf-8')
        res = None
        try:
            res = urequests.post(url, data=body, headers={'Content-Type': 'application/json'})
            print(str(res.json()))
            if self._notification_log is not None:
                self._notification_log.record({})
            return True
        except Exception as ow_exc:
            print("Telegram notify failed:", ow_exc)
            record_exception(self._error_log, CATEGORY_EXTERNAL_API, ow_exc, logging_settings=self._logging_settings)
            led_error_twinkle(22, 23, 100, 5)
            return False
        finally:
            if res is not None:
                res.close()

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
