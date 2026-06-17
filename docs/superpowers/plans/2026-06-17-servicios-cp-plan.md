# Servicios por CP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add amenity filters (supermarket, school, high school, university, health center) to the CP pipeline using OSM Overpass API and SNS catalog data.

**Architecture:** Two new scraper scripts fetch POI data from Overpass API and SNS catalog. Pipeline.py loads both CSVs, merges by CP, adds boolean columns, and filters. HTML viewer adds amenity checkboxes and badges.

**Tech Stack:** Python, Overpass API, pandas, requests.

## Global Constraints

- Preserve all existing pipeline functionality and output files
- All new data goes in `data/` directory
- Follow existing code style: no comments, concise, direct
- Overpass API queries use `[out:json]` format, timeout 60s
- Supermarket names list: Mercadona, Carrefour, Alcampo, Gadis, Eroski, Consum

---

### Task 1: `scrape_osm_pois.py` — Overpass API scraper

**Files:**
- Create: `scrape_osm_pois.py`
- Output: `data/pois_osm.csv`

**Interfaces:**
- Produces: `data/pois_osm.csv` with columns `codigo_postal`, `tipo`, `nombre`

- [ ] **Step 1: Write `scrape_osm_pois.py`**

```python
import csv
import json
import re
import sys
import time
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# (provincia_name in OSM, provincia_id)
PROVINCES = [
    ("Alicante/Alacant", "03"),
    ("Castellón/Castelló", "12"),
    ("Valencia/València", "46"),
    ("A Coruña", "15"),
    ("Lugo", "27"),
    ("Ourense", "32"),
    ("Pontevedra", "36"),
    ("Murcia", "30"),
    ("Tarragona", "43"),
]

SUPERMARKET_NAMES = "Mercadona|Carrefour|Alcampo|Gadis|Eroski|Consum"

QUERIES = {
    "supermercado": f"""
[out:json];
area["name"="{{prov}}"]["admin_level"="6"]->.a;
node(area.a)[shop=supermarket][name~"{SUPERMARKET_NAMES}"];
out center;
""",
    "colegio": """
[out:json];
area["name"="{prov}"]["admin_level"="6"]->.a;
node(area.a)[amenity=school];
out center;
""",
    "instituto": """
[out:json];
area["name"="{prov}"]["admin_level"="6"]->.a;
node(area.a)[amenity=school][school=secondary];
out center;
""",
    "universidad": """
[out:json];
area["name"="{prov}"]["admin_level"="6"]->.a;
node(area.a)[amenity=university];
out center;
""",
}


def query_overpass(query):
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def extract_cp(tags):
    for key in ("addr:postcode", "postcode", "addr:post_code"):
        val = tags.get(key, "")
        if val:
            return val.strip().zfill(5)
    return ""


def scrape():
    all_pois = []
    total = len(PROVINCES) * len(QUERIES)
    done = 0

    for prov_name, prov_id in PROVINCES:
        # Try OSM name variants for dual names
        prov_variants = [prov_name]
        if "/" in prov_name:
            parts = prov_name.split("/")
            prov_variants.append(f"{parts[1]}/{parts[0]}")

        for tipo, query_template in QUERIES.items():
            results = None
            for variant in prov_variants:
                q = query_template.format(prov=variant)
                try:
                    results = query_overpass(q)
                    if results and len(results.get("elements", [])) > 0:
                        break
                except requests.RequestException:
                    continue

            if not results:
                done += 1
                continue

            for el in results.get("elements", []):
                tags = el.get("tags", {})
                cp = extract_cp(tags)
                if not cp:
                    continue
                all_pois.append({
                    "codigo_postal": cp,
                    "tipo": tipo,
                    "nombre": tags.get("name", ""),
                })

            done += 1
            print(f"  [{done}/{total}] {prov_name} - {tipo}: {len(results.get('elements', []))} POIs")
            time.sleep(1)

    out_path = Path("data/pois_osm.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["codigo_postal", "tipo", "nombre"])
        writer.writeheader()
        writer.writerows(all_pois)

    print(f"\nSaved {len(all_pois)} POIs to {out_path}")
    cps = set(p["codigo_postal"] for p in all_pois)
    print(f"Unique CPs: {len(cps)}")
    for tipo in ("supermercado", "colegio", "instituto", "universidad"):
        count = sum(1 for p in all_pois if p["tipo"] == tipo)
        print(f"  {tipo}: {count}")


if __name__ == "__main__":
    scrape()
```

- [ ] **Step 2: Run it and verify output**

```bash
python scrape_osm_pois.py
```

Expected: Output CSV with POIs per province, saved to `data/pois_osm.csv`

- [ ] **Step 3: Commit**

