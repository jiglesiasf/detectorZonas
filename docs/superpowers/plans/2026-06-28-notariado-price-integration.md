# Notariado Price Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MIVAU municipality-level housing prices with per-CP real transaction prices from the Portal Estadístico del Notariado (penotariado.com).

**Architecture:** Playwright-based scraper (`scrape_notariado.py`) discovers the internal API of the penotariado.com map and extracts price/m2 per postal code. Pipeline.py loads the new per-CP CSV and merges directly by CP (no municipality matching needed). MIVAU is kept as fallback if Notariado data is unavailable.

**Tech Stack:** Python 3.10+, pandas, requests, playwright (new dependency)

## Global Constraints

- Playwright must be used to discover the API; no hardcoded API URLs
- All existing pipeline flags (`supera_20k`, `crecimiento_positivo`, amenity flags) must continue working
- MIVAU data must remain as fallback if Notariado data unavailable
- No breaking changes to existing CSV column names
- Output: `data/precios_notariado.csv` with `codigo_postal` as key

---

### Task 1: Discover penotariado map API with Playwright

**Files:**
- Create: `scrape_notariado.py` (will evolve in Task 2)
- Run: exploratory script to discover API

**Interfaces:**
- Produces: discovered API endpoint, request parameters, response format

- [ ] **Step 1: Install Playwright and open the map page**

```bash
pip install playwright && playwright install chromium
```

- [ ] **Step 2: Write and run exploratory script**

Write a Python script that:
1. Opens `https://penotariado.com/inmobiliario/buscador-precio-vivienda` with Playwright
2. Sets up request interception to capture all XHR/fetch requests
3. Waits for the map to load
4. Types a CP code (e.g. 46001) in the search box
5. Captures the API request/response that returns price data
6. Prints the discovered URL, headers, and response JSON

Run the script and document the findings.

- [ ] **Step 3: Document the discovered API**

Record:
- Full API endpoint URL
- HTTP method
- Request parameters (locationType, locationCode, etc.)
- Response JSON structure
- Required headers/cookies
- Whether auth is needed
- Whether the API works with direct HTTP calls or requires browser context

---

### Task 2: Build scrape_notariado.py

**Files:**
- Create: `scrape_notariado.py`

**Interfaces:**
- Consumes: CP list from `data/poblacion_por_cp_completo.csv` (or INE province list from pipeline)
- Produces: `data/precios_notariado.csv` with columns `codigo_postal, precio_m2, fecha_datos`

- [ ] **Step 1: Implement scrape_notariado.py**

The scraper:
1. Loads the target CP list (same provinces as pipeline)
2. Opens penotariado map with Playwright
3. For each CP, extracts price data via the discovered API
4. Sleeps 1-3 seconds between requests (rate limiting)
5. Saves results incrementally (resumable)
6. Output: `data/precios_notariado.csv`

Key considerations:
- Handle CPs with no data (confidentiality threshold) → set precio_m2 = None
- Handle API errors with retries (exponential backoff)
- Track progress to resume interrupted runs
- Use the same Playwright browser session for all requests (avoids re-login)

- [ ] **Step 2: Run scraper and verify output**

```bash
python3 scrape_notariado.py
```

Verify:
- `data/precios_notariado.csv` exists
- Has correct columns
- Has data for multiple CPs
- Some CPs within same municipality have different prices

- [ ] **Step 3: Commit**

```bash
git add scrape_notariado.py data/precios_notariado.csv
git commit -m "feat: add notariado price scraper for per-CP prices"
```

---

### Task 3: Modify pipeline.py

**Files:**
- Modify: `pipeline.py`

- [ ] **Step 1: Add load_notariado() and merge_notariado() functions**

After `merge_mivau()` (line 148), add:

