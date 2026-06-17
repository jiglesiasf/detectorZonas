import argparse
import csv
import json
import os
import random
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


API_BASE = "https://www.idealista.com/sala-de-prensa/informes-precio-vivienda"
API_REST = "https://www.idealista.com/press-room/property-price-reports/rest"

TARGET_PROVINCES = [
    "alicante/alacant", "castellón/castelló", "valencia/valència",
    "a coruña", "lugo", "ourense", "pontevedra",
    "murcia", "tarragona",
]


def _kebab(name):
    s = name.lower().strip()
    s = s.replace("/", "-").replace(" ", "-")
    accents = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
        "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
        "ñ": "n",
    }
    for a, b in accents.items():
        s = s.replace(a, b)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s


def _build_location_tree(page, api_key):
    """Build full hierarchy: comunidad → provincia → municipio using get-location-children."""

    def fetch_children(loc_id):
        url = f"{API_REST}/get-location-children/{loc_id}/?apiKey={api_key}"
        return page.evaluate(
            """(url) => fetch(url).then(r => r.json()).then(data =>
                data.map(item => ({
                    serial: item.serial,
                    location_id: item.location_id,
                    name: item.name,
                    zone_level_id: item.zone_level_id,
                    final_location: item.final_location,
                }))
            )""",
            url,
        )

    root = fetch_children(1)
    tree = {}
    for com in root:
        com_slug = _kebab(com["name"])
        tree[com_slug] = {
            "serial": com["serial"],
            "name": com["name"],
            "provinces": {},
        }
        provs = fetch_children(com["serial"])
        for prov in provs:
            prov_slug = _kebab(prov["name"])
            tree[com_slug]["provinces"][prov_slug] = {
                "serial": prov["serial"],
                "name": prov["name"],
                "municipios": {},
            }
            munis = fetch_children(prov["serial"])
            for muni in munis:
                if muni.get("final_location") == "1":
                    tree[com_slug]["provinces"][prov_slug]["municipios"][_kebab(muni["name"])] = {
                        "serial": muni["serial"],
                        "name": muni["name"],
                    }
    return tree


def _learn_url_patterns(page, tree, target_provinces):
    """For each target province, submit form once to discover URL slug pattern."""

    target_munis = {}
    for target_raw in target_provinces:
        target = _kebab(target_raw)
        found_province = None
        found_com = None
        for com_slug, com_data in tree.items():
            for prov_slug, prov_data in com_data["provinces"].items():
                if target == prov_slug or target in prov_slug or prov_slug in target:
                    found_province = prov_data
                    found_com = com_slug
                    break
            if found_province:
                break

        if not found_province:
            print(f"  WARNING: Could not find province '{target_raw}' in tree")
            continue

        muni_slugs = list(found_province["municipios"].keys())
        if not muni_slugs:
            continue

        # Use the first municipality as a probe
        first_muni_slug = muni_slugs[0]
        first_muni = found_province["municipios"][first_muni_slug]

        url = _submit_form_get_url(page, found_com, found_province["serial"], first_muni["serial"])
        print(f"  URL pattern for {target_raw}: {url}")

        # Parse slugs from URL
        m = re.search(r"/venta/([^/]+)/([^/]+)/([^/]+)/", url)
        if m:
            com_url_slug, prov_url_slug, muni_url_slug = m.group(1), m.group(2), m.group(3)
        else:
            com_url_slug, prov_url_slug, muni_url_slug = found_com, _kebab(found_province["name"]), first_muni_slug

        # Build mapping for all municipalities in this province
        target_munis[target_raw] = []
        for m_slug, m_data in found_province["municipios"].items():
            # Determine municipality slug — same pattern as first one
            if m_slug == first_muni_slug:
                m_url_slug = muni_url_slug
            else:
                m_url_slug = _kebab(m_data["name"])
                # Apply same disambiguation pattern as first
                if prov_url_slug == _kebab(found_province["name"]) and m_url_slug == prov_url_slug:
                    m_url_slug = m_url_slug + "-provincia"
                elif prov_url_slug == first_muni_slug and m_url_slug == first_muni_slug:
                    pass
                elif m_url_slug == _kebab(found_province["name"]):
                    m_url_slug = m_url_slug + "-provincia"

            target_munis[target_raw].append({
                "com_slug": com_url_slug,
                "prov_slug": prov_url_slug,
                "muni_url_slug": m_url_slug,
                "serial": m_data["serial"],
                "name": m_data["name"],
                "target_name": target_raw,
            })

    return target_munis


