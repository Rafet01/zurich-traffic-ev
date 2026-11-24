"""Generate the public holidays of the canton of Zurich as a dbt seed (2012-2030).

Full-day holidays only. The City of Zurich's half-day holidays (Sechseläuten, Knabenschiessen)
are not included: offices close in the afternoon only.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def zurich_holidays(year: int) -> list[tuple[date, str]]:
    easter = easter_sunday(year)
    return sorted(
        [
            (date(year, 1, 1), "Neujahrstag"),
            (date(year, 1, 2), "Berchtoldstag"),
            (easter - timedelta(days=2), "Karfreitag"),
            (easter + timedelta(days=1), "Ostermontag"),
            (date(year, 5, 1), "Tag der Arbeit"),
            (easter + timedelta(days=39), "Auffahrt"),
            (easter + timedelta(days=50), "Pfingstmontag"),
            (date(year, 8, 1), "Bundesfeier"),
            (date(year, 12, 25), "Weihnachtstag"),
            (date(year, 12, 26), "Stephanstag"),
        ]
    )


def main(out: str = "transform/seeds/zurich_public_holidays.csv") -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["holiday_date", "holiday_name"])
        for year in range(2012, 2031):
            for d, name in zurich_holidays(year):
                w.writerow([d.isoformat(), name])


if __name__ == "__main__":
    main(*sys.argv[1:])