```bash
git add scrape_osm_pois.py data/pois_osm.csv
git commit -m "feat: add OSM POI scraper for amenity data"
```

---

### Task 2: `scrape_sns.py` — SNS health centers scraper

**Files:**
- Create: `scrape_sns.py`
- Output: `data/centros_salud.csv`

**Interfaces:**
- Produces: `data/centros_salud.csv` with columns `codigo_postal`, `tipo`, `nombre`

- [ ] **Step 1: Write `scrape_sns.py`**

The SNS catalog is available at the Ministerio de Sanidad website. Two sources:
- Catálogo de Centros de Atención Primaria del SNS (CSV)
- REGCESS (Registro General de Centros, Servicios y Establecimientos Sanitarios)

```python
import csv
from pathlib import Path

import requests
import pandas as pd

SNS_PRIMARY_CARE_URL = (
    "https://www.msps.es/estadEstudios/estadisticas/"
    "sisInfSanSNS/UltDatos/CentrosAtencionPrimaria.csv"
)

OUTPUT = "data/centros_salud.csv"


def scrape():
    headers = {"User-Agent": "Mozilla/5.0"}
    print(f"Downloading SNS primary care centers from {SNS_PRIMARY_CARE_URL}...")

    try:
        resp = requests.get(SNS_PRIMARY_CARE_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        print(f"Downloaded {len(lines)} lines")

        reader = csv.DictReader(lines, delimiter=";")
        records = []
        for row in reader:
            cp = row.get("CODIGO_POSTAL", "").strip().zfill(5)
            nombre = row.get("NOMBRE_CENTRO", row.get("NOMBRE", "")).strip()
            if cp and len(cp) == 5 and cp != "00000":
                records.append({
                    "codigo_postal": cp,
                    "tipo": "centro_salud",
                    "nombre": nombre,
                })
        print(f"Extracted {len(records)} centers with CP")

    except Exception as e:
        print(f"Primary care download failed: {e}")
        print("Trying REGCESS fallback...")
        records = _fallback_regcess()

    out_path = Path(OUTPUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["codigo_postal", "tipo", "nombre"])
        writer.writeheader()
        writer.writerows(records)

    print(f"\nSaved {len(records)} health centers to {OUTPUT}")


def _fallback_regcess():
    """Fallback: try REGCESS Excel download from datos.gob.es."""
    records = []
    print("  Searching datos.gob.es for SNS datasets...")
    search_url = "https://datos.gob.es/apidata/catalog/dataset?q=centros+atenci%C3%B3n+primaria+SNS&title=SNS"
    try:
        resp = requests.get(search_url, headers={"Accept": "application/json"}, timeout=30)
        data = resp.json()
        # Extract first dataset distribution URL with CSV
        for result in data.get("result", {}).get("items", []):
            for dist in result.get("distribution", []):
                url = dist.get("accessURL", dist.get("downloadURL", ""))
                if "csv" in url.lower():
                    print(f"  Found: {url}")
                    resp2 = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                    lines = resp2.text.splitlines()
                    reader = csv.DictReader(lines, delimiter=",")
                    for row in reader:
                        cp = row.get("codigo_postal", row.get("CP", "")).strip().zfill(5)
                        if cp and len(cp) == 5 and cp != "00000":
                            records.append({
                                "codigo_postal": cp,
                                "tipo": "centro_salud",
                                "nombre": row.get("nombre", row.get("centro", "")).strip(),
                            })
                    break
            if records:
                break
    except Exception as e:
        print(f"  Fallback failed: {e}")
    return records


if __name__ == "__main__":
    scrape()
```

- [ ] **Step 2: Investigate and verify the actual SNS CSV download URL**

The download page likely has a direct CSV link. Try scraping the page to find it:

```bash
python -c "
import requests, re
url = 'https://www.msps.es/ciudadanos/centros.do?metodo=modalidadGestion'
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
# Find CSV links
for m in re.finditer(r'href=[\"\\']([^\"\\']+\.(csv|CSV)[^\"\\']*)[\"\\']', resp.text):
    print(m.group(1))
# Also check the UltDatos page
url2 = 'http://www.msps.es/estadEstudios/estadisticas/sisInfSanSNS/UltDatos.htm'
resp2 = requests.get(url2, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
# Find links
import re
for m in re.finditer(r'href=[\"\\']([^\"\\']*(csv|CSV|centro)[^\"\\']*)[\"\\']', resp2.text, re.I):
    print(m.group(1))
"
```

If no CSV download link is found, use the datos.gob.es search API:
```python
# Alternative: search datos.gob.es for SNS datasets
search_url = "https://datos.gob.es/apidata/catalog/dataset?q=centros+atenci%C3%B3n+primaria+SNS&title=SNS"
resp = requests.get(search_url, headers={"Accept": "application/json"}, timeout=30)
print(resp.json())
```
Update the SNS_PRIMARY_CARE_URL in scrape_sns.py with the actual download URL found.

