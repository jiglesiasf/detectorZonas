# Añadir filtros de servicios por código postal

## Resumen

Añadir un nuevo conjunto de filtros al pipeline de detección de zonas que verifique que un código postal dispone de al menos un supermercado grande, un colegio, un instituto, una universidad y un centro de salud público.

## Fuentes de datos

### OpenStreetMap (via Overpass API)

Se creará un script independiente `scrape_osm_pois.py` que consulta la API de Overpass para obtener POIs de las provincias objetivo.

**Tipos y etiquetas OSM:**

| Servicio | Etiqueta OSM | Filtro adicional |
|---|---|---|
| Supermercado | `shop=supermarket` | `name` contiene: Mercadona, Carrefour, Alcampo, Gadis, Eroski, Consum |
| Colegio | `amenity=school` | — |
| Instituto | `amenity=school` + `school=secondary` | — |
| Universidad | `amenity=university` | — |

Se extraerá la etiqueta `addr:postcode` de cada POI. Solo se conservan POIs con código postal no vacío.

**Estrategia de consulta:**
- Por cada provincia, ejecutar consulta Overpass para cada tipo (4 consultas por provincia)
- Usar `area` para limitar al ámbito provincial
- Parámetros: `[out:json]`, timeout 60s
- Formato de salida: CSV con columnas `codigo_postal`, `tipo`, `nombre`

**Output:** `data/pois_osm.csv`

### Catálogo de Centros del SNS

Se consideran centros de salud públicos: centros de atención primaria (centros de salud, consultorios) y hospitales públicos del Sistema Nacional de Salud.

**Fuentes potenciales:**
- Catálogo de Centros de Atención Primaria del SNS en `http://www.msps.es/estadEstudios/estadisticas/sisInfSanSNS/UltDatos.htm` (CSV, actualizado a 31/12/2025)
- REGCESS (Registro General de Centros, Servicios y Establecimientos Sanitarios) con descargas mensuales en Excel por tipo de centro

Se creará un script `scrape_sns.py` que:
- Descarga el CSV/Excel de la fuente que esté disponible
- Filtra centros con código postal en provincias objetivo
- Output: `data/centros_salud.csv` con columnas `codigo_postal`, `tipo` (`centro_salud` o `hospital`), `nombre`

## Pipeline (`pipeline.py`)

Después del bloque de precios (línea ~316), se añade:

1. Cargar `data/pois_osm.csv` y `data/centros_salud.csv`
2. Para cada CP en `grouped`, verificar si existe ≥1 POI de cada tipo
3. Añadir columnas booleanas por servicio + columna compuesta

**Nuevas columnas en output:**

| Columna | Tipo | Descripción |
|---|---|---|
| `tiene_supermercado` | bool | ≥1 supermercado grande en el CP |
| `tiene_colegio` | bool | ≥1 colegio en el CP |
| `tiene_instituto` | bool | ≥1 instituto en el CP |
| `tiene_universidad` | bool | ≥1 universidad en el CP |
| `tiene_centro_salud` | bool | ≥1 centro de salud público en el CP |
| `tiene_todos_servicios` | bool | Todos los anteriores true |

**Nuevo filtro:** Se añade `tiene_todos_servicios == True` a la condición de filtrado (líneas ~333-338).

## HTML viewer (`build_html.py`)

Se añaden alvisor:
- 6 nuevos campos en cada registro JSON
- 5 checkboxes de filtro (uno por servicio) + checkbox "Todos los servicios"
- Badges visuales por cada servicio presente

## Tests (`test_pipeline.py`)

Se añaden tests:
- Columnas de servicios existen en output completo
- Filtrado solo incluye CPs con `tiene_todos_servicios == True`
- Tipos booleanos válidos

## Orden de implementación

1. `scrape_osm_pois.py` — script de obtención de POIs OSM
2. `scrape_sns.py` — script de obtención de centros SNS
3. Modificar `pipeline.py` — integración de datos y filtros
4. Modificar `build_html.py` — nuevos filtros en visor
5. Modificar `test_pipeline.py` — nuevos tests
6. Ejecución completa del pipeline y verificación
