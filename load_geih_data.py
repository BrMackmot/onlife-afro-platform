#!/usr/bin/env python3
# =============================================================
# load_geih_data.py  —  Auto-feed DANE indicators into OnLife Afro
# -------------------------------------------------------------
# The platform already looks for this file: app.py -> try_run_pipeline()
# runs it on startup (and the admin endpoint /api/pipeline/run triggers it).
# When it finishes with exit code 0, the app clears its cache and re-reads
# data/official_indicators.csv. So all this script has to do is WRITE that CSV.
#
# WHERE THE DATA COMES FROM
#   datos.gov.co is a Socrata open-data portal. Every dataset has a built-in
#   HTTP API:  https://www.datos.gov.co/resource/<4x4-id>.json?$select=...&$where=...
#   That is the part that is genuinely automatable. You give this script the
#   dataset id + column names for each indicator and it does the rest.
#
# WHAT YOU STILL HAVE TO DO ONCE (config, below)
#   1. Get a FREE Socrata app token (since SODA3 / Sept-2025, anonymous traffic
#      is throttled). Register at https://evergreen.data.socrata.com/ or via the
#      datos.gov.co developer settings, then:  export SOCRATA_APP_TOKEN=xxxx
#   2. Find the dataset ids for the indicators you want. Run:
#        python load_geih_data.py --discover desempleo
#      and copy the 4x4 id + the relevant column names into SOURCES below.
#
# Indicators the app uses (CSV columns):
#   unemployment  poverty  education  healthcare  connectivity
# Territory rows must use the app's slugs:
#   choco buenaventura tumaco sanandres cali cartagena pacificosur
# =============================================================

import os, sys, csv, json, time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.environ.get("DATA_FOLDER", os.path.join(BASE_DIR, "data"))
CSV_PATH    = os.path.join(DATA_FOLDER, "official_indicators.csv")
APP_TOKEN   = os.environ.get("SOCRATA_APP_TOKEN", "").strip()
DOMAIN      = "www.datos.gov.co"
METRICS     = ["unemployment", "poverty", "education", "healthcare", "connectivity"]

# Baseline values (same as app.py TERRITORIES). Used to fill any metric/territory
# the API can't supply, so the CSV is ALWAYS complete and the app never breaks.
BASELINE = {
    "choco":        {"unemployment":18.4,"poverty":62,"education":6.2,"healthcare":42,"connectivity":31},
    "buenaventura": {"unemployment":16.1,"poverty":55,"education":7.4,"healthcare":51,"connectivity":45},
    "tumaco":       {"unemployment":19.3,"poverty":67,"education":5.9,"healthcare":38,"connectivity":28},
    "sanandres":    {"unemployment":11.7,"poverty":22,"education":9.8,"healthcare":78,"connectivity":72},
    "cali":         {"unemployment":14.8,"poverty":38,"education":8.3,"healthcare":65,"connectivity":58},
    "cartagena":    {"unemployment":15.2,"poverty":44,"education":7.9,"healthcare":59,"connectivity":51},
    "pacificosur":  {"unemployment":20.1,"poverty":71,"education":5.4,"healthcare":31,"connectivity":22},
}

# ── CONFIGURE YOUR SOURCES HERE ──────────────────────────────
# For each metric, point at a Socrata dataset and tell the script which column
# holds the territory name, which holds the value, and how DANE's territory
# labels map onto the app slugs. Leave a metric as None to keep the baseline.
#
# Example shape (fill `dataset`, `ter_col`, `val_col`, `where` with REAL values
# you found via --discover; the ids below are placeholders, NOT real):
#
#   "unemployment": {
#       "dataset": "abcd-1234",        # 4x4 id from datos.gov.co
#       "ter_col": "ciudad",           # column with the territory/city name
#       "val_col": "tasa_desempleo",   # column with the numeric value
#       "where":   "anio='2023'",      # optional SoQL filter (latest year, etc.)
#       "map": {                       # DANE label -> app slug
#           "Buenaventura":"buenaventura", "Cali":"cali",
#           "Cartagena":"cartagena", "Quibdó":"choco", "Tumaco":"tumaco",
#           "San Andrés":"sanandres",
#       },
#   },
SOURCES = {
    "unemployment": None,
    "poverty":      None,
    "education":    None,
    "healthcare":   None,
    "connectivity": None,
}


def _get(url):
    headers = {"Accept": "application/json", "User-Agent": "OnLifeAfro-pipeline/1.0"}
    if APP_TOKEN:
        headers["X-App-Token"] = APP_TOKEN
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def discover(term):
    """Find candidate DANE datasets so you can grab their 4x4 ids + columns."""
    url = "https://api.us.socrata.com/api/catalog/v1?" + urlencode({
        "domains": DOMAIN, "search_context": DOMAIN, "q": term, "limit": 15})
    try:
        for d in _get(url).get("results", []):
            r = d.get("resource", {})
            print(f"  {r.get('id','????-????')}  {r.get('name','')[:70]}")
            cols = r.get("columns_field_name") or []
            if cols:
                print(f"        columns: {', '.join(cols[:12])}")
    except (URLError, HTTPError, ValueError) as e:
        print("Discovery failed:", e)


def fetch_metric(metric, cfg, retries=2):
    """Pull one metric from its dataset and return {app_slug: value}."""
    params = {"$limit": "5000"}
    sel = []
    if cfg.get("ter_col"): sel.append(cfg["ter_col"])
    if cfg.get("val_col"): sel.append(cfg["val_col"])
    if sel: params["$select"] = ",".join(sel)
    if cfg.get("where"): params["$where"] = cfg["where"]
    url = f"https://{DOMAIN}/resource/{cfg['dataset']}.json?" + urlencode(params)

    rows = None
    for attempt in range(retries + 1):
        try:
            rows = _get(url); break
        except (URLError, HTTPError, ValueError) as e:
            print(f"  [{metric}] attempt {attempt+1} failed: {e}")
            time.sleep(1.5 * (attempt + 1))
    if rows is None:
        return {}

    out, mapping = {}, cfg.get("map", {})
    for row in rows:
        label = str(row.get(cfg["ter_col"], "")).strip()
        slug  = mapping.get(label)
        if not slug:
            continue
        try:
            out[slug] = round(float(row.get(cfg["val_col"])), 2)
        except (TypeError, ValueError):
            continue
    print(f"  [{metric}] matched {len(out)} territories")
    return out


def build_csv():
    # Start from baseline, then overlay anything we successfully fetch.
    data = {slug: dict(vals) for slug, vals in BASELINE.items()}
    fetched_any = False
    for metric, cfg in SOURCES.items():
        if not cfg or not cfg.get("dataset"):
            continue
        got = fetch_metric(metric, cfg)
        for slug, val in got.items():
            data.setdefault(slug, {})[metric] = val
            fetched_any = True

    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["territory"] + METRICS)
        for slug, vals in data.items():
            w.writerow([slug] + [vals.get(m, "") for m in METRICS])

    print(("Wrote (with live DANE data) " if fetched_any
           else "Wrote (baseline only — no sources configured/reachable) ") + CSV_PATH)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        term = sys.argv[2] if len(sys.argv) > 2 else "desempleo"
        print(f"Searching datos.gov.co for: {term}")
        discover(term)
        sys.exit(0)
    if not APP_TOKEN:
        print("WARNING: no SOCRATA_APP_TOKEN set — requests may be throttled (SODA3).")
    sys.exit(build_csv())
