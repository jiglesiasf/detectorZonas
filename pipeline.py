import json
import pandas as pd
import requests
import time
import sys
from pathlib import Path

PROVINCES = {
    "03": ("Alicante/Alacant", 2856),
    "12": ("Castellón/Castelló", 2865),
    "46": ("Valencia/València", 2903),
    "15": ("A Coruña", 2868),
    "27": ("Lugo", 2880),
    "32": ("Ourense", 2885),
    "36": ("Pontevedra", 2890),
    "30": ("Murcia", 2883),
    "43": ("Tarragona", 2900),
}

API_BASE = "https://servicios.ine.es/wstempus/js/ES"

def fetch_table_data(table_id, year_ini, year_fin):
    params = {"date": f"{year_ini}0101:{year_fin}1231", "tip": "A"}
    resp = requests.get(f"{API_BASE}/DATOS_TABLA/{table_id}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def parse_series_name(nombre):
    parts = nombre.split(". ")
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return nombre.strip(), ""

def load_municipios():
    return pd.read_csv("data/municipios.csv", dtype={"municipio_id": str, "provincia_id": str, "nombre": str})

def load_cp_mapping():
    df = pd.read_csv("data/codigos_postales_municipios.csv",
                      dtype={"codigo_postal": str, "municipio_id": str, "municipio_nombre": str})
    df["codigo_postal"] = df["codigo_postal"].str.zfill(5)
    return df


def load_idealista():
    df = pd.read_csv("data/precios_idealista.csv")
    df["municipio_nombre"] = df["municipio_nombre"].str.strip().str.lower()
    df["en_maximo_historico"] = df["variacion_maximo"].fillna(100).abs() < 0.01
    df["precio_anual_positivo"] = df["variacion_anual"].fillna(-1) > 0
    return df


def merge_idealista(cp_df, idealista_df):
    def lookup_prices(muni_str):
        munis = [m.strip().lower() for m in str(muni_str).split(", ")]
        matched = idealista_df[idealista_df["municipio_nombre"].isin(munis)]
        if matched.empty:
            return pd.Series({
                "precio_m2": None,
                "variacion_anual": None,
                "variacion_maximo": None,
                "en_maximo_historico": False,
                "precio_anual_positivo": False,
            })
        return pd.Series({
            "precio_m2": matched["precio_m2"].mean(),
            "variacion_anual": matched["variacion_anual"].mean(),
            "variacion_maximo": matched["variacion_maximo"].mean(),
            "en_maximo_historico": matched["en_maximo_historico"].any(),
            "precio_anual_positivo": matched["precio_anual_positivo"].all(),
        })

    merged = cp_df.join(
        cp_df["municipio_nombre"].apply(lookup_prices)
    )
    return merged


def normalize_name(name):
    """Normalize municipality name for matching across data sources."""
    import re
    s = name.strip().lower()
    m = re.match(r"^(.+?)\s*\((.+?)\)\s*$", s)
    if m:
        s = f"{m.group(2).strip()} {m.group(1).strip()}"
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    accents = {"á":"a","é":"e","í":"i","ó":"o","ú":"u","à":"a","è":"e","ì":"i","ò":"o","ù":"u","ü":"u","ñ":"n"}
    for a, b in accents.items():
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_names(name):
    """Return all normalized variants of a name (handles slash ordering)."""
    base = normalize_name(name)
    variants = {base}
    if "/" in base:
        parts = base.split("/")
        variants.add(f"{parts[0]}/{parts[1]}")
        variants.add(f"{parts[1]}/{parts[0]}")
    return variants


def load_mivau():
    """Load MIVAU price data, return dict normalized_name -> row."""
    df = pd.read_csv("data/precios_mivau.csv")
    df["precio_anual_positivo"] = df["variacion_anual"].fillna(-1) > 0
    mapping = {}
    for _, row in df.iterrows():
        mapping[row["nombre_normalizado"]] = row
    return df, mapping


def merge_mivau(cp_df, mivau_mapping):
    def lookup_prices(muni_str):
        munis = str(muni_str).split(", ")
        matched = []
        for m in munis:
            variants = normalize_names(m)
            for v in variants:
                if v in mivau_mapping:
                    matched.append(mivau_mapping[v])
                    break
        if not matched:
            return pd.Series({
                "precio_m2": None,
                "variacion_anual": None,
                "variacion_maximo": None,
                "en_maximo_historico": False,
                "precio_anual_positivo": False,
            })
        prices = [r["precio_m2"] for r in matched if pd.notna(r["precio_m2"])]
        vars_anual = [r["variacion_anual"] for r in matched if pd.notna(r["variacion_anual"])]
        vars_max = [r["variacion_maximo"] for r in matched if pd.notna(r["variacion_maximo"])]
        en_max = [r["en_maximo_historico"] for r in matched]
        prec_pos = [r["precio_anual_positivo"] for r in matched]
        return pd.Series({
            "precio_m2": sum(prices) / len(prices) if prices else None,
            "variacion_anual": sum(vars_anual) / len(vars_anual) if vars_anual else None,
            "variacion_maximo": sum(vars_max) / len(vars_max) if vars_max else None,
            "en_maximo_historico": any(en_max),
            "precio_anual_positivo": all(prec_pos) if prec_pos else False,
        })

    merged = cp_df.join(
        cp_df["municipio_nombre"].apply(lookup_prices)
    )
    return merged


def load_notariado():
    """Load Notariado price data (CP-level)."""
    df = pd.read_csv("data/precios_notariado.csv", dtype={"codigo_postal": str})
    df["codigo_postal"] = df["codigo_postal"].str.zfill(5)
    return df


def merge_notariado(cp_df, notariado_df):
    """Merge Notariado prices directly by codigo_postal (CP-level)."""
    notariado_map = dict(zip(notariado_df["codigo_postal"], notariado_df["precio_m2"]))

    def lookup_price(cp):
        price = notariado_map.get(cp)
        if pd.notna(price):
            return price
        return None

    cp_df["precio_m2"] = cp_df["codigo_postal"].apply(lookup_price)
    return cp_df


def merge_mivau_variacion(cp_df, mivau_mapping):
    """Fill variacion_anual/variacion_maximo from MIVAU for CPs (complements Notariado).
    Also fallback precio_m2 from MIVAU for CPs without Notariado data.
    """
    def lookup_vars(muni_str):
        munis = str(muni_str).split(", ")
        matched = []
        for m in munis:
            variants = normalize_names(m)
            for v in variants:
                if v in mivau_mapping:
                    matched.append(mivau_mapping[v])
                    break
        if not matched:
            return pd.Series({
                "variacion_anual": None,
                "variacion_maximo": None,
                "en_maximo_historico": False,
                "precio_anual_positivo": False,
            })
        vars_anual = [r["variacion_anual"] for r in matched if pd.notna(r["variacion_anual"])]
        vars_max = [r["variacion_maximo"] for r in matched if pd.notna(r["variacion_maximo"])]
        en_max = [r["en_maximo_historico"] for r in matched]
        prec_pos = [r["precio_anual_positivo"] for r in matched]
        return pd.Series({
            "variacion_anual": sum(vars_anual) / len(vars_anual) if vars_anual else None,
            "variacion_maximo": sum(vars_max) / len(vars_max) if vars_max else None,
            "en_maximo_historico": any(en_max),
            "precio_anual_positivo": all(prec_pos) if prec_pos else False,
        })

    merged = cp_df.join(
        cp_df["municipio_nombre"].apply(lookup_vars)
    )

    # Fallback precio_m2 from MIVAU for CPs without Notariado data
    for i, row in merged.iterrows():
        if pd.isna(row["precio_m2"]):
            munis = str(row["municipio_nombre"]).split(", ")
            for m in munis:
                variants = normalize_names(m)
                for v in variants:
                    if v in mivau_mapping:
                        merged.at[i, "precio_m2"] = mivau_mapping[v]["precio_m2"]
                        break
    return merged


def main():
    year_actual = 2025
    year_pasado = 2020

    print("Cargando datos de municipios y CPs...")
    municipios_df = load_municipios()
    cp_raw = load_cp_mapping()

    prov_ids = list(PROVINCES.keys())

    # --- Build unique CP -> municipio mapping (deduplicated) ---
    cp_muni = cp_raw[cp_raw["codigo_postal"] != "00000"] \
        .groupby("codigo_postal")["municipio_id"] \
        .apply(lambda x: list(set(x))) \
        .reset_index()
    cp_muni.rename(columns={"municipio_id": "municipio_ids"}, inplace=True)

    # Also build reverse: municipio -> unique CPs
    muni_cps = cp_raw[cp_raw["codigo_postal"] != "00000"] \
        .groupby("municipio_id")["codigo_postal"] \
        .apply(lambda x: list(set(x))) \
        .to_dict()

    # Filter municipios in target provinces
    target_munis = municipios_df[municipios_df["provincia_id"].isin(prov_ids)]
    target_muni_ids = set(target_munis["municipio_id"])
    muni_info = dict(zip(target_munis["municipio_id"], target_munis["nombre"]))
    muni_prov = dict(zip(target_munis["municipio_id"], target_munis["provincia_id"]))

    print(f"Total municipios en zonas objetivo: {len(muni_info)}")

    # --- Fetch population data from INE API ---
    all_pop = []
    for prov_id, (prov_name, table_id) in PROVINCES.items():
        print(f"  Descargando datos de {prov_name}...")
        try:
            data = fetch_table_data(table_id, year_pasado, year_actual)
            for serie in data:
                nombre = serie.get("Nombre", "")
                muni_name, sexo = parse_series_name(nombre)
                if sexo != "Total":
                    continue
                for dp in serie.get("Data", []):
                    all_pop.append({
                        "municipio_nombre_api": muni_name,
                        "provincia_id": prov_id,
                        "anio": dp["Anyo"],
                        "poblacion": dp["Valor"],
                    })
            time.sleep(0.3)
        except Exception as e:
            print(f"    Error: {e}", file=sys.stderr)

    pop_df = pd.DataFrame(all_pop)
    pop_pivot = pop_df.pivot_table(
        index=["provincia_id", "municipio_nombre_api"],
        columns="anio", values="poblacion", aggfunc="first"
    ).reset_index()
    pop_pivot.columns.name = None
    pop_pivot.rename(columns={year_pasado: "pob_5a", year_actual: "pob_act"}, inplace=True)
    pop_pivot["crecimiento_%"] = (
        (pop_pivot["pob_act"] - pop_pivot["pob_5a"]) / pop_pivot["pob_5a"] * 100
    ).round(2)

    print(f"Municipios con datos: {len(pop_pivot)}")

    # --- Match API names to INE municipio IDs (fuzzy) ---
    def match_muni(api_name, prov_id):
        norm = api_name.strip().lower()
        # Build set of name variants from db name (split on /)
        for mid, name in muni_info.items():
            if muni_prov.get(mid) != prov_id:
                continue
            db_norm = name.strip().lower()
            db_variants = [v.strip() for v in db_norm.split("/")]
            api_variants = [v.strip() for v in norm.split("/")]
            # Match if any variant matches
            for av in api_variants:
                for dv in db_variants:
                    if av == dv or av == dv.replace("ó", "o").replace("à", "a"):
                        return mid
        return None

    pop_pivot["municipio_id"] = pop_pivot.apply(
        lambda r: match_muni(r["municipio_nombre_api"], r["provincia_id"]), axis=1
    )

    matched = pop_pivot[pop_pivot["municipio_id"].notna()].copy()
    unmatched = pop_pivot[pop_pivot["municipio_id"].isna()]
    print(f"Match directo: {len(matched)}, Sin match: {len(unmatched)}")

    if len(unmatched) > 0:
        print("\n--- Municipios sin match ---")
        for _, r in unmatched.iterrows():
            print(f"  '{r['municipio_nombre_api']}' (prov {r['provincia_id']})")
        print()

    matched["n_cps"] = matched["municipio_id"].map(
        lambda mid: len(muni_cps.get(mid, []))
    )
    matched["pob_act_cp"] = matched["pob_act"] / matched["n_cps"].clip(lower=1)
    matched["pob_5a_cp"] = matched["pob_5a"] / matched["n_cps"].clip(lower=1)

    # --- Build CP-level results ---
    rows = []
    for _, row in matched.iterrows():
        mid = row["municipio_id"]
        cps = muni_cps.get(mid, [])
        for cp in cps:
            rows.append({
                "codigo_postal": cp,
                "municipio_id": mid,
                "municipio_nombre": muni_info.get(mid, ""),
                "provincia_id": mid[:2],
                "pob_act": row["pob_act_cp"],
                "pob_5a": row["pob_5a_cp"],
                "crecimiento_%": row["crecimiento_%"],
            })

    wide = pd.DataFrame(rows)

    # A CP can belong to multiple municipios -> group again and sum shares
    grouped = wide.groupby("codigo_postal").agg(
        municipio_nombre=("municipio_nombre", lambda x: ", ".join(sorted(set(x)))),
        provincia_id=("provincia_id", "first"),
        pob_act=("pob_act", "sum"),
        pob_5a=("pob_5a", "sum"),
        pct_crecimiento=("crecimiento_%", "mean"),
    ).reset_index()

    # Recompute growth over summed population
    grouped["crecimiento_%"] = (
        (grouped["pob_act"] - grouped["pob_5a"]) / grouped["pob_5a"] * 100
    ).round(2)

    grouped["supera_20k"] = grouped["pob_act"] > 20000
    grouped["crecimiento_positivo"] = grouped["crecimiento_%"] > 0

    prov_names = {
        "03": "Alicante/Alacant", "12": "Castellón/Castelló", "46": "Valencia/València",
        "15": "A Coruña", "27": "Lugo", "32": "Ourense", "36": "Pontevedra",
        "30": "Murcia", "43": "Tarragona",
    }
    grouped["provincia"] = grouped["provincia_id"].map(prov_names)
    grouped = grouped.sort_values("pob_act", ascending=False)

    # Try loading Notariado price data (CP-level, highest priority);
    # fall back to MIVAU (municipio-level), then idealista.
    notariado_path = Path("data/precios_notariado.csv")
    mivau_path = Path("data/precios_mivau.csv")
    idealista_path = Path("data/precios_idealista.csv")

    # Always load MIVAU for variacion_anual/variacion_maximo even when Notariado is primary
    mivau_loaded = False
    if mivau_path.exists():
        print("Loading MIVAU price data (for variación)...")
        mivau_df, mivau_mapping = load_mivau()
        mivau_loaded = True

    if notariado_path.exists():
        print("Loading NOTARIADO price data (primary source, CP-level)...")
        notariado_df = load_notariado()
        grouped = merge_notariado(grouped, notariado_df)
        # Fill in variacion/en_maximo from MIVAU for CPs where Notariado has precio_m2
        if mivau_loaded:
            grouped = merge_mivau_variacion(grouped, mivau_mapping)
            print(f"  Notariado price coverage: {grouped['precio_m2'].notna().sum()} CPs")
            print(f"  MIVAU variación coverage: {grouped['variacion_anual'].notna().sum()} CPs")
    elif mivau_loaded:
        print("Merging MIVAU price data...")
        grouped = merge_mivau(grouped, mivau_mapping)
        print(f"  MIVAU coverage: {grouped['precio_m2'].notna().sum()} CPs")
    elif idealista_path.exists():
        print("Merging idealista price data...")
        idealista_df = load_idealista()
        grouped = merge_idealista(grouped, idealista_df)
    else:
        print("WARNING: No price data found, skipping price filters")
        grouped["precio_m2"] = None
        grouped["variacion_anual"] = None
        grouped["variacion_maximo"] = None
        grouped["en_maximo_historico"] = False
        grouped["precio_anual_positivo"] = False

    # Set fuente_precio (track which source provided the price)
    notariado_has_price = notariado_path.exists() and notariado_df["precio_m2"].notna().any()
    if notariado_has_price:
        notariado_cps_with_price = set(notariado_df[notariado_df["precio_m2"].notna()]["codigo_postal"])
        grouped["fuente_precio"] = grouped["codigo_postal"].apply(
            lambda cp: "notariado" if cp in notariado_cps_with_price else ("mivau" if mivau_loaded else None)
        )
    elif mivau_loaded:
        grouped["fuente_precio"] = "mivau"
    else:
        grouped["fuente_precio"] = None

    amenity_types = ["supermercado", "colegio", "instituto", "universidad", "centro_salud"]
    amenity_path = Path("data/pois_osm.csv")
    health_path = Path("data/centros_salud.csv")
    if amenity_path.exists() and health_path.exists():
        pois = pd.read_csv(amenity_path, dtype={"codigo_postal": str})
        health = pd.read_csv(health_path, dtype={"codigo_postal": str})
        pois["codigo_postal"] = pois["codigo_postal"].str.zfill(5)
        health["codigo_postal"] = health["codigo_postal"].str.zfill(5)
        all_amenities = pd.concat([pois, health], ignore_index=True)

        for atype in amenity_types:
            cps_con = set(all_amenities[all_amenities["tipo"] == atype]["codigo_postal"])
            grouped[f"tiene_{atype}"] = grouped["codigo_postal"].isin(cps_con)

        grouped["tiene_todos_servicios"] = grouped[
            [f"tiene_{t}" for t in amenity_types]
        ].all(axis=1)
        print(f"CPs con todos los servicios: {grouped['tiene_todos_servicios'].sum()}")
    else:
        print("WARNING: Amenity data not found, skipping amenity filters")
        for atype in amenity_types:
            grouped[f"tiene_{atype}"] = False
        grouped["tiene_todos_servicios"] = False

    mercadona_path = Path("data/mercadona_cps.csv")
    if mercadona_path.exists():
        mercadona = pd.read_csv(mercadona_path, dtype={"codigo_postal": str})
        mercadona["codigo_postal"] = mercadona["codigo_postal"].str.zfill(5)
        cp_mercadona = set(mercadona[mercadona["tiene_mercadona"] == True]["codigo_postal"])
        grouped["tiene_mercadona"] = grouped["codigo_postal"].isin(cp_mercadona)
        print(f"CPs con Mercadona: {grouped['tiene_mercadona'].sum()}")
    else:
        print("WARNING: Mercadona data not found, skipping")
        grouped["tiene_mercadona"] = False

    amenity_cols = [f"tiene_{t}" for t in amenity_types] + ["tiene_todos_servicios", "tiene_mercadona"]
    cols = ["codigo_postal", "provincia", "municipio_nombre",
            "pob_act", "pob_5a", "crecimiento_%", "supera_20k", "crecimiento_positivo",
            "precio_m2", "variacion_anual", "variacion_maximo",
            "en_maximo_historico", "precio_anual_positivo", "fuente_precio"] + amenity_cols
    grouped = grouped[cols]
    grouped.columns = ["codigo_postal", "provincia", "municipio_nombre",
                       "poblacion_actual", "poblacion_hace_5a",
                       "crecimiento_%", "supera_20k", "crecimiento_positivo",
                       "precio_m2", "variacion_anual_%", "variacion_maximo_%",
                       "en_maximo_historico", "precio_anual_positivo",
                       "fuente_precio"] + amenity_cols

    print(f"\nCPs totales: {len(grouped)}")
    print(f"CPs >20K hab: {grouped['supera_20k'].sum()}")
    print(f"CPs crecimiento positivo: {grouped['crecimiento_positivo'].sum()}")

    if "precio_m2" in grouped.columns and grouped["precio_m2"].notna().any():
        filtered = grouped[
            grouped["supera_20k"]
            & grouped["crecimiento_positivo"]
            & grouped["precio_anual_positivo"]
            & ~grouped["en_maximo_historico"]
            & grouped["tiene_todos_servicios"]
        ]
    else:
        filtered = grouped[
            grouped["supera_20k"]
            & grouped["crecimiento_positivo"]
            & grouped["tiene_todos_servicios"]
        ]
    print(f"CPs cumplen TODOS los filtros: {len(filtered)}")

    grouped.to_csv("data/poblacion_por_cp_completo.csv", index=False)
    filtered.to_csv("data/poblacion_por_cp_filtrado.csv", index=False)
    print(f"\nGuardado: data/poblacion_por_cp_completo.csv ({len(grouped)} CPs)")
    print(f"Guardado: data/poblacion_por_cp_filtrado.csv ({len(filtered)} CPs)")

    if len(filtered) > 0:
        print(f"\nTop 20 CPs filtrados:")
        for _, r in filtered.head(20).iterrows():
            print(f"  {r['codigo_postal']} | {r['provincia']:20s} | "
                  f"{r['municipio_nombre'][:28]:28s} | "
                  f"Pob: {int(r['poblacion_actual']):>6d} | "
                  f"Δ: {r['crecimiento_%']:>+6.2f}%")

if __name__ == "__main__":
    main()
