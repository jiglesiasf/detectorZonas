# Integración Datos Precio Vivienda (idealista)

## Objetivo
Añadir datos de precio de vivienda (€/m2) de idealista al pipeline de detección de zonas, de modo que los filtros incluyan:
- **Variación anual del precio positiva** (la zona es apetecible)
- **No en máximo histórico** (si `variacion_maximo == 0%` es negativo)

## Fuente de Datos
- **URL**: `https://www.idealista.com/sala-de-prensa/informes-precio-vivienda/`
- **Métricas por municipio**: precio m2, variación mensual, trimestral, anual, máximo histórico, variación al máximo
- **Granularidad**: municipio (distrito/CP si disponible vía API)

## Arquitectura

```
scrape_idealista.py (NUEVO)
  → Playwright abre idealista UNA vez
  → Intercepta peticiones para descubrir API interna
  → Hace ~3000 llamadas HTTP a la API (rate-limited)
  → Output: data/precios_idealista.csv

pipeline.py (MODIFICADO)
  → Carga precios_idealista.csv
  → Merge con poblacion_por_cp_completo.csv por municipio
  → Nuevos flags de filtro
  → Output actualizado: poblacion_por_cp_filtrado.csv

build_html.py (MODIFICADO)
  → Nuevas columnas y filtros en visor HTML
```

## Componentes

### 1. scrape_idealista.py — Obtención de precios

**Fase 1: Descubrimiento de API**
1. Playwright abre `https://www.idealista.com/sala-de-prensa/informes-precio-vivienda/`
2. Intercepta todas las peticiones XHR/fetch (request interception)
3. Interactúa con la UI: selecciona una provincia → un municipio
4. Identifica el endpoint que devuelve los datos de precio (patrón JSON)
5. Extrae: URL base, parámetros (ids de localización), formato de respuesta

**Fase 2: Extracción masiva**
1. Para cada municipio en la lista objetivo (~3000):
   a. Construir URL de API con los parámetros descubiertos
   b. Hacer GET con la cookie/sesión de Playwright
   c. Parsear JSON y extraer: `precio_m2`, `variacion_anual`, `variacion_maximo`
   d. Añadir delay de 1s entre peticiones

**Fase 3: Fallback**
- Si no se descubre API, extraer datos del DOM renderizado
- Navegar Playwright provincia por provincia, extraer tabla HTML

**Rate limiting:**
- 1 petición/segundo como mínimo
- Backoff exponencial si hay errores 429/503: 2s, 4s, 8s, 16s (max 5 retries)
- Jitter aleatorio (±0.5s) para evitar patrones predecibles

### 2. pipeline.py — Nuevos campos y filtros

**Nuevas columnas en `poblacion_por_cp_completo.csv`:**
| Columna | Tipo | Origen |
|---------|------|--------|
| `precio_m2` | float | idealista |
| `variacion_anual_%` | float | idealista |
| `variacion_maximo_%` | float | idealista |
| `en_maximo_historico` | bool | True si variacion_maximo == 0% |
| `precio_anual_positivo` | bool | True si variacion_anual > 0% |

**Nuevo filtro combinado:**
```python
candidato = (
    supera_20k
    and crecimiento_positivo
    and precio_anual_positivo
    and not en_maximo_historico
)
```

**Matching municipios:**
- Cruzar `precios_idealista.csv` (columna `municipio_nombre`) con `municipios.csv`
- Misma estrategia de fuzzy matching existente (normalizar, quitar acentos, split por `/`)
- Municipios sin datos de idealista → `precio_anual_positivo = False` (no pasan filtro)

### 3. build_html.py — Nuevas columnas y filtros

**Nuevas columnas en tabla:**
- Precio (€/m2) — con formato numérico
- Var. Anual — con color verde (positivo) / rojo (negativo)
- Máx. Hist. — badge rojo si `en_maximo_historico = True`

**Nuevos controles de filtro:**
- Checkbox "Precio anual positivo" (on by default)
- Checkbox "No en máximo histórico" (on by default)

**Datos del tooltip/row:**
```
CP | Provincia | Municipio | Población | Crecimiento % | Precio m2 | Var. Anual | Filtros
```

## Flags de filtro (resumen)

| Flag | Fuente | Bueno | Malo |
|------|--------|-------|------|
| `supera_20k` | INE | True | False |
| `crecimiento_positivo` | INE | True | False |
| `precio_anual_positivo` | idealista | True (>0%) | False (≤0%) |
| `en_maximo_historico` | idealista | False | True (=0%) |

Todos los flags deben ser "buenos" para que un CP pase el filtro.

## Stack
- Python 3.10+ + pandas + requests
- playwright (nuevo)

## Output
- `data/precios_idealista.csv` — datos crudos por municipio
- `data/poblacion_por_cp_completo.csv` — actualizado con columnas de precio
- `data/poblacion_por_cp_filtrado.csv` — actualizado con nuevos filtros
- `docs/visor-cps.html` — visor con nuevas columnas y filtros
