"""Synthetic source files in the exact layouts of the real ones (no download needed).

  python tests/make_fixtures.py tests/fixtures

Traffic: two yearly CSVs (2025, 2026) with 5 measuring points, four weeks each, covering both DST
switches, Easter holidays, a counting-site outage (Fehlend) and imputed hours.
Vehicle stock: four snapshots in four of the eight real ASTRA header lines (verbatim headers),
including the 2019 typos, the 2022-07 one-digit postcode, a quoted model name and a broken row.
The numbers are invented; only the structure is real.
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ----------------------------------------------------------------------------------------------- traffic

TRAFFIC_HEADER = (
    "MSID,MSName,ZSID,ZSName,Achse,HNr,Hoehe,EKoord,NKoord,Richtung,Knummer,Kname,AnzDetektoren,"
    "D1ID,D2ID,D3ID,D4ID,MessungDatZeit,LieferDat,AnzFahrzeuge,AnzFahrzeugeStatus"
).split(",")

# (MSID, ZSID, site name, street, house no, E, N, direction, base vehicles/hour, outage days)
MEASURING_POINTS = [
    ("Z001M001", "Z001", "Seestrasse (Strandbad Wollishofen)", "Seestrasse", "451", 2683009.89, 1243936.2,
     "auswärts", 420, ()),
    ("Z001M002", "Z001", "Seestrasse (Strandbad Wollishofen)", "Seestrasse", "451", 2683012.40, 1243931.7,
     "einwärts", 450, ()),
    ("Z030M001", "Z030", "Rosengartenstrasse (Wipkingerplatz)", "Rosengartenstrasse", "Unbekannt", 2681766.0,
     1249890.5, "auswärts", 1100, ()),
    ("Z030M002", "Z030", "Rosengartenstrasse (Wipkingerplatz)", "Rosengartenstrasse", "Unbekannt", 2681770.3,
     1249885.1, "einwärts", 1150, ()),
    ("Z045M001", "Z045", "Hardbrücke (Escher-Wyss-Platz)", "Hardbrücke", "Unbekannt", 2681320.7, 1248900.2,
     "Hardplatz", 700, (date(2026, 3, 24), date(2026, 3, 25))),
]  # fmt: skip

HOLIDAYS = {date(2026, 4, 3), date(2026, 4, 6)}  # Good Friday, Easter Monday

# Relative traffic by hour of day (weekday). Inbound peaks in the morning, outbound in the evening.
WEEKDAY = [0.12, 0.07, 0.05, 0.05, 0.09, 0.30, 0.75, 1.00, 0.95, 0.75, 0.70, 0.72,
           0.75, 0.72, 0.75, 0.82, 0.92, 1.00, 0.90, 0.70, 0.50, 0.38, 0.28, 0.18]  # fmt: skip
WEEKEND = [0.20, 0.14, 0.10, 0.08, 0.07, 0.10, 0.18, 0.28, 0.40, 0.55, 0.65, 0.72,
           0.75, 0.72, 0.70, 0.68, 0.66, 0.62, 0.55, 0.45, 0.38, 0.32, 0.26, 0.20]  # fmt: skip


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _hours(day: date) -> list[int]:
    """Local wall-clock hours delivered for one day: 23 in spring (no 02:00), 25 in autumn (02:00 twice)."""
    if day == _last_sunday(day.year, 3):
        return [h for h in range(24) if h != 2]
    if day == _last_sunday(day.year, 10):
        return [0, 1, 2, 2] + list(range(3, 24))
    return list(range(24))


def _volume(mp, day: date, hour: int, rnd: random.Random) -> int:
    direction, base = mp[7], mp[8]
    weekend = day.weekday() >= 5 or day in HOLIDAYS
    profile = WEEKEND if weekend else WEEKDAY
    factor = profile[hour]
    if not weekend and direction == "einwärts":  # morning peak stronger inbound, evening weaker
        factor *= 1.25 if 6 <= hour <= 9 else (0.8 if 16 <= hour <= 19 else 1)
    if not weekend and direction == "auswärts":
        factor *= 0.8 if 6 <= hour <= 9 else (1.25 if 16 <= hour <= 19 else 1)
    growth = 1.0 if day.year == 2025 else 0.97  # slightly less traffic in 2026
    return max(0, round(base * factor * growth * rnd.uniform(0.9, 1.1)))


def write_traffic(path: Path, year: int, start: date, days: int, delivered: date) -> Path:
    rnd = random.Random(year)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(TRAFFIC_HEADER)
        for mp in MEASURING_POINTS:
            msid, zsid, zsname, street, hnr, e, n, direction, _base, outage = mp
            for i in range(days):
                day = start + timedelta(days=i)
                for hour in _hours(day):
                    ts = datetime(day.year, day.month, day.day, hour).isoformat()
                    if day in outage:
                        count, status = "", "Fehlend"
                    elif msid == "Z030M001" and day == start + timedelta(days=3) and hour in (10, 11):
                        count, status = str(_volume(mp, day, hour, rnd)), "Imputiert"
                    else:
                        count, status = str(_volume(mp, day, hour, rnd)), "Gemessen"
                    w.writerow(
                        [
                            msid,
                            "Unbekannt",
                            zsid,
                            zsname,
                            street,
                            hnr,
                            "Unbekannt",
                            f"{e:.2f}",
                            f"{n:.1f}",
                            direction,
                            "789",
                            "Badanstalt Wollishofen" if zsid == "Z001" else "Unbekannt",
                            "1",
                            "2",
                            "Unbekannt",
                            "Unbekannt",
                            "Unbekannt",
                            ts,
                            delivered.isoformat(),
                            count,
                            status,
                        ]
                    )
    return path


# ---------------------------------------------------------------------------------------- vehicle stock

# Verbatim headers as published by ASTRA (read 2026-11-24).
BEST_CURRENT = (
    "Fahrzeugklasse|Fahrzeugart_Code|Fahrzeugart|Marken_Code|Marke|Marke_und_Typ|Typ1|Typ2|Typ3|Typ4|"
    "Typengenehmigungs-Nr|Typengenehmigungs-Nr_Zusatz|Typ|Variante|Version|Fahrgestell-Nr_Teil|Karosserieform_Code|"
    "Karosserieform|Farbe|Farbe_Zusatz|Sitzplätze|Sitzplätze_vorne|Stehplätze|Leergewicht|Nutzlast|Gesamtgewicht|"
    "Gesamtzugsgewicht|Anhängelast|Dachlast|Tankinhalt_Aufbaus|Hubraum|Zylinder|Leistung|Motorkennzeichen|"
    "Treibstoff_Code|Treibstoff|Hybridcode|CO2-WLTP|CO2-NEFZ|El-Verbrauch|Emissionscode|Getriebe_Code|Getriebe|"
    "Getriebe_Detailcode|Antrieb_Code|Antrieb|Achsen|Erstinverkehrsetzung_Jahr|Erstinverkehrsetzung_Monat|"
    "Erstinverkehrsetzung_Kanton|Erstinverkehrsetzung_Staat|Gebrauchtcode|Ersterfassung_Jahr|Ersterfassung_Monat|"
    "Schildfarbe_Code|Schildfarbe|Schildart_Code|Schildart|Inverkehrsetzung_Status_Code|Inverkehrsetzung_Kanton|PLZ|"
    "Staat_Code|Staat"
).split("|")
BEST_2019_07 = (
    "Fahrzeugklasse|Fahrzeugart_Code|Fahrzeugart|Marken_Code|Marke|Marke_und_Typ|Typ1|Typ2|Typ3|Typ4|"
    "Typengenehmigungs-Nr|Typengenehmigungs-Nr_Zusatz|Karosserieform_Code|Karosserieform|Farbe|Farbe_Zusatz|"
    "Sitzplätze|Sitzplätze_vorne|Stehplätze|Leergewicht|Nutzlast|Gesamtgewicht|Gesamtzugsgewicht|Anhängelast|Dachlast|"
    "Tankinhalt_Aufbaus|Hubraum|Zylinder|Leistung|Motorkennzeichen|Treibstoff_Code|Treibstoff|CO2|Emissionscode|"
    "Energieeffizienzkategorie|Getriebe_Code|Getriebe|Getriebe_Detailcode|Antrieb_Code|Antrieb|Achsen|"
    "Erstinverkehrsetzung_Jahr|Erstinverkehrsetzung_Monat|Erstinvekehrsetzung_Kanton|Erstinverkehrsetzung_Staat|"
    "Gebrauchtcode|Ersterfassung_Jahr|Ersterfassung_Monat|Schildfarbe_Code|Schildfarbe|Schildart_Code|Schildart|"
    "Inverkehrsetzung_Status_Code|Inverkehrsetzung_Kanton|PLZ|Staat_Code|Staat|V58"
).split("|")
BEST_2023_01 = ["Erstinverkehrsetzung_Monat]" if c == "Erstinverkehrsetzung_Monat" else c for c in BEST_CURRENT] + [
    "Datenstand"
]
BEST_2022_07 = [c for c in BEST_2023_01 if c != "Fahrgestell-Nr_Teil"]
OGD = (
    "Gebrauchtimport|Inverkehrsetzungsstatus|EU-Fahrzeugklassencode|EU-Fahrzeugklassencode-10 stellig|"
    "Fahrzeugartcode|Fahrzeugartbezeichnung|Marke|Marke und Typ|Typengenehmigung|Typengenehmigung Zusatzcode|Typ|"
    "Variante|Version|Typengenehmigung TypVarianteVersion|Fahrgestellnummer anonymisiert|Karosserieformcode|"
    "Karosserieform Bezeichnung|Hauptfarbe|Zweitfarbe|Drittfarbe|Sitzplätze|Sitzplätze vorne|Stehplätze|Leergewicht|"
    "Nutzlast|Gesamtgewicht|Gesamtzugsgewicht|Anhängelast|Tankinhalt Aufbau|Hubraum|Zylinder|Leistung|Leistungsgewicht|"
    "Motorkennzeichen|Treibstoff|Treibstoff Bezeichnung|Pluginhybrid|CO2-WLTP|CO2-NEFZ|Elektrischer Verbrauch WLTP|"
    "Emissionscode|Getriebe|Getriebebauart|Antrieb|Achsen|Erstinverkehrsetzungsdatum|Erstinverkehrsetzungskanton|"
    "CH-FL-Erstinverkehrsetzungsdatum|CH-FL-Erstinverkehrsetzung Km-Stand|Erstinverkehrsetzungsstaat|"
    "Inverkehrsetzungskanton|Schildfarbe Bezeichnung|Schildart|PLZ|Staat|Datenstand"
).split("|")

FUEL_NAMES = {"B": "Benzin", "D": "Diesel", "E": "Elektrisch", "C": "Benzin / Elektrisch", "F": "Diesel / Elektrisch"}
VEHICLE_TYPES = [("001", "Personenwagen", 0.75), ("060", "Motorrad", 0.15), ("030", "Lieferwagen", 0.10)]
CANTONS = [("ZH", ["80..", "80..", "81..", "84..", "86.."], 0.30), ("ZG", ["63.."], 0.10), ("BE", ["30.."], 0.20),
           ("VD", ["10.."], 0.18), ("AG", ["50.."], 0.18), ("FL", ["94.."], 0.02), ("-1", [""], 0.02)]  # fmt: skip
# Battery-electric share of passenger cars per canton and snapshot year (invented, Zug growing faster).
BEV_SHARE = {"ZH": {2019: 0.010, 2022: 0.030, 2023: 0.045, 2026: 0.090},
             "ZG": {2019: 0.012, 2022: 0.040, 2023: 0.065, 2026: 0.140}}  # fmt: skip
BRANDS = [("TESLA", "TESLA MODEL 3"), ("VW", 'VW GOLF 1.5 TSI "Life"'), ("SKODA", "SKODA OCTAVIA"),
          ("BMW", "BMW X3 xDrive20d"), ("TOYOTA", "TOYOTA YARIS HYBRID")]  # fmt: skip


def _pick(rnd: random.Random, items):
    r, acc = rnd.random(), 0.0
    for item in items:
        acc += item[-1]
        if r <= acc:
            return item
    return items[-1]


def _vehicle(rnd: random.Random, year: int) -> dict:
    canton, plzs, _w = _pick(rnd, CANTONS)
    vcode, vname, _w = _pick(rnd, VEHICLE_TYPES)
    bev = BEV_SHARE.get(canton, {}).get(year, 0.02 if year < 2023 else 0.05)
    if vcode != "001":
        fuel, hybrid = rnd.choice("BBBD"), "N/A"
    else:
        r = rnd.random()
        if r < bev:
            fuel, hybrid = "E", "N/A"
        elif r < bev * 2.5:
            fuel, hybrid = "C", rnd.choice(["NOVC-HEV", "OVC-HEV", "N/A"])
        elif r < 0.35:
            fuel, hybrid = "D", "N/A"
        else:
            fuel, hybrid = "B", "N/A"
    brand, model = ("TESLA", "TESLA MODEL 3") if fuel == "E" and rnd.random() < 0.4 else rnd.choice(BRANDS[1:])
    first = (rnd.randint(2004, year), rnd.randint(1, 12))
    return dict(canton=canton, plz=rnd.choice(plzs), vcode=vcode, vname=vname, fuel=fuel, hybrid=hybrid,
                brand=brand, model=model, first=first, power=str(rnd.randint(50, 250)))  # fmt: skip


def _row(header: list[str], v: dict, data_as_of: str, plz_digits: int = 2) -> list[str]:
    plz = v["plz"][:plz_digits] + "." * (4 - plz_digits) if v["plz"] else ""
    ogd = "Fahrzeugartcode" in header
    values = {
        "Fahrzeugklasse": "M1" if v["vcode"] == "001" else "L3e",
        "EU-Fahrzeugklassencode": "M1" if v["vcode"] == "001" else "L3e",
        "Fahrzeugart_Code": v["vcode"], "Fahrzeugartcode": v["vcode"],
        "Fahrzeugart": v["vname"], "Fahrzeugartbezeichnung": v["vname"],
        "Marke": v["brand"], "Marke_und_Typ": v["model"], "Marke und Typ": v["model"],
        "Leistung": v["power"],
        "Treibstoff_Code": v["fuel"],
        "Treibstoff": v["fuel"] if ogd else FUEL_NAMES[v["fuel"]],
        "Treibstoff Bezeichnung": FUEL_NAMES[v["fuel"]],
        "Hybridcode": v["hybrid"], "Pluginhybrid": "1" if v["hybrid"] == "OVC-HEV" else "0",
        "Erstinverkehrsetzung_Jahr": str(v["first"][0]),
        "Erstinverkehrsetzung_Monat": f"{v['first'][1]:02d}", "Erstinverkehrsetzung_Monat]": f"{v['first'][1]:02d}",
        "Erstinverkehrsetzungsdatum": f"01.{v['first'][1]:02d}.{v['first'][0]}",
        "Gebrauchtcode": "0", "Gebrauchtimport": "0",
        "Inverkehrsetzung_Status_Code": "I", "Inverkehrsetzungsstatus": "I",
        "Inverkehrsetzung_Kanton": v["canton"], "Inverkehrsetzungskanton": v["canton"],
        "PLZ": plz,
        "Staat_Code": "CH" if v["canton"] != "FL" else "FL", "Staat": ("CH" if ogd else "Schweiz"),
        "Datenstand": data_as_of,
    }  # fmt: skip
    return [values.get(c, "") for c in header]


def write_vehicle_stock(path: Path, header: list[str], year: int, n: int, data_as_of: str = "",
                        plz_digits: int = 2, broken_row: bool = False) -> Path:  # fmt: skip
    rnd = random.Random(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\r\n")
        for i in range(n):
            # the current-format file leaves Datenstand empty on its first rows, as the real one does
            as_of = "" if i < 3 and "Fahrzeugartcode" in header else data_as_of
            f.write("\t".join(_row(header, _vehicle(rnd, year), as_of, plz_digits)) + "\r\n")
            if broken_row and i == n // 2:
                f.write("\t".join(["M1", "001", "Personenwagen", "truncated"]) + "\r\n")
    return path


def write_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    t = out_dir / "traffic"
    v = out_dir / "vehicle_stock"
    return [
        write_traffic(t / "sid_dav_verkehrszaehlung_miv_OD2031_2025.csv", 2025, date(2025, 10, 13), 28,
                      date(2026, 1, 15)),
        write_traffic(t / "sid_dav_verkehrszaehlung_miv_OD2031_2026.csv", 2026, date(2026, 3, 16), 28,
                      date(2026, 11, 23)),
        write_vehicle_stock(v / "BEST-20190701.txt", BEST_2019_07, 2019, 1500, broken_row=True),
        write_vehicle_stock(v / "BEST-20220701.txt", BEST_2022_07, 2022, 1500, "01.07.2022", plz_digits=1),
        write_vehicle_stock(v / "BEST-20230101.txt", BEST_2023_01, 2023, 1500, "01.01.2023"),
        write_vehicle_stock(v / "best_ogd.txt", OGD, 2026, 1500, "31.10.2026"),
    ]  # fmt: skip


if __name__ == "__main__":
    for p in write_all(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")):
        print(p)
