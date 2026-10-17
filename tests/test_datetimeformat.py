import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.datetimeformat import CULTURES, UTC_OFFSETS, VALID_OFFSET_MINUTES, format_datetime

# 2026-10-17 06:05:09 UTC - chosen so day/month/hour are all unambiguous
# (two different values each), which would catch a day/month mix-up.
_SAMPLE = (2026, 10, 17, 6, 5, 9)


class FormatDatetimeTests(unittest.TestCase):
    def test_iso_is_year_month_day_24h(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso'), "2026-10-17 06:05:09 UTC")

    def test_unknown_culture_falls_back_to_iso(self):
        self.assertEqual(format_datetime(_SAMPLE, 'xx_XX'), format_datetime(_SAMPLE, 'iso'))

    def test_austria_is_day_month_year_24h(self):
        self.assertEqual(format_datetime(_SAMPLE, 'de_AT'), "17.10.2026 06:05:09 UTC")

    def test_germany_matches_austria(self):
        self.assertEqual(format_datetime(_SAMPLE, 'de_DE'), format_datetime(_SAMPLE, 'de_AT'))

    def test_uk_is_day_month_year_24h_with_slashes(self):
        self.assertEqual(format_datetime(_SAMPLE, 'en_GB'), "17/10/2026 06:05:09 UTC")

    def test_canada_east_asia_style_is_year_month_day_with_slashes(self):
        self.assertEqual(format_datetime(_SAMPLE, 'en_CA'), "2026/10/17 06:05:09 UTC")

    def test_denmark_is_day_month_year_with_dashes(self):
        self.assertEqual(format_datetime(_SAMPLE, 'da_DK'), "17-10-2026 06:05:09 UTC")

    def test_us_is_month_day_year_12h_with_am_pm(self):
        self.assertEqual(format_datetime(_SAMPLE, 'en_US'), "10/17/2026 06:05:09 AM UTC")

    def test_us_midnight_is_displayed_as_12_am_not_00(self):
        midnight = (2026, 1, 1, 0, 30, 0)
        self.assertEqual(format_datetime(midnight, 'en_US'), "01/01/2026 12:30:00 AM UTC")

    def test_us_noon_is_displayed_as_12_pm_not_00(self):
        noon = (2026, 1, 1, 12, 30, 0)
        self.assertEqual(format_datetime(noon, 'en_US'), "01/01/2026 12:30:00 PM UTC")

    def test_us_afternoon_wraps_correctly(self):
        afternoon = (2026, 1, 1, 13, 0, 0)
        self.assertEqual(format_datetime(afternoon, 'en_US'), "01/01/2026 01:00:00 PM UTC")

    def test_default_culture_is_iso(self):
        self.assertEqual(format_datetime(_SAMPLE), format_datetime(_SAMPLE, 'iso'))

    def test_every_offered_culture_actually_formats_without_error(self):
        for code in CULTURES:
            result = format_datetime(_SAMPLE, code)
            self.assertIn("2026", result)
            self.assertIn("UTC", result)

    # -- UTC offset: shifting the clock -----------------------------------

    def test_zero_offset_is_unchanged_and_labelled_plain_utc(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso', 0), "2026-10-17 06:05:09 UTC")

    def test_positive_offset_within_the_same_day(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso', 60), "2026-10-17 07:05:09 UTC+01")

    def test_negative_offset_within_the_same_day(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso', -300), "2026-10-17 01:05:09 UTC-05")

    def test_positive_offset_rolls_over_into_the_next_day(self):
        late_evening = (2026, 10, 17, 23, 30, 0)
        self.assertEqual(format_datetime(late_evening, 'iso', 60), "2026-10-18 00:30:00 UTC+01")

    def test_negative_offset_rolls_back_into_the_previous_day(self):
        early_morning = (2026, 10, 17, 0, 30, 0)
        self.assertEqual(format_datetime(early_morning, 'iso', -60), "2026-10-16 23:30:00 UTC-01")

    def test_offset_rolls_over_a_month_and_year_boundary(self):
        new_years_eve = (2025, 12, 31, 23, 0, 0)
        self.assertEqual(format_datetime(new_years_eve, 'iso', 120), "2026-01-01 01:00:00 UTC+02")

    def test_offset_rolls_back_over_a_leap_day(self):
        # 2024 is a leap year - this must land on 2024-02-29, not 2024-03-01.
        just_after_midnight = (2024, 3, 1, 0, 30, 0)
        self.assertEqual(format_datetime(just_after_midnight, 'iso', -60), "2024-02-29 23:30:00 UTC-01")

    def test_half_hour_offset_label(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso', 330), "2026-10-17 11:35:09 UTC+05:30")

    def test_quarter_hour_offset_label(self):
        self.assertEqual(format_datetime(_SAMPLE, 'iso', 345), "2026-10-17 11:50:09 UTC+05:45")

    def test_offset_is_applied_before_culture_specific_formatting(self):
        # en_US (12h) should see the shifted hour, not the original one.
        just_before_midnight = (2026, 10, 17, 23, 0, 0)
        self.assertEqual(format_datetime(just_before_midnight, 'en_US', 120), "10/18/2026 01:00:00 AM UTC+02")

    def test_every_offered_offset_actually_formats_without_error(self):
        for minutes, _label in UTC_OFFSETS:
            result = format_datetime(_SAMPLE, 'iso', minutes)
            self.assertIn("2026", result)
            self.assertIn("UTC", result)

    def test_valid_offset_minutes_matches_the_offered_offsets(self):
        self.assertEqual(VALID_OFFSET_MINUTES, tuple(minutes for minutes, _label in UTC_OFFSETS))

    # -- EU summer time (DST) -----------------------------------------------
    # Ground truth (independently verified with Python's stdlib datetime,
    # not with this module's own calendar math): last Sunday of March /
    # October, at 01:00 UTC, is when the whole EU switches at once.
    #   2024: 2024-03-31 / 2024-10-27 (leap year)
    #   2026: 2026-03-29 / 2026-10-25

    def test_disabled_by_default_even_in_summer(self):
        midsummer = (2026, 7, 1, 12, 0, 0)
        self.assertEqual(format_datetime(midsummer, 'iso', 60), "2026-07-01 13:00:00 UTC+01")

    def test_eu_summer_time_true_in_midsummer(self):
        midsummer = (2026, 7, 1, 12, 0, 0)
        self.assertEqual(format_datetime(midsummer, 'iso', 60, eu_summer_time=True),
                          "2026-07-01 14:00:00 UTC+02")

    def test_eu_summer_time_false_in_midwinter(self):
        midwinter = (2026, 1, 1, 12, 0, 0)
        self.assertEqual(format_datetime(midwinter, 'iso', 60, eu_summer_time=True),
                          "2026-01-01 13:00:00 UTC+01")

    def test_spring_transition_instant_2026(self):
        just_before = (2026, 3, 29, 0, 59, 59)
        at_transition = (2026, 3, 29, 1, 0, 0)
        self.assertEqual(format_datetime(just_before, 'iso', 60, eu_summer_time=True),
                          "2026-03-29 01:59:59 UTC+01")
        self.assertEqual(format_datetime(at_transition, 'iso', 60, eu_summer_time=True),
                          "2026-03-29 03:00:00 UTC+02")

    def test_autumn_transition_instant_2026(self):
        just_before = (2026, 10, 25, 0, 59, 59)
        at_transition = (2026, 10, 25, 1, 0, 0)
        self.assertEqual(format_datetime(just_before, 'iso', 60, eu_summer_time=True),
                          "2026-10-25 02:59:59 UTC+02")
        self.assertEqual(format_datetime(at_transition, 'iso', 60, eu_summer_time=True),
                          "2026-10-25 02:00:00 UTC+01")

    def test_spring_transition_instant_2024_leap_year(self):
        just_before = (2024, 3, 31, 0, 59, 59)
        at_transition = (2024, 3, 31, 1, 0, 0)
        self.assertEqual(format_datetime(just_before, 'iso', 60, eu_summer_time=True),
                          "2024-03-31 01:59:59 UTC+01")
        self.assertEqual(format_datetime(at_transition, 'iso', 60, eu_summer_time=True),
                          "2024-03-31 03:00:00 UTC+02")

    def test_autumn_transition_instant_2024_leap_year(self):
        just_before = (2024, 10, 27, 0, 59, 59)
        at_transition = (2024, 10, 27, 1, 0, 0)
        self.assertEqual(format_datetime(just_before, 'iso', 60, eu_summer_time=True),
                          "2024-10-27 02:59:59 UTC+02")
        self.assertEqual(format_datetime(at_transition, 'iso', 60, eu_summer_time=True),
                          "2024-10-27 02:00:00 UTC+01")

    def test_eu_summer_time_combines_with_day_rollover(self):
        # 23:30 UTC + (60 base + 60 DST) = 2h -> rolls into the next day.
        late_evening = (2026, 7, 1, 23, 30, 0)
        self.assertEqual(format_datetime(late_evening, 'iso', 60, eu_summer_time=True),
                          "2026-07-02 01:30:00 UTC+02")

    def test_eu_summer_time_applies_regardless_of_base_offset(self):
        # Athens (UTC+02:00 base) is also EU and in the same summer-time
        # window, becoming UTC+03 in summer.
        midsummer = (2026, 7, 1, 12, 0, 0)
        self.assertEqual(format_datetime(midsummer, 'iso', 120, eu_summer_time=True),
                          "2026-07-01 15:00:00 UTC+03")


if __name__ == "__main__":
    unittest.main()