```python
def load_notariado():
    """Load Notariado price data, return dict cp -> row."""
    df = pd.read_csv("data/precios_notariado.csv", dtype={"codigo_postal": str})
    df["codigo_postal"] = df["codigo_postal"].str.zfill(5)
    mapping = {}
    for _, row in df.iterrows():
        mapping[row["codigo_postal"]] = row
    return df, mapping


def merge_notariado(cp_df, notariado_mapping):
    def lookup_price(cp):
        cp = str(cp).zfill(5)
        if cp in notariado_mapping:
            r = notariado_mapping[cp]
            return pd.Series({
                "precio_m2": r["precio_m2"] if pd.notna(r["precio_m2"]) else None,
                "variacion_anual": None,
                "variacion_maximo": None,
                "en_maximo_historico": False,
                "precio_anual_positivo": pd.notna(r["precio_m2"]),
            })
        return pd.Series({
            "precio_m2": None,
            "variacion_anual": None,
            "variacion_maximo": None,
            "en_maximo_historico": False,
            "precio_anual_positivo": False,
        })

    merged = cp_df.join(
        cp_df["codigo_postal"].apply(lookup_price)
    )
    return merged
```

- [ ] **Step 2: Change data source priority in main()**

Replace lines 297-315 with:

```python
notariado_path = Path("data/precios_notariado.csv")
mivau_path = Path("data/precios_mivau.csv")
idealista_path = Path("data/precios_idealista.csv")

if notariado_path.exists():
    print("Merging Notariado price data...")
    notariado_df, notariado_mapping = load_notariado()
    grouped = merge_notariado(grouped, notariado_mapping)
    print(f"  Notariado coverage: {grouped['precio_m2'].notna().sum()} CPs")
elif mivau_path.exists():
    print("Merging MIVAU price data...")
    mivau_df, mivau_mapping = load_mivau()
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
```

- [ ] **Step 3: Commit**

```bash
git add pipeline.py
git commit -m "feat: add Notariado as primary price source with per-CP merge"
```

---

### Task 4: Run full pipeline and verify

**Files:**
- Run: existing pipeline

- [ ] **Step 1: Run the full pipeline**

```bash
python3 pipeline.py && python3 build_html.py
```

- [ ] **Step 2: Verify CP-level price variation**

```bash
python3 -c "
import pandas as pd
df = pd.read_csv('data/poblacion_por_cp_completo.csv')
# Check that CPs in same municipio have different prices
valencia = df[df['municipio_nombre'].str.contains('Valencia', na=False)]
print(f'Valencia CPs: {len(valencia)}')
print(f'Unique prices in Valencia: {valencia[\"precio_m2\"].nunique()}')
print(valencia[['codigo_postal', 'precio_m2']].head(10))
"
```

- [ ] **Step 3: Verify filtered output**

```bash
python3 -c "
import pandas as pd
df = pd.read_csv('data/poblacion_por_cp_filtrado.csv')
print(f'Filtered CPs: {len(df)}')
print(df[['codigo_postal', 'municipio_nombre', 'precio_m2']].head(10))
"
```

- [ ] **Step 4: Commit**

```bash
git add data/poblacion_por_cp_completo.csv data/poblacion_por_cp_filtrado.csv docs/visor-cps.html
git commit -m "feat: update CP data with Notariado per-CP prices"
```

---

### Task 5: Write tests

**Files:**
- Modify: `test_pipeline.py`

- [ ] **Step 1: Add Notariado price integration tests**

After the existing test class, add:

```python
class TestNotariado(unittest.TestCase):

    def test_notariado_output_exists(self):
        self.assertTrue(os.path.exists("data/precios_notariado.csv"))

    def test_notariado_has_expected_columns(self):
        df = pd.read_csv("data/precios_notariado.csv")
        expected = {"codigo_postal", "precio_m2", "fecha_datos"}
        self.assertTrue(expected.issubset(set(df.columns)))

    def test_notariado_some_prices_not_null(self):
        df = pd.read_csv("data/precios_notariado.csv")
        self.assertGreater(df["precio_m2"].notna().sum(), 0)

    def test_price_variation_within_municipio(self):
        """CPs in same municipio should not all have the same price."""
        complete = pd.read_csv("data/poblacion_por_cp_completo.csv")
        # Check Valencia city CPs
        valencia = complete[complete["municipio_nombre"] == "València"]
        if len(valencia) > 1:
            unique_prices = valencia["precio_m2"].dropna().unique()
            self.assertGreater(
                len(unique_prices), 1,
                f"All Valencia CPs have same price: {unique_prices}"
            )
```

- [ ] **Step 2: Run tests**

```bash
python3 -m unittest test_pipeline.py -v
```

- [ ] **Step 3: Commit**

```bash
git add test_pipeline.py
git commit -m "test: add Notariado price integration tests"
```
