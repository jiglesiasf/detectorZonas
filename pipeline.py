import json
import pandas as pd
import requests
import time
import sys

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

    cols = ["codigo_postal", "provincia", "municipio_nombre",
            "pob_act", "pob_5a", "crecimiento_%", "supera_20k", "crecimiento_positivo"]
    grouped = grouped[cols]
    grouped.columns = ["codigo_postal", "provincia", "municipio_nombre",
                       "poblacion_actual", "poblacion_hace_5a",
                       "crecimiento_%", "supera_20k", "crecimiento_positivo"]

    print(f"\nCPs totales: {len(grouped)}")
    print(f"CPs >20K hab: {grouped['supera_20k'].sum()}")
    print(f"CPs crecimiento positivo: {grouped['crecimiento_positivo'].sum()}")

    filtered = grouped[grouped["supera_20k"] & grouped["crecimiento_positivo"]]
    print(f"CPs cumplen AMBOS: {len(filtered)}")

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
