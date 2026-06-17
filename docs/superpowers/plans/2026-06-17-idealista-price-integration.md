# Integración Precios idealista — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add housing price trend data from idealista's price report as additional zone quality filters.

**Architecture:** A new Playwright-based scraper (`scrape_idealista.py`) discovers idealista's internal API and extracts price/m2 by municipality. The existing `pipeline.py` merges this with population data and applies new filters (positive annual price change, not at historical maximum). The HTML viewer (`build_html.py`) shows new columns and filter controls.

**Tech Stack:** Python 3.10+, pandas, requests, playwright (new dependency)

## Global Constraints

- Rate limit idealista API calls: 1 request/second minimum, exponential backoff on 429/503 (2s, 4s, 8s, 16s, max 5 retries), ±0.5s jitter
- All existing flags (`supera_20k`, `crecimiento_positivo`) must continue working
- CP-level aggregation must remain the unit of output
- No breaking changes to existing CSV column names

---

### Task 1: Set up Playwright dependency

**Files:**
- Modify: `requirements.txt` (if it exists) / install globally

- [ ] **Step 1: Check if requirements file exists**

```bash
ls -la requirements.txt 2>/dev/null || echo "no requirements.txt"
```

- [ ] **Step 2: Install playwright and sync browser**

```bash
pip install playwright && playwright install chromium
```

- [ ] **Step 3: Verify playwright works**

```bash
python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
```
Expected: `playwright OK`

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "chore: add playwright dependency"
```

---

### Task 2: Create scrape_idealista.py — API discovery and extraction

**Files:**
- Create: `scrape_idealista.py`
- Output: `data/precios_idealista.csv`

**Interfaces:**
- Consumes: `TARGET_PROVINCES` list from `pipeline.py` (copy in `scrape_idealista.py`)
- Produces: `discover_api(target_provinces)` → `{session, api_pattern, headers, location_mapping}`
- Produces: `fetch_municipio_price(muni_name, api_config)` → `{municipio_nombre, precio_m2, ...}`
- Produces: `scrape_all(target_munis, target_provinces)` → `list[dict]` with keys `municipio_nombre, precio_m2, variacion_mensual, variacion_trimestral, variacion_anual, maximo_historico, variacion_maximo, mes_referencia`

- [ ] **Step 1: Write `scrape_idealista.py` skeleton with CLI argument handling**

```python
import argparse
import csv
import json
import random
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


API_BASE = "https://www.idealista.com/sala-de-prensa/informes-precio-vivienda"


def discover_api() -> dict:
    """Open idealista page with Playwright, intercept XHR to discover the internal API pattern.
    
    Returns a dict with:
      - session: requests.Session with cookies from Playwright
      - api_url_template: str with {location_id} placeholder
      - headers: dict of required request headers
    """
    raise NotImplementedError("Task 2 step 2")


def fetch_municipio_price(muni_name: str, api_config: dict) -> dict:
    """Fetch price data for a single municipality via the discovered API.
    
    Args:
        muni_name: Municipality name as string
        api_config: Config dict from discover_api()
    
    Returns:
        dict with keys: municipio_nombre, precio_m2, variacion_mensual, 
        variacion_trimestral, variacion_anual, maximo_historico, 
        variacion_maximo, mes_referencia
    
    Raises:
        requests.HTTPError on non-2xx
    """
    raise NotImplementedError("Task 2 step 3")


def scrape_all(target_munis: list[str]) -> list[dict]:
    """Scrape price data for all target municipalities.
    
    Args:
        target_munis: List of municipality names to scrape
    
    Returns:
        List of price data dicts
    """
    raise NotImplementedError("Task 2 step 4")


