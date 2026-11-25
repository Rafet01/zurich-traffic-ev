"""Turn the gold tables into the README's Findings section, so the published numbers are never typed by hand.

    python pipeline.py findings            # print the Markdown
    python pipeline.py findings --write    # replace the block between the findings markers in README.md

Refuses to write while any loaded file is one of the synthetic test fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
START, END = "<!-- findings:start -->", "<!-- findings:end -->"
DIRECTIONS = {"inbound": "into the city", "outbound": "out of the city"}


def is_synthetic(manifest_path: Path) -> bool:
    if not manifest_path.exists():
        return False
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line) if line.strip() else {}
        uri = (entry.get("source_uri") or "").replace("\\", "/")
        if entry.get("status") == "loaded" and "tests/fixtures" in uri:
            return True
    return False


def _rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _month(d) -> str:
    return f"{d:%b %Y}" if d else "?"


def render(con, today: date | None = None) -> str:
    today = today or date.today()
    files = _rows(
        con,
        """
        select dataset, count(*) as files, min(partition_key) as first, max(partition_key) as last,
               avg(share_hours_measured) as measured, max(measuring_points) as points
        from gold.mart_data_quality where is_current_version group by dataset""",
    )
    basis = {f["dataset"]: f for f in files}
    out = [f"_Generated from the gold tables on {today:%Y-%m-%d} by `python pipeline.py findings`._", ""]
    t, v = basis.get("traffic_counts"), basis.get("vehicle_stock")
    if t:
        out.append(
            f"Data: {t['files']} yearly traffic files ({t['first']}-{t['last']}, up to {t['points']} measuring "
            f"points, {t['measured']:.1%} of hours measured)"
            + (f" and {v['files']} vehicle stock snapshots ({v['first'][:7]} to {v['last'][:7]})." if v else ".")
        )
        out.append("")

    peaks = _rows(
        con,
        """
        select direction_group, hour_of_day, avg_vehicles_per_point, share_of_daily_traffic
        from gold.mart_peak_hours
        where day_type = 'weekday' and busiest_rank = 1 and direction_group in ('inbound', 'outbound')
        order by direction_group""",
    )
    sites = _rows(
        con,
        """
        select rank_pm_peak, counting_site_name, direction, avg_vehicles_per_hour_pm_peak, avg_vehicles_per_hour_am_peak
        from gold.mart_busiest_sites_at_peak where rank_pm_peak <= 5 order by rank_pm_peak""",
    )
    if peaks:
        out.append("**1. Rush hour.** On working days the busiest hour is " + " and ".join(
            f"{p['hour_of_day']:02d}:00 {DIRECTIONS[p['direction_group']]} "
            f"({p['avg_vehicles_per_point']:,.0f} vehicles per measuring point, {p['share_of_daily_traffic']:.1%} "
            "of the day)"
            for p in peaks
        ) + ".")  # fmt: skip
        out.append("")
    if sites:
        out += [
            "| Evening peak rank | Site | Direction | Vehicles/hour 16-19 | Vehicles/hour 06-09 |",
            "|---|---|---|---|---|",
        ]
        out += [
            f"| {s['rank_pm_peak']} | {s['counting_site_name']} | {s['direction']} | "
            f"{s['avg_vehicles_per_hour_pm_peak']:,.0f} | {s['avg_vehicles_per_hour_am_peak']:,.0f} |"
            for s in sites
        ]
        out.append("")

    growth = _rows(
        con,
        """
        select region_code, region_name, first_stock_date, last_stock_date, first_share, last_share,
               share_growth_pp_per_year, battery_electric_cagr
        from gold.mart_ev_growth_zug_vs_zurich order by rank_by_pp_per_year""",
    )
    by_code = {g["region_code"]: g for g in growth}
    zg, zh = by_code.get("kanton_zg"), by_code.get("kanton_zh")
    if zg and zh:
        faster = zg["share_growth_pp_per_year"] > zh["share_growth_pp_per_year"]
        out.append(
            f"**2. Electric cars.** {'Yes' if faster else 'No'}: from {_month(zg['first_stock_date'])} to "
            f"{_month(zg['last_stock_date'])} the battery-electric share of passenger cars grew by "
            f"{zg['share_growth_pp_per_year']:.2f} percentage points per year in the canton of Zug and by "
            f"{zh['share_growth_pp_per_year']:.2f} in the canton of Zurich "
            f"({zg['first_share']:.1%} to {zg['last_share']:.1%} vs {zh['first_share']:.1%} to {zh['last_share']:.1%})."
        )
        ranks = _rows(
            con,
            """
            select canton, rank_in_snapshot, cantons_in_snapshot from gold.mart_ev_share_by_canton
            where is_latest_snapshot and canton in ('ZG', 'ZH') order by canton""",
        )
        if ranks:
            out.append(
                "In the latest snapshot "
                + " and ".join(
                    f"{r['canton']} ranks {r['rank_in_snapshot']} of {r['cantons_in_snapshot']}" for r in ranks
                )
                + " cantons."
            )
        out.append("")
        out += ["| Region | First | Last | pp per year | BEVs per year (CAGR) |", "|---|---|---|---|---|"]
        out += [
            f"| {g['region_name']} | {g['first_share']:.1%} | {g['last_share']:.1%} | "
            f"{g['share_growth_pp_per_year']:+.2f} | "
            + ("n/a" if g["battery_electric_cagr"] is None else f"{g['battery_electric_cagr']:+.0%}")
            + " |"
            for g in growth
        ]
        out.append("")
        out.append(
            "Cars are counted where they are registered: company and leasing cars count where the holder sits, "
            "which may matter in Zug."
        )
    return "\n".join(out).rstrip() + "\n"


def replace_block(readme: str, block: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), flags=re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"README has no {START} ... {END} block")
    return pattern.sub(lambda _: f"{START}\n{block}{END}", readme, count=1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--warehouse", type=Path, default=ROOT / "data" / "warehouse.duckdb")
    p.add_argument("--manifest", type=Path, default=ROOT / "data" / "manifest.jsonl")
    p.add_argument("--readme", type=Path, default=ROOT / "README.md")
    p.add_argument("--write", action="store_true", help="replace the findings block in the README")
    args = p.parse_args(argv)

    with duckdb.connect(str(args.warehouse), read_only=True) as con:
        block = render(con)
    print(block)
    if args.write:
        if is_synthetic(args.manifest):
            print("not written: the warehouse contains synthetic test files (make demo)", file=sys.stderr)
            return 1
        text = args.readme.read_text(encoding="utf-8")
        args.readme.write_text(replace_block(text, block), encoding="utf-8", newline="")
        print(f"written to {args.readme}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
