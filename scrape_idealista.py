import argparse
import csv
import json
import os
import random
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


API_BASE = "https://www.idealista.com/sala-de-prensa/informes-precio-vivienda"

TARGET_PROVINCES = [
    "alicante/alacant", "castellón/castelló", "valencia/valència",
    "a coruña", "lugo", "ourense", "pontevedra",
    "murcia", "tarragona",
]


def discover_api(target_provinces, cookie_file=None):
    """Discover idealista's internal price API.

    Opens the idealista price report page with Playwright, captures XHR
    requests to discover the internal API URL pattern, and builds a
    location mapping from the page's dropdown selectors.

    If DataDome blocks access (captcha), raises RuntimeError with guidance
    on how to manually export cookies for reuse.

    Args:
        target_provinces: List of province name strings (lowercase) to target.
        cookie_file: Optional path to a JSON cookie file exported from a
                     browser session where the captcha was already solved.

    Returns:
        dict with keys:
          - session: requests.Session primed with cookies
          - api_pattern: str, the API URL template
          - headers: dict of required request headers
          - location_mapping: dict[str, str] mapping normalized names -> IDs
    """
    if cookie_file and os.path.exists(cookie_file):
        return _load_cookies_and_discover(cookie_file)

    return _discover_via_playwright(target_provinces)


def _discover_via_playwright(target_provinces):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid",
        )
        page = context.new_page()
        captured_url = None
        captured_headers = None
        location_mapping = {}

        def intercept(response):
            nonlocal captured_url, captured_headers
            if response.ok and "/data/" in response.url and "price" in response.url.lower():
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    captured_url = response.url
                    captured_headers = response.request.headers

        page.on("response", intercept)
        try:
            page.goto(API_BASE, wait_until="networkidle", timeout=30000)
        except Exception as e:
            browser.close()
            raise RuntimeError(
                f"Could not load idealista page (blocked by DataDome?): {e}\n"
                "Try manually opening https://www.idealista.com/sala-de-prensa/informes-precio-vivienda/ "
                "in a regular browser, solve the captcha, export cookies as JSON, "
                "and pass them via --cookie-file."
            )
        time.sleep(2)

        # Check if we got past the captcha (look for select elements)
        selects = page.locator("select")
        if selects.count() < 2:
            body_text = page.locator("body").inner_text()
            browser.close()
            body_snippet = body_text[:200] if body_text else "(empty page body)"
            raise RuntimeError(
                "DataDome captcha blocking idealista access. "
                "Manually solve the captcha in a regular browser, then:\n"
                "  1. Export cookies with an extension like 'Cookie-Editor'\n"
                "  2. Save as JSON file\n"
                "  3. Pass with --cookie-file <path>\n"
                f"Body content: {body_snippet}"
            )

        prov_select = page.locator("select").first
        prov_options = prov_select.locator("option").all()
        for opt in prov_options:
            val = opt.get_attribute("value")
            text = opt.inner_text().strip()
            if val and text:
                location_mapping[f"prov:{text.lower()}"] = val

        for prov_name_lower in target_provinces:
            key = f"prov:{prov_name_lower}"
            if key in location_mapping:
                prov_select.select_option(location_mapping[key])
                time.sleep(2)
                break
        else:
            for opt in prov_options:
                val = opt.get_attribute("value")
                if val:
                    prov_select.select_option(val)
                    time.sleep(2)
                    break

        muni_select = page.locator("select").nth(1)
        muni_options = muni_select.locator("option").all()
        for opt in muni_options:
            val = opt.get_attribute("value")
            text = opt.inner_text().strip()
            if val and text and val != muni_select.get_attribute("value"):
                location_mapping[f"muni:{text.lower()}"] = val

        for opt in muni_options:
            val = opt.get_attribute("value")
            if val and val != muni_select.get_attribute("value"):
                muni_select.select_option(val)
                time.sleep(2)
                break

        cookies = context.cookies()
        browser.close()

    if not captured_url:
        raise RuntimeError(
            "Could not discover idealista API endpoint. "
            "The page loaded but no JSON API call was intercepted."
        )

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"])

    return {
        "session": session,
        "api_pattern": captured_url,
        "headers": {k: v for k, v in captured_headers.items()
                    if k.lower() in ("accept", "content-type", "x-requested-with",
                                     "user-agent", "referer")},
        "location_mapping": location_mapping,
    }


def _load_cookies_and_discover(cookie_file):
    """Load cookies from a file and attempt to use them for discovery."""
    with open(cookie_file, encoding="utf-8") as f:
        cookies = json.load(f)

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c.get("name", c.get("key", "")),
                            c.get("value", ""))

    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    })

    config = {
        "session": session,
        "api_pattern": None,
        "headers": dict(session.headers),
        "location_mapping": {},
    }
    return config


def fetch_municipio_price(muni_name, api_config):
    """Fetch price data for a municipality via the discovered idealista API.

    Uses the location_mapping from discover_api() to find the correct
    location ID and constructs the API URL accordingly.

    Args:
        muni_name: Municipality name as string.
        api_config: Config dict from discover_api().

    Returns:
        dict with keys: municipio_nombre, precio_m2, variacion_mensual,
        variacion_trimestral, variacion_anual, maximo_historico,
        variacion_maximo, mes_referencia.
    """
    session = api_config["session"]
    headers = api_config["headers"]
    mapping = api_config["location_mapping"]

    muni_key = f"muni:{muni_name.strip().lower()}"
    loc_id = mapping.get(muni_key)
    if not loc_id:
        for key, val in mapping.items():
            if key.startswith("muni:") and muni_key[5:] in key:
                loc_id = val
                break

    if not loc_id:
        raise ValueError(f"No location ID found for {muni_name}")

    api_pattern = api_config["api_pattern"]
    existing_ids = set(mapping.values())
    for eid in sorted(existing_ids, key=len, reverse=True):
        if eid in api_pattern:
            url = api_pattern.replace(eid, loc_id)
            break
    else:
        separator = "&" if "?" in api_pattern else "?"
        url = f"{api_pattern}{separator}locationId={loc_id}"

    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

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


def scrape_all(target_munis, target_provinces, cookie_file=None):
    """Scrape price data for all target municipalities."""
    print("Discovering idealista API...")
    api_config = discover_api(target_provinces, cookie_file=cookie_file)
    pattern = api_config.get("api_pattern") or "(cookie-based, URL pattern unknown until API call)"
    print(f"API discovered: {pattern}")

    results = []
    total = len(target_munis)
    for i, muni in enumerate(target_munis, 1):
        try:
            data = fetch_municipio_price(muni, api_config)
            results.append(data)
            print(f"  [{i}/{total}] {muni}: {data.get('precio_m2', 'N/A')} \u20ac/m2")
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
        delay = 1.0 + random.uniform(-0.5, 0.5)
        time.sleep(max(0.1, delay))

    return results


def extract_municipios_from_csv(csv_path):
    """Extract unique municipio names from the input CSV."""
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
    parser.add_argument("--cookie-file",
                        help="Path to JSON cookie file (bypasses Playwright captcha)")
    args = parser.parse_args()

    print("Extracting unique municipios from input...")
    munis = extract_municipios_from_csv(args.input)
    print(f"Found {len(munis)} unique municipios to scrape")

    results = scrape_all(munis, TARGET_PROVINCES, cookie_file=args.cookie_file)

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


if __name__ == "__main__":
    main()
