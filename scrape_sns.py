from pathlib import Path

import pandas as pd

SNS_XLSX_URL = (
    "https://www.sanidad.gob.es/estadEstudios/estadisticas/"
    "docs/siap/2026_C_Catal_Centros_AP.xlsx"
)

TARGET_PROVINCES = {
    "Alicante/Alacant", "Alacant", "Alicante",
    "Castellón/Castelló", "Castellón", "Castelló",
    "Valencia/València", "Valencia", "València",
    "A Coruña", "Coruña, A",
    "Lugo",
    "Ourense",
    "Pontevedra",
    "Murcia",
    "Tarragona",
}

TARGET_CP_PREFIXES = {"03", "12", "46", "15", "27", "32", "36", "30", "43"}

PUBLIC_KEYWORDS = [
    "SERVICIO ANDALUZ DE SALUD",
    "SERVICIO ARAGONÉS DE SALUD",
    "SERVICIO DE SALUD DEL PRINCIPADO DE ASTURIAS",
    "SERVICIO DE SALUD DE ILLES BALEARS",
    "SERVICIO CANARIO DE SALUD",
    "SERVICIO CÁNTABRO DE SALUD",
    "SERVICIO DE SALUD DE CASTILLA-LA MANCHA",
    "SERVICIO DE SALUD DE CASTILLA Y LEÓN",
    "SERVICIO CATALÁN DE SALUD",
    "SERVICIO MADRILEÑO DE SALUD",
    "SERVICIO NAVARRO DE SALUD",
    "SERVICIO GALLEGO DE SALUD",
    "SERVICIO MURCIANO DE SALUD",
    "SERVICIO VALENCIANO DE SALUD",
    "SERVICIO EXTREMEÑO DE SALUD",
    "SERVICIO RIOJANO DE SALUD",
    "SERVICIO VASCO DE SALUD",
    "SERVICIO DE SALUD",
    "SALUD",
    "CONSELLERIA",
    "CONSELLERÍA",
    "GERENCIA",
    "SERGAS",
    "SERVICIO GALLEGO DE SAÚDE",
    "OSAKIDETZA",
    "SERVICIO MURCIANO DE SALUD",
    "CONSEJERÍA DE SANIDAD",
    "CONSELLERIA DE SANITAT",
    "INSTITUT CATALÀ DE LA SALUT",
    "GENERALITAT",
    "XUNTA",
    "GOBIERNO",
    "Pública",
    "Pública Directa",
]


def is_public(row):
    gestion = str(row.get("D_GESTION", "")).upper()
    tnombre = str(row.get("T_NOMBRE", "")).upper()
    combined = gestion + " " + tnombre
    for kw in PUBLIC_KEYWORDS:
        if kw.upper() in combined:
            return True
    return False


def is_target_province(row):
    prov = str(row.get("SIAP_PROVINCIAS.NOMBRE", "")).strip()
    for target in TARGET_PROVINCES:
        if prov.upper() == target.upper():
            return True
        if prov.upper().startswith(target.upper()):
            return True
        if target.upper().startswith(prov.upper()):
            return True
    return False


def scrape():
    print(f"Downloading SNS catalog from {SNS_XLSX_URL}...", flush=True)
    df = pd.read_excel(SNS_XLSX_URL, sheet_name="Catálogo - 2026")
    print(f"Total centers: {len(df)}", flush=True)

    df["CP"] = df["CP"].astype(str).str.strip().str.zfill(5)

    target = df[df["CP"].str[:2].isin(TARGET_CP_PREFIXES)]
    print(f"Target province CPs: {len(target)}", flush=True)

    public_mask = target.apply(is_public, axis=1)
    public = target[public_mask]
    print(f"Public centers: {len(public)}", flush=True)

    records = []
    for _, row in public.iterrows():
        records.append({
            "codigo_postal": row["CP"],
            "tipo": "centro_salud",
            "nombre": str(row.get("SIAP_CENTROS.NOMBRE", "")),
        })

    out_path = Path("data/centros_salud.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df = pd.DataFrame(records)
    out_df.to_csv(out_path, index=False)

    print(f"\nSaved {len(records)} centers to {out_path}", flush=True)
    print(f"Unique CPs: {out_df['codigo_postal'].nunique()}", flush=True)


if __name__ == "__main__":
    scrape()