def _submit_form_get_url(page, com_slug, prov_serial, muni_serial):
    """Navigate to main page, select location, submit form, return resulting URL."""
    page.goto(API_BASE + "/", wait_until="networkidle", timeout=30000)
    time.sleep(2)

    selects = page.locator("select").all()
    opts = selects[0].locator("option").all()
    for opt in opts:
        if opt.get_attribute("value"):
            selects[0].select_option(opt.get_attribute("value"))
            time.sleep(1)
            break

    # Find comunidad by serial
    selects = page.locator("select").all()
    api_key = page.evaluate(
        """() => {
            const m = document.documentElement.innerHTML.match(/apiKey=([a-f0-9-]+)/);
            return m ? m[1] : null;
        }"""
    )
    comunidad_serial = None
    comunidades_raw = page.evaluate(
        """(apiKey) => fetch('https://www.idealista.com/press-room/property-price-reports/rest/get-location-children/1/?apiKey=' + apiKey)
            .then(r => r.json())
            .then(data => data.map(i => ({serial: i.serial, name: i.name})))""",
        api_key,
    )
    for c in comunidades_raw:
        if _kebab(c["name"]) == com_slug:
            comunidad_serial = c["serial"]
            break

    if not comunidad_serial:
        raise ValueError(f"Comunidad '{com_slug}' not found")

    selects = page.locator("select").all()
    selects[0].select_option(comunidad_serial)
    time.sleep(3)

    selects = page.locator("select").all()
    selects[1].select_option(prov_serial)
    time.sleep(3)

    selects = page.locator("select").all()
    selects[2].select_option(muni_serial)
    time.sleep(2)

    page.click("#edit-submit")
    time.sleep(5)
    return page.url


def _scrape_price_from_page(page):
    """Extract price data from current page."""
    title = page.title()
    m = re.search(r"en (.+?) — idealista", title)
    location_name = m.group(1) if m else ""

    price_data = page.evaluate(
        """() => {
            const el = document.querySelector('.price-indicator-current-values__list');
            return el ? el.innerText : '';
        }"""
    )

    precio_m2 = None
    for line in price_data.split("\n"):
        line = line.strip()
        m2 = re.match(r"([\d.]+)\s*€/m2", line)
        if m2:
            precio_m2 = float(m2.group(1).replace(".", ""))
            break

    # Parse table
    rows = page.evaluate(
        """() => {
            const block = document.querySelector('.price-indicator-table-block--children');
            if (!block) return [];
            const table = block.querySelector('table');
            if (!table) return [];
            const trs = table.querySelectorAll('tr');
            return Array.from(trs).slice(1, 2).map(r =>
                Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim())
            );
        }"""
    )

    variacion_anual = None
    variacion_mensual = None
    variacion_trimestral = None
    maximo_historico_str = None
    variacion_maximo = None
    en_maximo = False

    if rows and len(rows[0]) >= 7:
        variacion_anual = _parse_variacion(rows[0][4]) if rows[0][4] else None
        variacion_mensual = _parse_variacion(rows[0][2])
        variacion_trimestral = _parse_variacion(rows[0][3])
        maximo_historico_str = rows[0][5]
        variacion_maximo = _parse_variacion(rows[0][6])
        en_maximo = "0,0 %" in rows[0][6] if rows[0][6] else False

    return {
        "municipio_nombre": location_name,
        "precio_m2": precio_m2,
        "variacion_mensual": variacion_mensual,
        "variacion_trimestral": variacion_trimestral,
        "variacion_anual": variacion_anual,
        "maximo_historico_str": maximo_historico_str,
        "variacion_maximo": variacion_maximo,
        "en_maximo": en_maximo,
    }


