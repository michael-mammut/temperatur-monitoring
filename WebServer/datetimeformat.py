DEFAULT_CULTURE = 'iso'
DEFAULT_UTC_OFFSET_MINUTES = 0

# Country/culture presets for how date & time are displayed throughout the
# web interface. This device has no IANA timezone database (no room for one
# on the ESP32's flash, and no mechanism to keep DST rules up to date), so
# only the *display* format (date order, separators, 12h/24h) changes with
# the chosen culture - the timezone/offset is a separate, simpler setting
# below.
CULTURES = {
    'iso': 'ISO 8601 (JJJJ-MM-TT, 24h)',
    'de_AT': u'Österreich (TT.MM.JJJJ, 24h)',
    'de_DE': u'Deutschland (TT.MM.JJJJ, 24h)',
    'en_US': 'USA (MM/TT/JJJJ, 12h)',
    'en_GB': u'Vereinigtes Königreich (TT/MM/JJJJ, 24h)',
    'en_CA': u'Kanada/Ostasien (JJJJ/MM/TT, 24h)',
    'da_DK': u'Dänemark/Skandinavien (TT-MM-JJJJ, 24h)',
}

# Fixed UTC offsets to pick a timezone by - deliberately *not* a full
# IANA tz database with per-country DST rules (far too large for the
# ESP32's flash, and nothing on this device can keep DST rules current).
# A fixed offset is what small IoT devices (Shelly, Tasmota, ...) use for
# the same reason; picking a representative city just helps find the
# right one, it doesn't track that city's actual DST transitions.
UTC_OFFSETS = (
    (-720, 'UTC-12:00'),
    (-660, 'UTC-11:00 (Midway, Samoa)'),
    (-600, 'UTC-10:00 (Honolulu)'),
    (-570, u'UTC-09:30 (Marquesas-Inseln)'),
    (-540, 'UTC-09:00 (Anchorage)'),
    (-480, 'UTC-08:00 (Los Angeles, Vancouver)'),
    (-420, 'UTC-07:00 (Denver, Phoenix)'),
    (-360, u'UTC-06:00 (Chicago, Mexiko-Stadt)'),
    (-300, 'UTC-05:00 (New York, Toronto)'),
    (-240, 'UTC-04:00 (Santiago, Caracas)'),
    (-210, u"UTC-03:30 (St. John's)"),
    (-180, u'UTC-03:00 (Buenos Aires, São Paulo)'),
    (-120, u'UTC-02:00 (Südgeorgien)'),
    (-60, 'UTC-01:00 (Azoren)'),
    (0, 'UTC+00:00 (London, Lissabon, Reykjavik)'),
    (60, 'UTC+01:00 (Wien, Berlin, Paris, Rom)'),
    (120, u'UTC+02:00 (Athen, Kairo, Helsinki)'),
    (180, 'UTC+03:00 (Moskau, Istanbul, Nairobi)'),
    (210, 'UTC+03:30 (Teheran)'),
    (240, 'UTC+04:00 (Dubai, Baku)'),
    (270, 'UTC+04:30 (Kabul)'),
    (300, u'UTC+05:00 (Islamabad, Taschkent)'),
    (330, 'UTC+05:30 (Neu-Delhi, Colombo)'),
    (345, 'UTC+05:45 (Kathmandu)'),
    (360, 'UTC+06:00 (Dhaka, Almaty)'),
    (390, 'UTC+06:30 (Yangon)'),
    (420, 'UTC+07:00 (Bangkok, Jakarta)'),
    (480, 'UTC+08:00 (Peking, Singapur, Perth)'),
    (525, 'UTC+08:45 (Eucla)'),
    (540, 'UTC+09:00 (Tokio, Seoul)'),
    (570, 'UTC+09:30 (Adelaide, Darwin)'),
    (600, 'UTC+10:00 (Sydney, Brisbane)'),
    (630, 'UTC+10:30 (Lord-Howe-Insel)'),
    (660, u'UTC+11:00 (Nouméa)'),
    (720, 'UTC+12:00 (Auckland, Suva)'),
    (765, 'UTC+12:45 (Chatham-Inseln)'),
    (780, u'UTC+13:00 (Nukuʻalofa)'),
    (840, 'UTC+14:00 (Kiritimati)'),
)

