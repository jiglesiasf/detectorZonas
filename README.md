# detectorZonas

Pipeline para identificar códigos postales con potencial de inversión inmobiliaria en la Comunidad Valenciana, Galicia, Murcia y Tarragona.

Combina datos de población (INE), precios de vivienda (MIVAU) y servicios cercanos (OSM + Catálogo SNS) para filtrar CPs de interés.

## Requisitos / Filtros

Cada CP debe cumplir **todos** los siguientes requisitos simultáneamente:

### 1. Población > 20.000 habitantes

- **Fuente**: INE (Instituto Nacional de Estadística) — Cifras oficiales de población municipal, enero 2025.
- **Cómo se obtiene**: Descarga vía API del INE por municipio. La población se distribuye proporcionalmente entre los CPs de cada municipio según el peso poblacional histórico de cada CP dentro del municipio.
- **Limitaciones**: La población por CP es una estimación basada en la distribución proporcional del municipio. CPs dentro de un mismo municipio reciben la misma tasa de crecimiento.

### 2. Crecimiento demográfico positivo (2020 → 2025)

- **Fuente**: INE — Cifras oficiales de población municipal, enero 2020 y enero 2025.
- **Cómo se obtiene**: Misma API del INE. Se calcula el crecimiento relativo: `(pob_2025 - pob_2020) / pob_2020 * 100`.
- **Limitaciones**: El crecimiento se mide a nivel municipal y se aplica a todos los CPs del municipio. No refleja diferencias de crecimiento entre distritos de una misma ciudad.

### 3. Precio de vivienda anual positivo

- **Fuente**: MIVAU (Ministerio de Vivienda y Agenda Urbana) — Tasación de vivienda libre por código postal.
- **Cómo se obtiene**: Descarga manual del XLSX publicado por MIVAU en su web. Se extraen las columnas de precio medio por m² y variación anual.
- **Limitaciones**: MIVAU solo publica datos para CPs con suficientes operaciones de tasación. La cobertura es parcial (~546 CPs de 2599). No todos los CPs tienen datos disponibles.

### 4. No estar en máximo histórico de precio

- **Fuente**: MIVAU — misma tabla que el punto 3.
- **Cómo se obtiene**: El XLSX incluye una columna que indica si el precio actual supera el máximo histórico registrado para ese CP.
- **Limitaciones**: Depende de la cobertura de MIVAU. CPs sin datos quedan excluidos automáticamente.

### 5. Supermercado (de cadena)

- **Fuente**: OpenStreetMap vía Overpass API.
- **Cómo se obtienen**: Consulta `shop=supermarket` a nivel nacional. Se filtran solo las cadenas: **Mercadona, Carrefour, Alcampo, Gadis, Eroski, Consum**. Se conservan solo los POIs con etiqueta `addr:postcode` en los prefijos objetivo (03, 12, 46, 15, 27, 32, 36, 30, 43).
- **Limitaciones**:
  - Muchos supermercados en OSM carecen de `addr:postcode`. Ejemplo: Lugo tiene 193 supermercados en OSM, solo 2 con CP. Esto provoca infraestimación en provincias con baja densidad de etiquetado postal.
  - Solo se consideran 6 cadenas. Quedan excluidos Dia, Lidl, Aldi, Spar, Alimerka, Froiz, Covirán y otros supermercados locales o regionales.
  - El etiquetado en OSM es colaborativo y puede estar desactualizado o incompleto.

### 6. Colegio (educación primaria/infantil)

- **Fuente**: OpenStreetMap vía Overpass API.
- **Cómo se obtienen**: Consulta `amenity=school` a nivel nacional. Se etiquetan como "colegio" todos los centros escolares que no son de secundaria (ver filtro de instituto).
- **Limitaciones**: Misma dependencia de `addr:postcode` en OSM. La distinción entre colegio e instituto se hace por heurística (etiquetas + nombre), no por fuentes oficiales.

### 7. Instituto (educación secundaria)

- **Fuente**: OpenStreetMap vía Overpass API.
- **Cómo se obtienen**: Misma consulta `amenity=school`. Se identifica como instituto si tiene `school=secondary` o si el nombre contiene "IES", "Instituto", "Institut" o "Educación Secundaria".
- **Limitaciones**: Heurística basada en nombre y etiquetas. Puede haber falsos positivos/negativos. Dependencia de `addr:postcode` en OSM.

### 8. Universidad

- **Fuente**: OpenStreetMap vía Overpass API.
- **Cómo se obtienen**: Consulta `amenity=university` a nivel nacional.
- **Limitaciones**: Muchas universidades son áreas extensas (relaciones) que pueden no tener un CP único. Dependencia de `addr:postcode` en OSM. Campus grandes pueden estar infrarrepresentados.

### 9. Centro de Salud público

- **Fuente**: Catálogo de Centros del Sistema Nacional de Salud (SNS) — Ministerio de Sanidad.
- **Cómo se obtienen**: Descarga del XLSX oficial publicado en `sanidad.gob.es`. Se filtran centros de tipo "CENTRO SALUD" y "CONSULTORIO LOCAL" con gestión pública.
- **Limitaciones**: El catálogo incluye centros de toda España. Solo se conservan los de las provincias objetivo. No incluye centros privados ni consultas médicas particulares. La actualización depende del calendario de publicación del ministerio.

## Pipeline

```
scrape_osm_pois.py  →  data/pois_osm.csv        (supermercados, colegios, institutos, universidades)
scrape_sns.py       →  data/centros_salud.csv    (centros de salud públicos)
pipeline.py         →  data/poblacion_por_cp_completo.csv
                    →  data/poblacion_por_cp_filtrado.csv
build_html.py       →  docs/visor-cps.html       (visor interactivo)
```

Ejecución completa:

```bash
python3 scrape_osm_pois.py      # 1. Obtener POIs de OSM (~3 min)
python3 scrape_sns.py           # 2. Obtener centros de salud (~10 s)
python3 pipeline.py             # 3. Ejecutar pipeline completo (~30 s)
python3 build_html.py           # 4. Generar visor HTML (~2 s)
```

## Tests

```bash
python3 -m unittest test_pipeline.py -v
```

## Cobertura actual

| Servicio | CPs con servicio | CPs totales | Cobertura |
|---|---|---|---|
| Centro Salud | ~1.228 | 2.599 | ~47% |
| Colegio | ~488 | 2.599 | ~19% |
| Supermercado (cadena) | ~204 | 2.599 | ~8% |
| Instituto | ~203 | 2.599 | ~8% |
| Universidad | ~33 | 2.599 | ~1% |
| Todos los servicios | ~8 | 2.599 | ~0,3% |

Las coberturas bajas en supermercados, institutos y universidades se deben principalmente a la falta de la etiqueta `addr:postcode` en los datos de OpenStreetMap, no necesariamente a la ausencia real del servicio en esas zonas.

## Stack

- Python 3.9+ con pandas
- OpenStreetMap Overpass API (consultas XML)
- Curl (subprocess) para consultas Overpass
- XLSX del Catálogo SNS (Ministerio de Sanidad)
- XLSX de MIVAU (Ministerio de Vivienda)
- HTML + JavaScript vanilla para el visor
