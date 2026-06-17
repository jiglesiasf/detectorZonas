"""Scrape MIVAU Valor Tasado de la Vivienda dataset.

Downloads the quarterly XLS file with appraised housing values
for Spanish municipalities >25k inhabitants. Extracts price/m2
time series and computes annual variation and historical max.
"""

import csv
import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

MIVAU_URL = (
    "https://apps.fomento.gob.es/BoletinOnline2/sedal/35103500.XLS"
)
OUTPUT = "data/precios_mivau.csv"


def parse_sheet_name(name):
    """Parse sheet name like 'T1A2024' or 'T2A2005 ' into (quarter, year)."""
    name = name.strip()
    m = re.match(r"T(\d)A(\d{4})", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse_value(val):
    """Parse a value cell: number, 'n.r.' (not representative), or NaN."""
    if pd.isna(val):
        return None
    if isinstance(val, str):
        val = val.strip()
        if val.lower() in ("n.r.", "n/a", ""):
            return None
        try:
            return float(val.replace(",", "."))
        except (ValueError, AttributeError):
            return None
    return float(val)


def normalize_name(name):
    """Normalize municipality name for matching.

    Handles accents, parentheses ordering (e.g. 'Coruña (A)' -> 'a coruña'),
    and slashes (always sorts parts to handle reversed dual names).
    """
    s = name.strip().lower()

    # Handle "Name (Prefix)" -> "Prefix Name"
    m = re.match(r"^(.+?)\s*\((.+?)\)\s*$", s)
    if m:
        alt = f"{m.group(2).strip()} {m.group(1).strip()}"
        s = alt

    # Remove parenthetical suffixes after reordering
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()

    # Normalize slashes: "a / b" -> "a/b", then sort parts
    s = re.sub(r"\s*/\s*", "/", s)
    if "/" in s:
        parts = s.split("/")
        parts.sort()
        s = "/".join(parts)

    # Remove accents
    accents = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
        "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
        "ñ": "n",
    }
    for a, b in accents.items():
        s = s.replace(a, b)

    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()

    return s


def scrape():
    print(f"Downloading MIVAU XLS from {MIVAU_URL}...")
    resp = requests.get(MIVAU_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    resp.raise_for_status()
    print(f"Downloaded {len(resp.content):,} bytes")

    xls = pd.ExcelFile(io.BytesIO(resp.content))
    print(f"Sheets: {len(xls.sheet_names)}")

    # Parse each sheet into a unified dataframe
    all_records = []
    for sheet_name in xls.sheet_names:
        quarter, year = parse_sheet_name(sheet_name)
        if quarter is None:
            continue

        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        # The structure varies before/after 2010
        is_old_format = year < 2010

        for _, row in df.iterrows():
            name = str(row[2]).strip() if pd.notna(row[2]) else ""
            if not name or name == "nan" or "Elige" in name or "Comunidad" in name:
                continue

            if is_old_format:
                total = parse_value(row[3])
                n_tasaciones = parse_value(row[5])
            else:
                val_new = parse_value(row[3])
                val_old = parse_value(row[4])
                total = parse_value(row[5])
                n_tasaciones = parse_value(row[9])
                # If total is missing but components exist, use val_old
                if total is None and val_old is not None:
                    total = val_old

            if total is None:
                continue

            all_records.append({
                "municipio_nombre": name,
                "year": year,
                "quarter": quarter,
                "precio_m2": total,
                "n_tasaciones": n_tasaciones,
            })

    raw = pd.DataFrame(all_records)
    print(f"Total records: {len(raw)}")
    print(f"Unique municipios: {raw['municipio_nombre'].nunique()}")
    print(f"Year range: {raw['year'].min()} - {raw['year'].max()}")
    print(f"Latest quarter: {raw['year'].max()} Q{raw[raw['year'] == raw['year'].max()]['quarter'].max()}")

    # For each municipality, compute:
    # - latest quarter's total value
    # - same quarter last year's value (for annual variation)
    # - all-time max value
    # - whether latest is at max

    results = []
    for muni_name, grp in raw.groupby("municipio_nombre"):
        grp = grp.sort_values(["year", "quarter"])

        latest = grp.iloc[-1]
        latest_price = latest["precio_m2"]
        latest_year = latest["year"]
        latest_quarter = latest["quarter"]

        # Find same quarter last year
        q_prev = grp[(grp["year"] == latest_year - 1) & (grp["quarter"] == latest_quarter)]
        prev_price = q_prev.iloc[0]["precio_m2"] if len(q_prev) > 0 else None

        # Annual variation
        if prev_price and prev_price > 0 and latest_price:
            variacion_anual = round((latest_price / prev_price - 1) * 100, 2)
        else:
            variacion_anual = None

        # Historical max
        hist_max = grp["precio_m2"].max()
        en_maximo = abs(latest_price - hist_max) < 0.01 if (latest_price and hist_max) else False

        # Variation from max
        if hist_max and hist_max > 0 and latest_price:
            variacion_maximo = round((latest_price / hist_max - 1) * 100, 2)
        else:
            variacion_maximo = None

        results.append({
            "municipio_nombre": muni_name,
            "nombre_normalizado": normalize_name(muni_name),
            "precio_m2": latest_price,
            "variacion_anual": variacion_anual,
            "en_maximo_historico": en_maximo,
            "variacion_maximo": variacion_maximo,
            "year": latest_year,
            "quarter": latest_quarter,
            "n_tasaciones": latest["n_tasaciones"],
        })

    out_df = pd.DataFrame(results)
    out_df = out_df.sort_values("municipio_nombre")

    out_path = Path(OUTPUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    col_order = [
        "municipio_nombre", "nombre_normalizado", "precio_m2",
        "variacion_anual", "en_maximo_historico", "variacion_maximo",
        "year", "quarter", "n_tasaciones",
    ]
    out_df = out_df[[c for c in col_order if c in out_df.columns]]
    out_df.to_csv(out_path, index=False)

    print(f"\nSaved {len(out_df)} municipalities to {OUTPUT}")
    print(f"  With annual data: {out_df['variacion_anual'].notna().sum()}")
    print(f"  At max historical: {out_df['en_maximo_historico'].sum()}")
    print(f"  Positive annual: {(out_df['variacion_anual'] > 0).sum()}")
    print(f"\nSample:")
    for _, r in out_df.head(5).iterrows():
        print(f"  {r['municipio_nombre']:30s} {r['precio_m2']:>8.1f} €/m2  "
              f"var anual: {r['variacion_anual']:>+6.2f}%  "
              f"max: {'SI' if r['en_maximo_historico'] else 'NO'}")

    return out_df


def show_muni(name):
    """Quick lookup for a specific municipality."""
    df = pd.read_csv(OUTPUT)
    m = df[df["municipio_nombre"].str.contains(name, case=False, na=False)]
    if len(m) > 0:
        print(m.to_string())
    else:
        print(f"No municipality matching '{name}'")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--lookup":
        show_muni(sys.argv[2])
    else:
        scrape()
