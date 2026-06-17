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