def _parse_variacion(s):
    s = s.strip()
    m = re.match(r"([+-])\s*([\d,]+)\s*%", s)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        val = float(m.group(2).replace(",", "."))
        return sign * val
    return None


def scrape_idealista(target_munis_dict):
    """Scrape price data for all target municipalities via CDP browser.

    Args:
        target_munis_dict: dict mapping province -> list of {com_slug, prov_slug, muni_url_slug, name}

    Returns:
        list of dicts with price data per municipality.
    """
    results = []
    total = sum(len(munis) for munis in target_munis_dict.values())

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.new_page()

        done = 0
        for prov, munis in target_munis_dict.items():
            if not munis:
                continue
            com_slug = munis[0]["com_slug"]
            prov_slug = munis[0]["prov_slug"]

            for m_data in munis:
                done += 1
                m_url_slug = m_data["muni_url_slug"]
                url = f"{API_BASE}/venta/{com_slug}/{prov_slug}/{m_url_slug}/"

                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    time.sleep(2)

                    data = _scrape_price_from_page(page)
                    results.append(data)
                    precio_str = f'{data["precio_m2"]} €/m2' if data["precio_m2"] else "N/A"
                    print(f"  [{done}/{total}] {m_data['name']}: {precio_str}")
                except Exception as e:
                    print(f"  [{done}/{total}] {m_data['name']}: ERROR - {e}")
                    results.append({
                        "municipio_nombre": m_data["name"],
                        "precio_m2": None,
                        "variacion_mensual": None,
                        "variacion_trimestral": None,
                        "variacion_anual": None,
                        "maximo_historico_str": None,
                        "variacion_maximo": None,
                        "en_maximo": None,
                    })

                delay = random.uniform(0.5, 1.5)
                time.sleep(delay)

        browser.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Scrape idealista housing prices")
    parser.add_argument("--input", default="data/poblacion_por_cp_completo.csv",
                        help="CSV with municipio_nombre column")
    parser.add_argument("--output", default="data/precios_idealista.csv",
                        help="Output CSV path")
    parser.add_argument("--cdp-port", type=int, default=9222,
                        help="Connect to existing Chrome via CDP")
    args = parser.parse_args()

    print("Extracting unique municipios from input...")
    import pandas as pd
    df = pd.read_csv(args.input)
    all_munis = set()
    for names in df["municipio_nombre"].str.split(", "):
        for n in names:
            all_munis.add(n.strip())
    all_munis = sorted(all_munis)
    print(f"Found {len(all_munis)} unique municipios")

    print("\nPhase 1: Building location hierarchy...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{args.cdp_port}")
        context = browser.contexts[0]
        page = context.new_page()

        page.goto(API_BASE + "/", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        api_key = page.evaluate(
            """() => {
                const m = document.documentElement.innerHTML.match(/apiKey=([a-f0-9-]+)/);
                return m ? m[1] : null;
            }"""
        )
        print(f"API Key: {api_key}")

        tree = _build_location_tree(page, api_key)
        print(f"Tree built: {sum(len(c['provinces']) for c in tree.values())} provinces in {len(tree)} communities")

        print("\nPhase 2: Learning URL patterns for target provinces...")
        target_munis = _learn_url_patterns(page, tree, TARGET_PROVINCES)

        total_target = sum(len(m) for m in target_munis.values())
        print(f"Target municipalities: {total_target}")

        browser.close()

    print("\nPhase 3: Scraping prices...")
    results = scrape_idealista(target_munis)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "municipio_nombre", "precio_m2", "variacion_mensual",
            "variacion_trimestral", "variacion_anual", "maximo_historico_str",
            "variacion_maximo", "en_maximo",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nSaved {len(results)} records to {out_path}")
    success = sum(1 for r in results if r["precio_m2"] is not None)
    print(f"Successful: {success}/{len(results)}")


if __name__ == "__main__":
    main()
