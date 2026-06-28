"""Scrape real housing prices per postal code from the Portal Estadístico del Notariado.

Uses the ArcGIS FeatureServer API discovered from penotariado.com.
No Playwright needed -- direct REST queries.
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

API_BASE = (
    "https://services-eu1.arcgis.com/UpPGybwp9RK4YtZj/arcgis/rest/services"
    "/PRO_Inmuebles_Datos/FeatureServer/4/query"
)
OUTPUT = "data/precios_notariado.csv"

TARGET_PROVINCES = ["03", "12", "46", "15", "27", "32", "36", "30", "43"]


def query_cp_data(cp_list: list[tuple[str, str]]) -> list[dict]:
    """Query the ArcGIS CP layer for specific CPs.

    cp_list: list of (cp, provincia_id) tuples
    Returns list of attribute dicts.
    """
    results = []
    # Batch by province (avoids hitting URL length limits)
    by_prov = {}
    for cp, prov in cp_list:
        by_prov.setdefault(prov, []).append(cp)

    for prov, cps in by_prov.items():
        # Split into chunks of 80 to avoid URL length issues
        for i in range(0, len(cps), 80):
            chunk = cps[i:i+80]
            cp_filter = ", ".join(f"'{c}'" for c in chunk)
            where = (
                f"cp IN ({cp_filter}) "
                f"AND tipo_construccion_id=99 "
                f"AND clase_finca_urbana_id=99"
            )

            params = {
                "f": "json",
                "where": where,
                "outFields": "cp,precio_m2,precio_medio,superficie_media,total_informados,total,es_estimado",
                "returnGeometry": "false",
            }

            data = _query_with_retry(prov, i, params)
            features = data.get("features", [])

            for feat in features:
                results.append(feat["attributes"])

            print(f"  Prov {prov}: queried {len(chunk)} CPs, got {len(features)} results")

        time.sleep(0.3)  # rate limit

    return results


def _query_with_retry(prov, chunk_idx, params):
    """Make API query with retry logic."""
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(API_BASE, params=params, timeout=60)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            err_body = resp.text[:300] if resp is not None else 'no response'
            print(f"  Attempt {attempt+1} failed for prov {prov} chunk {chunk_idx}: {e}")
            if attempt == 2:
                print(f"    Response: {err_body}")
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"All retries exhausted for prov {prov} chunk {chunk_idx}")

    return results


def load_target_cps() -> list[tuple[str, str]]:
    """Load CPs from pipeline output or CP-municipio mapping."""
    completo_path = Path("data/poblacion_por_cp_completo.csv")
    mapping_path = Path("data/codigos_postales_municipios.csv")

    if completo_path.exists():
        df = pd.read_csv(completo_path, dtype={"codigo_postal": str})
        df["codigo_postal"] = df["codigo_postal"].str.zfill(5)
        cp_prov_map = {}
        for _, row in df.iterrows():
            cp = row["codigo_postal"]
            prov = cp[:2]
            if prov in TARGET_PROVINCES:
                cp_prov_map[cp] = prov
        print(f"Loaded {len(cp_prov_map)} target CPs from poblacion_por_cp_completo.csv")
        return [(cp, prov) for cp, prov in cp_prov_map.items()]

    if mapping_path.exists():
        df = pd.read_csv(mapping_path, dtype={"codigo_postal": str})
        df["codigo_postal"] = df["codigo_postal"].str.zfill(5)
        df = df[df["codigo_postal"].str[:2].isin(TARGET_PROVINCES)]
        cps = sorted(df["codigo_postal"].unique())
        print(f"Loaded {len(cps)} target CPs from codigos_postales_municipios.csv")
        return [(cp, cp[:2]) for cp in cps]

    raise FileNotFoundError(
        "No CP data found. Run pipeline.py first or ensure data exists."
    )


def scrape() -> None:
    print("=" * 60)
    print("Portal Estadístico del Notariado - CP Price Scraper")
    print("=" * 60)

    target = load_target_cps()
    total_cps = len(set(cp for cp, _ in target))
    print(f"Target CPs: {total_cps}")

    # Check if we already have results
    if os.path.exists(OUTPUT):
        existing = pd.read_csv(OUTPUT, dtype={"codigo_postal": str})
        existing_cps = set(existing["codigo_postal"].str.zfill(5))
        # Filter out already scraped CPs
        pending = [(cp, prov) for cp, prov in target if cp not in existing_cps]
        print(f"Existing: {len(existing_cps)} CPs, Pending: {len(pending)}")
        if not pending:
            print("All CPs already scraped.")
            return
    else:
        pending = target
        print(f"New scrape: {len(pending)} CPs")

    print("Querying ArcGIS API...")
    raw = query_cp_data(pending)

    if not raw:
        print("No data returned from API!")
        return

    df = pd.DataFrame(raw)

    # Rename columns
    df.rename(columns={
        "cp": "codigo_postal",
    }, inplace=True)

    df["codigo_postal"] = df["codigo_postal"].str.zfill(5)

    # Merge with any existing results
    if os.path.exists(OUTPUT):
        existing = pd.read_csv(OUTPUT, dtype={"codigo_postal": str})
        df = pd.concat([existing, df], ignore_index=True)
        df.drop_duplicates(subset=["codigo_postal", "tipo_construccion_id", "clase_finca_urbana_id"], keep="last", inplace=True)

    out_path = Path(OUTPUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    covered = df["precio_m2"].notna().sum()
    print(f"\nSaved {len(df)} records to {OUTPUT}")
    print(f"CPs with price data: {covered}")
    if covered > 0:
        print(f"Price range: {df['precio_m2'].min():.0f} - {df['precio_m2'].max():.0f} €/m2")
        print(f"Avg price: {df['precio_m2'].mean():.0f} €/m2")

    # Show breakdown
    print(f"\nCPs found by province:")
    df["prov"] = df["codigo_postal"].str[:2]
    for prov in sorted(df["prov"].unique()):
        n = len(df[df["prov"] == prov])
        c = df[df["prov"] == prov]["precio_m2"].notna().sum()
        print(f"  {prov}: {n} records, {c} with price")


if __name__ == "__main__":
    scrape()
