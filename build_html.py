import json
import pandas as pd

df = pd.read_csv("data/poblacion_por_cp_completo.csv")

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
    })

data_json = json.dumps(records, ensure_ascii=False)

html = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visor de Códigos Postales</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f7fa;color:#1a1a2e;padding:20px}}
.header{{max-width:1200px;margin:0 auto 20px}}
.header h1{{font-size:24px;color:#1a1a2e;margin-bottom:8px}}
.header p{{color:#666;font-size:14px}}
.filters{{background:white;border-radius:10px;padding:16px 20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08);display:flex;flex-wrap:wrap;align-items:center;gap:12px;max-width:1200px;margin-left:auto;margin-right:auto}}
.filters label{{display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px;user-select:none}}
.filters input[type=checkbox]{{width:16px;height:16px;cursor:pointer;accent-color:#4361ee}}
.search-input{{flex:1;min-width:160px;padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px;outline:none}}
.search-input:focus{{border-color:#4361ee;box-shadow:0 0 0 2px rgba(67,97,238,.15)}}
.counter{{font-size:13px;color:#666;white-space:nowrap}}
.table-wrap{{max-width:1200px;margin:0 auto;background:white;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);overflow:hidden}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead{{background:#f8f9fa;position:sticky;top:0;z-index:1}}
th{{padding:10px 12px;text-align:left;font-weight:600;color:#444;cursor:pointer;user-select:none;white-space:nowrap;border-bottom:2px solid #e8ecf1}}
th:hover{{color:#4361ee}}
th.sorted{{color:#4361ee}}
td{{padding:8px 12px;border-bottom:1px solid #f0f2f5}}
tr:hover td{{background:#f8faff}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}}
.badge-pop{{background:#e3fcef;color:#0a7b3e}}
.badge-grow{{background:#fff3cd;color:#856404}}
.badge-both{{background:#dbeafe;color:#1e40af}}
.province-tag{{font-size:11px;color:#666}}
.empty{{text-align:center;padding:40px;color:#999;font-size:15px}}
.th-sort{{margin-left:4px;opacity:.4}}
th.sorted .th-sort{{opacity:1}}
</style>
</head>
<body>

<div class="header">
<h1>📍 Detector de Zonas</h1>
<p>CPs de Comunidad Valenciana, Galicia, Murcia y Tarragona con datos de población (INE 2020 vs 2025)</p>
</div>

<div class="filters">
<label><input type="checkbox" id="filter20k" checked onchange="render()"> <span>Más de 20K habitantes</span></label>
<label><input type="checkbox" id="filterCrec" checked onchange="render()"> <span>Crecimiento demográfico positivo</span></label>
<input type="text" class="search-input" id="search" placeholder="Buscar CP o municipio..." oninput="render()">
<span class="counter" id="counter"></span>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
<th onclick="sort('cp')">CP <span class="th-sort">▲</span></th>
<th onclick="sort('prov')">Provincia <span class="th-sort">▲</span></th>
<th onclick="sort('muni')">Municipio <span class="th-sort">▲</span></th>
<th onclick="sort('pob')" class="sorted">Población <span class="th-sort">▼</span></th>
<th onclick="sort('crec')">Crecimiento <span class="th-sort">▲</span></th>
<th>Filtros</th>
</tr>
</thead>
<tbody id="tbody">
</tbody>
</table>
</div>

<script>
const DATA = {data_json};

let sortField = 'pob';
let sortDir = -1;

function render() {{
    const f20k = document.getElementById('filter20k').checked;
    const fCrec = document.getElementById('filterCrec').checked;
    const q = document.getElementById('search').value.toLowerCase().trim();

    let items = DATA.filter(d => {{
        if (f20k && !d.sup20k) return false;
        if (fCrec && !d.crecPos) return false;
        if (q && !d.cp.includes(q) && !d.muni.toLowerCase().includes(q) && !d.prov.toLowerCase().includes(q)) return false;
        return true;
    }});

    items.sort((a, b) => sortDir * (a[sortField] > b[sortField] ? 1 : -1));

    const tbody = document.getElementById('tbody');
    tbody.innerHTML = items.map(d => {{
        const badges = [];
        if (d.sup20k) badges.push('<span class="badge badge-pop">>20K</span>');
        if (d.crecPos) badges.push('<span class="badge badge-grow">+' + d.crec + '%</span>');
        const crecClass = d.crec > 0 ? 'color:#0a7b3e' : 'color:#d32f2f';
        return '<tr><td><strong>' + d.cp + '</strong></td><td><span class="province-tag">' + d.prov + '</span></td><td>' + d.muni + '</td><td>' + d.pob.toLocaleString() + '</td><td style="' + crecClass + ';font-weight:600">' + (d.crec > 0 ? '+' : '') + d.crec + '%</td><td>' + badges.join(' ') + '</td></tr>';
    }}).join('');

    if (items.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="6" class="empty">No se encontraron CPs con los filtros seleccionados</td></tr>';
    }}

    document.getElementById('counter').textContent = 'Mostrando ' + items.length + ' de ' + DATA.length + ' CPs';
}}

function sort(field) {{
    if (sortField === field) sortDir *= -1;
    else {{ sortField = field; sortDir = field === 'pob' || field === 'crec' ? -1 : 1; }}
    document.querySelectorAll('th').forEach(th => th.classList.remove('sorted'));
    event.currentTarget.classList.add('sorted');
    render();
}}

render();
</script>
</body>
</html>'''

with open("docs/visor-cps.html", "w", encoding="utf-8") as f:
    f.write(html)

print("docs/visor-cps.html generado")