VALID_OFFSET_MINUTES = tuple(minutes for minutes, _ in UTC_OFFSETS)


def _days_from_civil(year, month, day):
    # Howard Hinnant's days-from-civil algorithm (proleptic Gregorian
    # calendar, correct for the full int range) - used instead of
    # time.mktime() because that treats the tuple as *local* time on
    # CPython (varies with the host's timezone) but has no timezone
    # concept at all on MicroPython, so the two platforms would disagree.
    # This is pure integer arithmetic, so it behaves identically on both.
    y = year - 1 if month <= 2 else year
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = (month + 9) % 12
    doy = (153 * mp + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return (year + (1 if month <= 2 else 0), month, day)


def _apply_utc_offset(time_tuple, utc_offset_minutes):
    year, month, day, hour, minute, second = time_tuple[0:6]
    if not utc_offset_minutes:
        return (year, month, day, hour, minute, second)
    total_seconds = hour * 3600 + minute * 60 + second + utc_offset_minutes * 60
    day_delta, remaining = divmod(total_seconds, 86400)
    new_hour, rem = divmod(remaining, 3600)
    new_minute, new_second = divmod(rem, 60)
    new_year, new_month, new_day = _civil_from_days(_days_from_civil(year, month, day) + day_delta)
    return (new_year, new_month, new_day, new_hour, new_minute, new_second)


def _offset_suffix(utc_offset_minutes):
    if not utc_offset_minutes:
        return "UTC"
    sign = '+' if utc_offset_minutes > 0 else '-'
    hours, minutes = divmod(abs(utc_offset_minutes), 60)
    if minutes:
        return "UTC{}{:02d}:{:02d}".format(sign, hours, minutes)
    return "UTC{}{:02d}".format(sign, hours)


def format_datetime(time_tuple, culture=DEFAULT_CULTURE, utc_offset_minutes=DEFAULT_UTC_OFFSET_MINUTES):
    """Formats a (year, month, day, hour, minute, second, ...) tuple -
    e.g. straight from time.gmtime(), which is always UTC on this device
    - shifted by the given fixed UTC offset and written out in the
    date/time convention of the given country/culture. Falls back to
    ISO 8601 / UTC for an unknown culture/offset, so a stale/invalid
    stored value never breaks rendering."""
    year, month, day, hour, minute, second = _apply_utc_offset(time_tuple, utc_offset_minutes)

    if culture in ('de_AT', 'de_DE'):
        date_part = "{:02d}.{:02d}.{:04d}".format(day, month, year)
        time_part = "{:02d}:{:02d}:{:02d}".format(hour, minute, second)
    elif culture == 'en_US':
        date_part = "{:02d}/{:02d}/{:04d}".format(month, day, year)
        hour12 = hour % 12 or 12
        am_pm = 'AM' if hour < 12 else 'PM'
        time_part = "{:02d}:{:02d}:{:02d} {}".format(hour12, minute, second, am_pm)
    elif culture == 'en_GB':
        date_part = "{:02d}/{:02d}/{:04d}".format(day, month, year)
        time_part = "{:02d}:{:02d}:{:02d}".format(hour, minute, second)
    elif culture == 'en_CA':
        date_part = "{:04d}/{:02d}/{:02d}".format(year, month, day)
        time_part = "{:02d}:{:02d}:{:02d}".format(hour, minute, second)
    elif culture == 'da_DK':
        date_part = "{:02d}-{:02d}-{:04d}".format(day, month, year)
        time_part = "{:02d}:{:02d}:{:02d}".format(hour, minute, second)
    else:
        date_part = "{:04d}-{:02d}-{:02d}".format(year, month, day)
        time_part = "{:02d}:{:02d}:{:02d}".format(hour, minute, second)

    return "{} {} {}".format(date_part, time_part, _offset_suffix(utc_offset_minutes))
