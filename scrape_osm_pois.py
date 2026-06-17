import csv
import json
import subprocess
import time
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TARGET_PREFIXES = {"03", "12", "46", "15", "27", "32", "36", "30", "43"}

SUPERMARKET_NAMES = {"Mercadona", "Carrefour", "Alcampo", "Gadis", "Eroski", "Consum"}

SCHOOL_QUERY = """
[out:json];
area["ISO3166-1"="ES"]->.es;
nwr(area.es)[amenity=school];
out center;
"""

UNIVERSIDAD_QUERY = """
[out:json];
area["ISO3166-1"="ES"]->.es;
nwr(area.es)[amenity=university];
out center;
"""

SUPERMERCADO_QUERY = """
[out:json];
area["ISO3166-1"="ES"]->.es;
nwr(area.es)[shop=supermarket];
out center;
"""


def query_overpass(query, timeout=300):
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", str(timeout),
                 "--data-urlencode", f"data={query}",
                 OVERPASS_URL],
                capture_output=True, text=True, timeout=timeout + 30
            )
            if result.returncode != 0:
                if attempt < 2:
                    time.sleep(10)
                    continue
                raise RuntimeError(f"curl failed: {result.stderr}")
            data = json.loads(result.stdout)
            remark = data.get("osm3s", {}).get("remark", "")
            if "runtime error" in remark:
                if attempt < 2:
                    print(f"  Server busy, retrying in 30s...")
                    time.sleep(30)
                    continue
                raise RuntimeError(f"Overpass error: {remark}")
            return data
        except json.JSONDecodeError:
            if attempt < 2:
                retry_after = (attempt + 1) * 20
                print(f"  JSON error, retrying in {retry_after}s...")
                time.sleep(retry_after)
                continue
            raise
    return {"elements": []}


def extract_cp(tags):
    for key in ("addr:postcode", "postcode", "addr:post_code"):
        val = tags.get(key, "")
        if val:
            return val.strip().zfill(5)
    return ""


def is_target_cp(cp):
    return cp[:2] in TARGET_PREFIXES


def is_instituto(tags):
    if tags.get("school") == "secondary":
        return True
    name = tags.get("name", "")
    upper = name.upper()
    if "IES " in upper or upper.startswith("IES") or upper.startswith("I.E.S."):
        return True
    if "INSTITUTO" in upper or "INSTITUT " in upper:
        return True
    if "EDUCACIÓN SECUNDARIA" in upper or "EDUCACIÓ SECUNDÀRIA" in upper:
        return True
    return False


def filter_supermarket(tags):
    name = tags.get("name", "")
    for chain in SUPERMARKET_NAMES:
        if chain.lower() in name.lower():
            return True
    return False


def process_elements(elements, tipo, extra_filter=None):
    matched = 0
    no_cp = 0
    wrong_prov = 0
    filtered = 0
    results = []

    for el in elements:
        tags = el.get("tags", {})
        if extra_filter and not extra_filter(tags):
            filtered += 1
            continue
        cp = extract_cp(tags)
        if not cp:
            no_cp += 1
            continue
        if not is_target_cp(cp):
            wrong_prov += 1
            continue
        results.append({
            "codigo_postal": cp,
            "tipo": tipo,
            "nombre": tags.get("name", ""),
        })
        matched += 1

    return results, matched, no_cp, wrong_prov, filtered


def scrape():
    all_pois = []
    t0 = time.time()

    print("Querying supermercados...", flush=True)
    try:
        data = query_overpass(SUPERMERCADO_QUERY)
        el = data.get("elements", [])
        print(f"  {len(el)} elements in {time.time()-t0:.0f}s", flush=True)
        results, *stats = process_elements(el, "supermercado", filter_supermarket)
        all_pois.extend(results)
        print(f"  Target CPs: {stats[0]}, No CP: {stats[1]}, "
              f"Wrong prov: {stats[2]}, Filtered: {stats[3]}", flush=True)
    except Exception as e:
        print(f"  Error: {e}", flush=True)
    time.sleep(5)

    t0 = time.time()
    print("Querying escuelas (colegios + institutos)...", flush=True)
    try:
        data = query_overpass(SCHOOL_QUERY)
        el = data.get("elements", [])
        print(f"  {len(el)} elements in {time.time()-t0:.0f}s", flush=True)

        colegio_results, *cs = process_elements(el, "colegio")
        all_pois.extend(colegio_results)
        print(f"  Colegios -> Target CPs: {cs[0]}, No CP: {cs[1]}, "
              f"Wrong prov: {cs[2]}", flush=True)

        instituto_results, *ins = process_elements(el, "instituto", is_instituto)
        all_pois.extend(instituto_results)
        print(f"  Institutos -> Target CPs: {ins[0]}, No CP: {ins[1]}, "
              f"Wrong prov: {ins[2]}, Filtered: {ins[3]}", flush=True)
    except Exception as e:
        print(f"  Error: {e}", flush=True)
    time.sleep(5)

    t0 = time.time()
    print("Querying universidades...", flush=True)
    try:
        data = query_overpass(UNIVERSIDAD_QUERY, timeout=120)
        el = data.get("elements", [])
        print(f"  {len(el)} elements in {time.time()-t0:.0f}s", flush=True)
        results, *stats = process_elements(el, "universidad")
        all_pois.extend(results)
        print(f"  Target CPs: {stats[0]}, No CP: {stats[1]}, "
              f"Wrong prov: {stats[2]}", flush=True)
    except Exception as e:
        print(f"  Error: {e}", flush=True)

    out_path = Path("data/pois_osm.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["codigo_postal", "tipo", "nombre"])
        writer.writeheader()
        writer.writerows(all_pois)

    print(f"\nSaved {len(all_pois)} POIs to {out_path}", flush=True)
    cps = set(p["codigo_postal"] for p in all_pois)
    print(f"Unique CPs: {len(cps)}", flush=True)
    for t in ("supermercado", "colegio", "instituto", "universidad"):
        count = sum(1 for p in all_pois if p["tipo"] == t)
        print(f"  {t}: {count}", flush=True)


if __name__ == "__main__":
    scrape()
