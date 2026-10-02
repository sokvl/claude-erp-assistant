from datetime import date, datetime
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Europe/Warsaw")


def today_in_business_timezone() -> date:
    return datetime.now(BUSINESS_TIMEZONE).date()