- [ ] **Step 3: Run and verify**

```bash
python scrape_sns.py
```

Expected: Output CSV with health centers, saved to `data/centros_salud.csv`

- [ ] **Step 4: Commit**

```bash
git add scrape_sns.py data/centros_salud.csv
git commit -m "feat: add SNS health centers scraper"
```

---

### Task 3: Modify `pipeline.py` — Integrate amenity data

**Files:**
- Modify: `pipeline.py` (after price block, before final filtering)

**Interfaces:**
- Consumes: `data/pois_osm.csv`, `data/centros_salud.csv` (from Tasks 1 & 2)
- Produces: Updated `data/poblacion_por_cp_completo.csv` and `data/poblacion_por_cp_filtrado.csv` with amenity columns

- [ ] **Step 1: Add amenity loading and merge after the price block (after line ~315)**

Find the line:
```python
    cols = ["codigo_postal", "provincia", "municipio_nombre",
```

Replace with amenity loading before that:

After this block (around line 316, before `cols = ...`):
```python
    # --- Load amenity data (OSM POIs + SNS health centers) ---
    amenity_path = Path("data/pois_osm.csv")
    health_path = Path("data/centros_salud.csv")
    amenity_types = ["supermercado", "colegio", "instituto", "universidad", "centro_salud"]

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

    cols = ["codigo_postal", "provincia", "municipio_nombre",
```

- [ ] **Step 2: Update the columns list and rename to include new columns**

In the `cols` list (around line 317):
```python
    cols = ["codigo_postal", "provincia", "municipio_nombre",
            "pob_act", "pob_5a", "crecimiento_%", "supera_20k", "crecimiento_positivo",
            "precio_m2", "variacion_anual", "variacion_maximo",
            "en_maximo_historico", "precio_anual_positivo"]
    grouped = grouped[cols]
    grouped.columns = ["codigo_postal", "provincia", "municipio_nombre",
                       "poblacion_actual", "poblacion_hace_5a",
                       "crecimiento_%", "supera_20k", "crecimiento_positivo",
                       "precio_m2", "variacion_anual_%", "variacion_maximo_%",
                       "en_maximo_historico", "precio_anual_positivo"]
```

Replace with:
```python
    amenity_cols = [f"tiene_{t}" for t in amenity_types] + ["tiene_todos_servicios"]
    cols = ["codigo_postal", "provincia", "municipio_nombre",
            "pob_act", "pob_5a", "crecimiento_%", "supera_20k", "crecimiento_positivo",
            "precio_m2", "variacion_anual", "variacion_maximo",
            "en_maximo_historico", "precio_anual_positivo"] + amenity_cols
    grouped = grouped[cols]
    grouped.columns = ["codigo_postal", "provincia", "municipio_nombre",
                       "poblacion_actual", "poblacion_hace_5a",
                       "crecimiento_%", "supera_20k", "crecimiento_positivo",
                       "precio_m2", "variacion_anual_%", "variacion_maximo_%",
                       "en_maximo_historico", "precio_anual_positivo"] + amenity_cols
```

- [ ] **Step 3: Add `tiene_todos_servicios` to the filter condition**

Find the filter block (around line 332):
```python
    if "precio_m2" in grouped.columns and grouped["precio_m2"].notna().any():
        filtered = grouped[
            grouped["supera_20k"]
            & grouped["crecimiento_positivo"]
            & grouped["precio_anual_positivo"]
            & ~grouped["en_maximo_historico"]
        ]
    else:
        filtered = grouped[grouped["supera_20k"] & grouped["crecimiento_positivo"]]
```

Replace with:
```python
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
```

- [ ] **Step 4: Run the pipeline and verify**

```bash
python pipeline.py
```

Expected: Pipeline runs, output files include new amenity columns.

```bash
python -c "
import pandas as pd
df = pd.read_csv('data/poblacion_por_cp_completo.csv')
print('Columns:', list(df.columns))
print('Has amenity cols:', all(c in df.columns for c in ['tiene_supermercado', 'tiene_colegio', 'tiene_instituto', 'tiene_universidad', 'tiene_centro_salud', 'tiene_todos_servicios']))
df2 = pd.read_csv('data/poblacion_por_cp_filtrado.csv')
print('Filtered rows:', len(df2))
if len(df2) > 0:
    print('All have servicios:', df2['tiene_todos_servicios'].all())
"
```

- [ ] **Step 5: Commit**

```bash
git add pipeline.py
git commit -m "feat: integrate amenity filters into pipeline"
```

---

### Task 4: Modify `build_html.py` — Add amenity filters to viewer