def main():
    parser = argparse.ArgumentParser(description="Scrape idealista housing prices")
    parser.add_argument("--input", default="data/poblacion_por_cp_completo.csv",
                        help="CSV with municipio_nombre column")
    parser.add_argument("--output", default="data/precios_idealista.csv",
                        help="Output CSV path")
    parser.add_argument("--rate-limit", type=float, default=1.0,
                        help="Seconds between API calls")
    args = parser.parse_args()
    # TODO: implement
    print(f"Output will be saved to: {args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement `discover_api()`**

This is the most complex function. Strategy:
1. Launch Playwright (headless Chromium), set up request interception
2. Open the idealista price report page at `/venta/` (sale tab)
3. Wait for page to load. Extract the data-loading API URL pattern from XHRs
4. Read all province dropdown values → build province mapping {name: value}
5. For the first relevant province, select it, wait for municipality dropdown to populate
6. Read all municipality dropdown values → build municipio mapping {name: value}
7. Select a municipality, capture the XHR that returns price JSON data
8. Extract cookies, headers, URL pattern
9. Return config with session, api_pattern, headers, and location_mapping

```python
def discover_api(target_provinces: list[str]) -> dict:
    """Discover idealista's internal price API.

    Returns:
        dict with keys:
          - session: requests.Session primed with cookies
          - api_pattern: str, the API URL template with {location_id} placeholder
          - headers: dict of required headers
          - location_mapping: dict[str, str] mapping normalized muni names → IDs
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        captured_url = None
        captured_headers = None
        location_mapping = {}

        def intercept(response):
            nonlocal captured_url, captured_headers
            if response.ok and "/data/" in response.url and "price" in response.url.lower():
                if "json" in response.headers.get("content-type", ""):
                    captured_url = response.url
                    captured_headers = response.request.headers

        page.on("response", intercept)
        page.goto(API_BASE, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # --- Build location mapping from dropdowns ---
        # Provinces
        prov_select = page.locator("select").first
        prov_options = prov_select.locator("option").all()
        for opt in prov_options:
            val = opt.get_attribute("value")
            text = opt.inner_text().strip()
            if val and text:
                location_mapping[f"prov:{text.lower()}"] = val

        # Select first relevant province to trigger municipio loading
        for prov_name_lower in target_provinces:
            key = f"prov:{prov_name_lower}"
            if key in location_mapping:
                prov_select.select_option(location_mapping[key])
                time.sleep(2)
                break
        else:
            # Fallback: first province with options
            for opt in prov_options:
                val = opt.get_attribute("value")
                if val:
                    prov_select.select_option(val)
                    time.sleep(2)
                    break

        # Municipalities
        muni_select = page.locator("select").nth(1)
        muni_options = muni_select.locator("option").all()
        for opt in muni_options:
            val = opt.get_attribute("value")
            text = opt.inner_text().strip()
            if val and text and val != muni_select.get_attribute("value"):
                location_mapping[f"muni:{text.lower()}"] = val

        # Select first non-empty municipality to trigger price API call
        for opt in muni_options:
            val = opt.get_attribute("value")
            if val and val != muni_select.get_attribute("value"):
                muni_select.select_option(val)
                time.sleep(2)
                break

        # Capture cookies before closing
        cookies = context.cookies()
        browser.close()

    if not captured_url:
        raise RuntimeError("Could not discover idealista API endpoint")

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"])

    # Extract pattern: replace the specific location ID with {location_id}
    # The URL will contain the selected municipio's ID - we replace it
    api_pattern = captured_url

    return {
        "session": session,
        "api_pattern": api_pattern,
        "headers": {k: v for k, v in captured_headers.items()
                    if k.lower() in ("accept", "content-type", "x-requested-with",
                                     "user-agent", "referer")},
        "location_mapping": location_mapping,
    }
```

- [ ] **Step 3: Implement `fetch_municipio_price()`**

```python
def fetch_municipio_price(muni_name: str, api_config: dict) -> dict:
    """Fetch price data for a municipality via the discovered idealista API.

    Uses the location_mapping from discover_api() to find the correct
    location ID and constructs the API URL accordingly.

    The API response format is unknown until discovery, so we adapt to
    whatever shape the discovered API returns.
    """
    session = api_config["session"]
    headers = api_config["headers"]
    mapping = api_config["location_mapping"]

    # Look up municipio ID from mapping
    muni_key = f"muni:{muni_name.strip().lower()}"
    loc_id = mapping.get(muni_key)
    if not loc_id:
        # Try matching by partial name
        for key, val in mapping.items():
            if key.startswith("muni:") and muni_key[5:] in key:
                loc_id = val
                break

    if not loc_id:
        raise ValueError(f"No location ID found for {muni_name}")

    # Construct URL: replace the location ID in the discovered pattern
    # The discovered URL might look like:
    #   .../data/api/venta?locationId=XYZ&type=sale
    # We need to find and replace the location ID
    import re
    api_pattern = api_config["api_pattern"]
    # Find any existing location ID in the pattern (a short alphanumeric string)
    existing_ids = set(mapping.values())
    # Replace the first matching ID in the URL
    for eid in sorted(existing_ids, key=len, reverse=True):
        if eid in api_pattern:
            url = api_pattern.replace(eid, loc_id)
            break
    else:
        # If we can't find the ID in the URL, append as query param
        separator = "&" if "?" in api_pattern else "?"
        url = f"{api_pattern}{separator}locationId={loc_id}"

    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Extract values adapting to the actual response shape
    # If data is a list, take first element
    if isinstance(data, list):
        data = data[0] if data else {}

    return {
        "municipio_nombre": muni_name,
        "precio_m2": data.get("price", 0),
        "variacion_mensual": data.get("monthlyVariation"),
        "variacion_trimestral": data.get("quarterlyVariation"),
        "variacion_anual": data.get("annualVariation"),
        "maximo_historico": data.get("historicalMax"),
        "variacion_maximo": data.get("maxVariation"),
        "mes_referencia": data.get("referenceMonth"),
    }
```

- [ ] **Step 4: Implement `scrape_all()` with rate limiting**

```python
def scrape_all(target_munis: list[str], target_provinces: list[str]) -> list[dict]:
    print("Discovering idealista API...")
    api_config = discover_api(target_provinces)
    print(f"API discovered: {api_config['api_pattern']}")

    results = []
    total = len(target_munis)
    for i, muni in enumerate(target_munis, 1):
        try:
            data = fetch_municipio_price(muni, api_config)
            results.append(data)
            print(f"  [{i}/{total}] {muni}: {data.get('precio_m2', 'N/A')} €/m2")
        except Exception as e:
            print(f"  [{i}/{total}] {muni}: ERROR - {e}")
            results.append({
                "municipio_nombre": muni,
                "precio_m2": None,
                "variacion_mensual": None,
                "variacion_trimestral": None,
                "variacion_anual": None,
                "maximo_historico": None,
                "variacion_maximo": None,
                "mes_referencia": None,
            })
        # Rate limiting with jitter
        delay = 1.0 + random.uniform(-0.5, 0.5)
        time.sleep(max(0.1, delay))

    return results
```

- [ ] **Step 5: Implement `main()` to wire everything together**

```python
TARGET_PROVINCES = [
    "alicante/alacant", "castellón/castelló", "valencia/valència",
    "a coruña", "lugo", "ourense", "pontevedra",
    "murcia", "tarragona",
]


def extract_municipios_from_csv(csv_path: str) -> list[str]:
    import pandas as pd
    df = pd.read_csv(csv_path)
    munis = set()
    for names in df["municipio_nombre"].str.split(", "):
        for n in names:
            munis.add(n.strip())
    return sorted(munis)


def main():
    parser = argparse.ArgumentParser(description="Scrape idealista housing prices")
    parser.add_argument("--input", default="data/poblacion_por_cp_completo.csv",
                        help="CSV with municipio_nombre column")
    parser.add_argument("--output", default="data/precios_idealista.csv",
                        help="Output CSV path")
    parser.add_argument("--rate-limit", type=float, default=1.0,
                        help="Seconds between API calls")
    args = parser.parse_args()

    print("Extracting unique municipios from input...")
    munis = extract_municipios_from_csv(args.input)
    print(f"Found {len(munis)} unique municipios to scrape")

    results = scrape_all(munis, TARGET_PROVINCES)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "municipio_nombre", "precio_m2", "variacion_mensual",
            "variacion_trimestral", "variacion_anual", "maximo_historico",
            "variacion_maximo", "mes_referencia",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"Saved {len(results)} records to {out_path}")

    success = sum(1 for r in results if r["precio_m2"] is not None)
    print(f"Successful: {success}/{len(results)}")
```

- [ ] **Step 6: Run a quick smoke test**

```bash
python scrape_idealista.py --input data/poblacion_por_cp_completo.csv --output data/precios_idealista_test.csv --rate-limit 0.5
```
Expected: Script runs, outputs some records (at least a few successful).

- [ ] **Step 7: Commit**

```bash
git add scrape_idealista.py
git commit -m "feat: add idealista price scraper with API discovery"
```

---

### Task 3: Modify pipeline.py to merge price data and apply new filters

**Files:**
- Modify: `pipeline.py`
- Modify: `data/poblacion_por_cp_completo.csv` (regenerated with new columns)
- Modify: `data/poblacion_por_cp_filtrado.csv` (regenerated with new filter logic)

**Interfaces:**
- Consumes: `data/precios_idealista.csv` (from Task 2)
- Modifies: `main()` in `pipeline.py` to call new merge function

- [ ] **Step 1: Read current pipeline.py fully**

```bash
cat -n pipeline.py
```
Confirm the file layout.

- [ ] **Step 2: Add `load_idealista()` function (after line 40, before `main()`)**

```python
def load_idealista():
    df = pd.read_csv("data/precios_idealista.csv")
    df["municipio_nombre"] = df["municipio_nombre"].str.strip().str.lower()
    df["en_maximo_historico"] = df["variacion_maximo"].fillna(100).abs() < 0.01
    df["precio_anual_positivo"] = df["variacion_anual"].fillna(-1) > 0
    return df
```

- [ ] **Step 3: Add `merge_idealista()` function (after `load_idealista()`)**

```python
def merge_idealista(cp_df, idealista_df):
    """Merge idealista price data into CP dataframe by matching municipality names."""
    def lookup_prices(muni_str):
        """Look up price data for a CP's comma-separated municipio list."""
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
        # If multiple municipios match a CP, take the mean
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
```

- [ ] **Step 4: Add new columns to the output in `main()`**

After line 188 where `grouped` is built, add:

```python
# Load and merge idealista price data
if Path("data/precios_idealista.csv").exists():
    print("Merging idealista price data...")
    idealista_df = load_idealista()
    grouped = merge_idealista(grouped, idealista_df)
else:
    print("WARNING: precios_idealista.csv not found, skipping price filters")
    grouped["precio_m2"] = None
    grouped["variacion_anual"] = None
    grouped["variacion_maximo"] = None
    grouped["en_maximo_historico"] = False
    grouped["precio_anual_positivo"] = False
```

- [ ] **Step 5: Update the column list and filtered output**

Replace lines 188-193:
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

Update the filter on line 199:
```python
# Old filter
# filtered = grouped[grouped["supera_20k"] & grouped["crecimiento_positivo"]]

# New combined filter
price_ok = grouped["precio_anual_positivo"] | grouped["precio_anual_positivo"].isna()
# If no price data, don't filter out (treat as unknown)
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

Add `import` at top:
```python
from pathlib import Path
```

- [ ] **Step 6: Run the pipeline to verify it works**

```bash
python pipeline.py
```
Expected: Pipeline runs, shows new columns in output, filter works.

- [ ] **Step 7: Commit**

```bash
git add pipeline.py
git commit -m "feat: merge idealista price data and apply price trend filters"
```

---

### Task 4: Update build_html.py with new price columns and filters

**Files:**
- Modify: `build_html.py`

- [ ] **Step 1: Add new fields to the data export**

Replace the record-building loop (lines 6-17):
```python
records = []
for _, row in df.iterrows():
    records.append({
        "cp": row["codigo_postal"],
        "prov": row["provincia"],
        "muni": row["municipio_nombre"],
        "pob": int(round(row["poblacion_actual"])),
        "pob5": int(round(row["poblacion_hace_5a"])),
        "crec": round(row["crecimiento_%"], 2),
        "sup20k": bool(row["supera_20k"]),
        "crecPos": bool(row["crecimiento_positivo"]),
        "precio": round(row["precio_m2"]) if pd.notna(row.get("precio_m2")) else None,
        "varAnual": round(row["variacion_anual_%"], 1) if pd.notna(row.get("variacion_anual_%")) else None,
        "enMax": bool(row["en_maximo_historico"]) if pd.notna(row.get("en_maximo_historico")) else False,
        "precPos": bool(row["precio_anual_positivo"]) if pd.notna(row.get("precio_anual_positivo")) else False,
    })
```

- [ ] **Step 2: Add new filter checkboxes in the HTML**

After the existing filter line (line 66), add:
```html
<label><input type="checkbox" id="filterPrecio" checked onchange="render()"> <span>Precio anual positivo</span></label>
<label><input type="checkbox" id="filterNoMax" checked onchange="render()"> <span>No en máximo histórico</span></label>
```

- [ ] **Step 3: Add new column headers in the table**

After the "Crecimiento" column header (line 79), add:
```html
<th onclick="sort('precio')">Precio (€/m²) <span class="th-sort">▲</span></th>
<th onclick="sort('varAnual')">Var. Anual <span class="th-sort">▲</span></th>
<th>Filtros</th>
```
Change the colspan on the existing header row from 6 to 7.

- [ ] **Step 4: Update the render function to handle new filters and data**

In the `render()` function, add new filter checks after the existing ones (line 101):
```javascript
if (fPrecio && d.precPos === false) return false;
if (fNoMax && d.enMax) return false;
```

Update the row template (line 114) to include price columns:
```javascript
const priceDisplay = d.precio ? d.precio.toLocaleString() + ' €' : '—';
const varAnualDisplay = d.varAnual !== null ? (d.varAnual > 0 ? '+' : '') + d.varAnual + '%' : '—';
const varAnualClass = d.varAnual > 0 ? 'color:#0a7b3e' : 'color:#d32f2f';

// In the badge section, add max historical badge:
if (d.enMax) badges.push('<span class="badge badge-max">Máx. histórico</span>');

// Add price columns to the row:
return '<tr>...existing cols...'
    + '<td>' + priceDisplay + '</td>'
    + '<td style="' + varAnualClass + ';font-weight:600">' + varAnualDisplay + '</td>'
    + '<td>' + badges.join(' ') + '</td></tr>';
```

Update empty state colspan from 6 to 7.

- [ ] **Step 5: Add CSS for the new badge**

```css
.badge-max{background:#fce4ec;color:#b71c1c}
```

- [ ] **Step 6: Add filter variable references at the top of render()**

```javascript
const fPrecio = document.getElementById('filterPrecio').checked;
const fNoMax = document.getElementById('filterNoMax').checked;
```

- [ ] **Step 7: Regenerate the HTML and verify**

```bash
python build_html.py
```
Then open `docs/visor-cps.html` in a browser to verify new columns and filters appear.

- [ ] **Step 8: Commit**

```bash
git add build_html.py docs/visor-cps.html
git commit -m "feat: add price columns and filters to HTML viewer"
```

---

### Task 5: Update tests

**Files:**
- Modify: `test_pipeline.py`

- [ ] **Step 1: Add test for new columns in complete CSV**

```python
def test_complete_has_price_columns(self):
    df = pd.read_csv(self.complete_path)
    price_cols = ["precio_m2", "variacion_anual_%", "variacion_maximo_%",
                  "en_maximo_historico", "precio_anual_positivo"]
    for col in price_cols:
        self.assertIn(col, df.columns, f"Missing column: {col}")
```

- [ ] **Step 2: Add test for filtered CSV enforces price filters**

```python
def test_filtered_enforces_price_filter(self):
    df = pd.read_csv(self.filtered_path)
    self.assertTrue((df["precio_anual_positivo"] == True).all())
    self.assertTrue((df["en_maximo_historico"] == False).all())
```

- [ ] **Step 3: Add test for price column types**

```python
def test_price_columns_have_valid_types(self):
    df = pd.read_csv(self.complete_path)
    valid = df.dropna(subset=["precio_m2"])
    if len(valid) > 0:
        self.assertTrue((valid["precio_m2"] > 0).all())
        self.assertTrue((valid["variacion_anual_%"].notna().all()))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest test_pipeline.py -v
```
Expected: All tests pass (including existing ones).

- [ ] **Step 5: Commit**

```bash
git add test_pipeline.py
git commit -m "test: add tests for idealista price columns and filters"
```

---

### Task 6: End-to-end smoke test

- [ ] **Step 1: Run full pipeline**

```bash
python pipeline.py
```
Expected: Outputs show new columns. Filtered count may differ due to new filters.

- [ ] **Step 2: Regenerate HTML viewer**

```bash
python build_html.py
```
Expected: New HTML generated.

- [ ] **Step 3: Quick verification of output**

```bash
head -3 data/poblacion_por_cp_filtrado.csv
```
Expected: CSV includes new columns.

```bash
wc -l data/poblacion_por_cp_filtrado.csv
```
Expected: Fewer rows than before (tighter filter).

- [ ] **Step 4: Run test suite**

```bash
python -m pytest test_pipeline.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete idealista price integration with pipeline, viewer, and tests"
```
