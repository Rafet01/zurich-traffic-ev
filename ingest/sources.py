"""List the files both publishers currently offer, and which of them still need to be ingested.

  python ingest/sources.py traffic --only-new         -> URLs of yearly traffic CSVs to (re)load
  python ingest/sources.py vehicle-stock --only-new   -> URLs of vehicle stock snapshots to load

"New" means: never loaded, or a file that is regenerated in place (the current year's traffic CSV,
the current month's best_ogd.txt). For those, the ingest itself skips the download when the server's
ETag / Last-Modified are unchanged since the last load.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import USER_AGENT, read_manifest  # noqa: E402

TRAFFIC_PACKAGE_API = "https://data.stadt-zuerich.ch/api/3/action/package_show?id=sid_dav_verkehrszaehlung_miv_od2031"
ASTRA_STOCK_DIR = (
    "https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/1300-Fahrzeugbestaende/1320-Datensaetze_monatlich/"
)
ASTRA_HISTORY_DIR = ASTRA_STOCK_DIR + "1323-Vorjahrsdaten/"

TRAFFIC_FILE = re.compile(r"_OD2031_(\d{4})\.csv$", re.IGNORECASE)
# Passenger cars, motorbikes etc. are all in BEST*.txt; BEST_ANDERE/ANH/MOTO are other vehicle groups.
STOCK_HISTORY_FILE = re.compile(r"^BEST-(\d{8})\.txt$")
STOCK_CURRENT_FILE = "best_ogd.txt"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def traffic_files(package_json: dict) -> list[tuple[str, str, int]]:
    """(file name, url, year) of every yearly CSV in the CKAN package, oldest first."""
    out = []
    for r in package_json["result"]["resources"]:
        url = r["url"]
        name = url.rsplit("/", 1)[-1]
        m = TRAFFIC_FILE.search(name)
        if m:
            out.append((name, url, int(m.group(1))))
    return sorted(out, key=lambda x: x[2])


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href" and v]


def directory_links(html: str) -> list[str]:
    """File names linked from a directory listing; works for relative and absolute hrefs alike."""
    p = _Links()
    p.feed(html)
    return [unquote(urlsplit(h).path).rstrip("/").rsplit("/", 1)[-1] for h in p.hrefs]


def vehicle_stock_files(current_html: str, history_html: str) -> list[tuple[str, str]]:
    """(file name, url) of the half-yearly history files (oldest first) plus the current snapshot."""
    history = sorted(h for h in directory_links(history_html) if STOCK_HISTORY_FILE.match(h))
    out = [(h, ASTRA_HISTORY_DIR + h) for h in history]
    if STOCK_CURRENT_FILE in directory_links(current_html):
        out.append((STOCK_CURRENT_FILE, ASTRA_STOCK_DIR + STOCK_CURRENT_FILE))
    return out


def loaded_names(manifest: list[dict], dataset: str) -> set[str]:
    return {m["source_file"].lower() for m in manifest if m["dataset"] == dataset and m["status"] == "loaded"}


def select_traffic(files, manifest, today: date | None = None) -> list[str]:
    today = today or date.today()
    done = loaded_names(manifest, "traffic_counts")
    # The current year's file changes daily; in January the previous year still receives late corrections.
    refresh = {today.year, today.year - 1} if today.month == 1 else {today.year}
    return [url for name, url, year in files if name.lower() not in done or year in refresh]


def select_vehicle_stock(files, manifest) -> list[str]:
    done = loaded_names(manifest, "vehicle_stock")
    return [url for name, url in files if name.lower() not in done or name == STOCK_CURRENT_FILE]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dataset", choices=["traffic", "vehicle-stock"])
    p.add_argument("--only-new", action="store_true")
    p.add_argument("--manifest", type=Path, default=Path("data/manifest.jsonl"))
    args = p.parse_args(argv)

    manifest = read_manifest(args.manifest) if args.only_new else []
    if args.dataset == "traffic":
        files = traffic_files(json.loads(_get(TRAFFIC_PACKAGE_API)))
        urls = select_traffic(files, manifest) if args.only_new else [u for _, u, _ in files]
    else:
        files = vehicle_stock_files(_get(ASTRA_STOCK_DIR).decode(), _get(ASTRA_HISTORY_DIR).decode())
        urls = select_vehicle_stock(files, manifest) if args.only_new else [u for _, u in files]
    print("\n".join(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
