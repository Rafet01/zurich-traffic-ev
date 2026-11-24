"""Known header layouts of the ASTRA vehicle stock files, mapped to one set of canonical columns.

The files on https://opendata.astra.admin.ch/ivzod/ (1000-Fahrzeuge_IVZ/1300-Fahrzeugbestaende/) are
tab-separated, UTF-8, one row per registered vehicle, no holder data. Six different headers were found
between July 2019 and November 2026 (checked 2026-11-24 by reading the first bytes of every file):

  BEST-20190701           58 columns, typo "Erstinvekehrsetzung_Kanton", empty trailing column "V58"
  BEST-20200101..20210101 58 columns, no Hybridcode, trailing "V58"
  BEST-20210701..20220101 57 columns
  BEST-20220701           63 columns, + Hybridcode / CO2-WLTP / Datenstand; PLZ masked to ONE digit ("8...")
  BEST-20230101           64 columns, header typo "Erstinverkehrsetzung_Monat]"
  BEST-20240101..BEST.txt 63-64 columns
  best_ogd.txt            56 columns, new format since November 2026: other names, "Treibstoff" now holds
                          the fuel *code*, first registration as one date, Datenstand e.g. "31.10.2026"

Two families cover all of them. Inside a family, a canonical column accepts several spellings.
"""

from __future__ import annotations

# Canonical columns landed in bronze (raw string values, untouched).
CANONICAL_COLUMNS = [
    "vehicle_class",
    "vehicle_type_code",
    "vehicle_type",
    "brand",
    "fuel_code",
    "fuel",
    "hybrid_code",
    "plugin_hybrid",
    "power_kw",
    "co2_wltp",
    "first_registration_year",
    "first_registration_month",
    "first_registration_date",
    "used_import_code",
    "registration_status_code",
    "canton",
    "plz_masked",
    "country_code",
    "data_as_of",
]

# canonical column -> accepted source header names (first match wins). None = column does not exist.
LAYOUTS: dict[str, dict[str, list[str] | None]] = {
    "astra_best": {
        "vehicle_class": ["Fahrzeugklasse"],
        "vehicle_type_code": ["Fahrzeugart_Code"],
        "vehicle_type": ["Fahrzeugart"],
        "brand": ["Marke"],
        "fuel_code": ["Treibstoff_Code"],
        "fuel": ["Treibstoff"],
        "hybrid_code": ["Hybridcode"],
        "plugin_hybrid": None,
        "power_kw": ["Leistung"],
        "co2_wltp": ["CO2-WLTP"],
        "first_registration_year": ["Erstinverkehrsetzung_Jahr"],
        "first_registration_month": ["Erstinverkehrsetzung_Monat", "Erstinverkehrsetzung_Monat]"],
        "first_registration_date": None,
        "used_import_code": ["Gebrauchtcode"],
        "registration_status_code": ["Inverkehrsetzung_Status_Code"],
        "canton": ["Inverkehrsetzung_Kanton"],
        "plz_masked": ["PLZ"],
        "country_code": ["Staat_Code"],
        "data_as_of": ["Datenstand"],
    },
    "astra_ogd": {
        "vehicle_class": ["EU-Fahrzeugklassencode"],
        "vehicle_type_code": ["Fahrzeugartcode"],
        "vehicle_type": ["Fahrzeugartbezeichnung"],
        "brand": ["Marke"],
        "fuel_code": ["Treibstoff"],
        "fuel": ["Treibstoff Bezeichnung"],
        "hybrid_code": None,
        "plugin_hybrid": ["Pluginhybrid"],
        "power_kw": ["Leistung"],
        "co2_wltp": ["CO2-WLTP"],
        "first_registration_year": None,
        "first_registration_month": None,
        "first_registration_date": ["Erstinverkehrsetzungsdatum"],
        "used_import_code": ["Gebrauchtimport"],
        "registration_status_code": ["Inverkehrsetzungsstatus"],
        "canton": ["Inverkehrsetzungskanton"],
        "plz_masked": ["PLZ"],
        "country_code": ["Staat"],
        "data_as_of": ["Datenstand"],
    },
}

# Without these the file cannot answer the questions; anything else may be missing (-> null).
REQUIRED = ["vehicle_type_code", "fuel_code", "canton", "registration_status_code"]

# A header must contain these to be recognised as a family (they are unique to it).
SIGNATURE = {"astra_best": "Fahrzeugart_Code", "astra_ogd": "Fahrzeugartcode"}


def resolve(header: list[str]) -> tuple[str, list[int | None]]:
    """Return (layout name, source column index per canonical column) or raise ValueError."""
    header = [h.strip() for h in header]
    for layout, signature in SIGNATURE.items():
        if signature not in header:
            continue
        mapping = LAYOUTS[layout]
        positions: list[int | None] = []
        for col in CANONICAL_COLUMNS:
            names = mapping[col] or []
            positions.append(next((header.index(n) for n in names if n in header), None))
        missing = [c for c, pos in zip(CANONICAL_COLUMNS, positions, strict=True) if pos is None and c in REQUIRED]
        if missing:
            raise ValueError(f"layout {layout}: required columns not found: {missing}")
        return layout, positions
    raise ValueError(f"unknown vehicle stock layout (first columns: {header[:5]})")