**Files:**
- Modify: `build_html.py`

- [ ] **Step 1: Add 6 new fields to each record in the JSON data block**

Find the record creation loop:
```python
records.append({
    "cp": row["codigo_postal"],
    ...
    "precPos": bool(row["precio_anual_positivo"]) if pd.notna(row.get("precio_anual_positivo")) else False,
})
```

Add after "precPos":
```python
    "sup": bool(row.get("tiene_supermercado", False)),
    "col": bool(row.get("tiene_colegio", False)),
    "inst": bool(row.get("tiene_instituto", False)),
    "uni": bool(row.get("tiene_universidad", False)),
    "cs": bool(row.get("tiene_centro_salud", False)),
    "todos": bool(row.get("tiene_todos_servicios", False)),
```

- [ ] **Step 2: Add 6 amenity checkboxes to the filters bar**

Find the filter div and add after the "No en máximo histórico" checkbox:
```html
<label><input type="checkbox" id="filterSup" checked onchange="render()"> <span>Supermercado</span></label>
<label><input type="checkbox" id="filterCol" checked onchange="render()"> <span>Colegio</span></label>
<label><input type="checkbox" id="filterInst" checked onchange="render()"> <span>Instituto</span></label>
<label><input type="checkbox" id="filterUni" checked onchange="render()"> <span>Universidad</span></label>
<label><input type="checkbox" id="filterCS" checked onchange="render()"> <span>Centro Salud</span></label>
<label><input type="checkbox" id="filterTodos" checked onchange="render()"> <span>Todos servicios</span></label>
```

- [ ] **Step 3: Add filter logic in render()**

In the filter condition, add after the q/NoMax block:
```javascript
const fSup = document.getElementById('filterSup').checked;
const fCol = document.getElementById('filterCol').checked;
const fInst = document.getElementById('filterInst').checked;
const fUni = document.getElementById('filterUni').checked;
const fCS = document.getElementById('filterCS').checked;
const fTodos = document.getElementById('filterTodos').checked;

// ...in the items.filter lambda:
if (fSup && !d.sup) return false;
if (fCol && !d.col) return false;
if (fInst && !d.inst) return false;
if (fUni && !d.uni) return false;
if (fCS && !d.cs) return false;
if (fTodos && !d.todos) return false;
```

- [ ] **Step 4: Add amenity badges to the badges section**

Find the badges display and add after the max badge:
```javascript
if (d.sup) badges.push('<span class="badge badge-both">Super</span>');
if (d.col) badges.push('<span class="badge badge-both">Cole</span>');
if (d.inst) badges.push('<span class="badge badge-both">Inst</span>');
if (d.uni) badges.push('<span class="badge badge-both">Univ</span>');
if (d.cs) badges.push('<span class="badge badge-both">CS</span>');
```

Add a new badge style:
```css
.badge-amenity{background:#e8f5e9;color:#2e7d32}
```

- [ ] **Step 5: Run and verify**

```bash
python build_html.py
```

Verify the HTML renders correctly by opening `docs/visor-cps.html`.

- [ ] **Step 6: Commit**

```bash
git add build_html.py docs/visor-cps.html
git commit -m "feat: add amenity filters to HTML viewer"
```

---

### Task 5: Add tests to `test_pipeline.py`

**Files:**
- Modify: `test_pipeline.py`

- [ ] **Step 1: Add test for amenity columns existence**

```python
def test_complete_has_amenity_columns(self):
    df = pd.read_csv(self.complete_path)
    amenity_cols = ["tiene_supermercado", "tiene_colegio", "tiene_instituto",
                    "tiene_universidad", "tiene_centro_salud", "tiene_todos_servicios"]
    for col in amenity_cols:
        self.assertIn(col, df.columns, f"Missing column: {col}")
```

- [ ] **Step 2: Add test for filtered only has amenity-positive rows**

```python
def test_filtered_has_all_services(self):
    df = pd.read_csv(self.filtered_path)
    if len(df) > 0:
        self.assertTrue((df["tiene_todos_servicios"] == True).all())
```

- [ ] **Step 3: Add test for amenity column types**

```python
def test_amenity_columns_are_bool(self):
    df = pd.read_csv(self.complete_path)
    amenity_cols = ["tiene_supermercado", "tiene_colegio", "tiene_instituto",
                    "tiene_universidad", "tiene_centro_salud", "tiene_todos_servicios"]
    valid = df.dropna(subset=amenity_cols)
    if len(valid) > 0:
        for col in amenity_cols:
            self.assertTrue(valid[col].isin([True, False]).all(),
                            f"Column {col} has non-boolean values")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest test_pipeline.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add test_pipeline.py
git commit -m "test: add amenity column tests"
```
