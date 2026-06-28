# Integración Precios Vivienda por CP — Portal Estadístico del Notariado

## Objetivo

Sustituir la fuente actual de precios de vivienda (MIVAU, datos por municipio) por datos del Portal Estadístico del Notariado (penotariado.com), que ofrece **precios reales de compraventa desglosados por código postal**.

## Contexto / Problema

La fuente actual (MIVAU — serie 35103500 del Ministerio de Vivienda) publica el valor tasado medio de vivienda libre **solo a nivel municipal** para municipios >25K habitantes. No tiene columna de código postal. Como consecuencia, todos los CPs de un mismo municipio reciben el mismo `precio_m2`, lo que impide detectar diferencias intra-municipales.

El Portal Estadístico del Notariado (lanzado en octubre 2025) publica precios basados en **escrituras notariales de compraventa** (precio real pagado, no oferta ni tasación) con granularidad de código postal, actualización mensual y cobertura nacional. Es la fuente más fiable y detallada disponible públicamente.

## Fuente de Datos

- **Nombre**: Portal Estadístico del Notariado
- **URL**: https://penotariado.com/inmobiliario/buscador-precio-vivienda
- **Granularidad**: Código postal (CP), municipio, provincia, CCAA, nacional
- **Métricas**: precio medio por m², número de compraventas, superficie media, importe medio total
- **Actualización**: Mensual
- **Acceso**: Gratuito (datos básicos sin registro; históricos y descargas requieren registro)
- **Licencia**: Uso público, datos anonimizados
- **API**: No documentada públicamente; el mapa usa un backend interno. Se descubrirá mediante Playwright.

## Arquitectura

```
scrape_notariado.py (NUEVO)
  → Playwright abre el mapa de penotariado.com
  → Intercepta peticiones de red para descubrir el API
  → Para cada CP objetivo (~2600), consulta el API
  → Output: data/precios_notariado.csv

pipeline.py (MODIFICADO)
  → Carga precios_notariado.csv (merge directo por CP)
  → Elimina carga de precios_mivau.csv
  → Mismo sistema de filtros (precio_anual_positivo, en_maximo_historico...)
  → Output actualizado: poblacion_por_cp_completo.csv

build_html.py (SIN CAMBIOS)
  → Las columnas de precio ya existen, solo cambia la fuente de datos

visor-cps.html (SIN CAMBIOS)
  → Misma estructura, datos más precisos
```

## Componentes

### 1. scrape_notariado.py — Obtención de precios por CP

**Fase exploratoria (1 vez):**
1. Playwright abre `https://penotariado.com/inmobiliario/buscador-precio-vivienda`
2. Intercepta todas las peticiones XHR/fetch (request interception)
3. Busca un CP en el mapa (ej: 46001) para activar la carga de datos
4. Identifica el endpoint que devuelve las estadísticas de precio
5. Extrae: URL base, parámetros (locationType, locationCode, etc.), formato de respuesta, cookies/headers necesarios

**Fase productiva (~2600 CPs):**
1. Para cada CP en la lista de provincias objetivo:
   a. Construir petición API con los parámetros descubiertos
   b. Enviar GET al endpoint de estadísticas
   c. Parsear respuesta JSON
   d. Extraer: `precio_m2`, `num_compraventas`, `superficie_media`, `importe_medio`
   e. Delay aleatorio entre peticiones

**Si el API no es directamente accesible sin sesión:**
- Mantener una página de Playwright abierta con sesión
- Usar `page.evaluate()` o `page.request()` para hacer llamadas autenticadas
- Alternativa: extraer datos del DOM renderizado

**Formato de salida (CSV):**
```csv
codigo_postal,precio_m2,num_compraventas,superficie_media,importe_medio,fecha_datos
46001,2500.0,125,85.0,212500.0,2026-05
46002,2300.0,98,90.0,207000.0,2026-05
...
```

### 2. pipeline.py — Nuevo merge de precios

La modificación principal está en el bloque que carga los precios (líneas 297-315 actuales):

```python
notariado_path = Path("data/precios_notariado.csv")
if notariado_path.exists():
    print("Merging Notariado price data...")
    notariado_df = load_notariado()
    grouped = merge_notariado(grouped, notariado_df)
else:
    # Fallback a MIVAU o idealista
    ...
```

**`load_notariado()`:**
- Lee `data/precios_notariado.csv`
- Calcula `precio_anual_positivo` si tenemos datos de periodos anteriores (con dos scrapeos)
- Si solo hay un scrapeo, este flag se basa en tendencia disponible o se omite
- Devuelve dict `{codigo_postal: row}`

**`merge_notariado()`:**
- Merge directo por `codigo_postal` (no por municipio)
- CPs sin datos en Notariado → `precio_m2 = None`
- No necesita fuzzy matching de nombres de municipio

### 3. Tratamiento de flags de filtro (v1 — primer scrapeo)

Con un solo scrapeo no tenemos serie histórica. Los flags se calculan así:

| Flag | Valor inicial | Motivo |
|------|---------------|--------|
| `precio_m2` | Del Notariado | Dato real del CP |
| `precio_anual_positivo` | `True` si hay `precio_m2`, `False` si no | Sin histórico no podemos calcular variación; tener precio ya es positivo |
| `en_maximo_historico` | `False` siempre | Sin histórico no sabemos si es máximo |
| `variacion_anual_%` | `None` | Se poblará con scrapeos sucesivos |

**Efecto en el filtro**: Con estos valores, el filtro de precio se convierte esencialmente en "tiene datos de precio del Notariado". Esto es razonable para v1. En v2, con scrapeos periódicos (ej: mensuales), podremos calcular variación anual real y detectar máximos.

### 3b. Estrategia de scrapeo periódico (v2)

Para obtener `variacion_anual_%` real:
- Scrapear mensualmente (aprovechando que el Notariado actualiza cada mes)
- Almacenar histórico en `data/precios_notariado_historico.csv`
- En cada ejecución, comparar con el dato del mismo mes del año anterior
- Calcular `en_maximo_historico` contra la serie completa

### 4. Estrategia de fallback

Si `data/precios_notariado.csv` no existe o está vacío:
1. Intentar `data/precios_mivau.csv` (comportamiento actual)
2. Si no, intentar `data/precios_idealista.csv`
3. Si no, precio = None (sin filtro de precio)

| Flag | Con MIVAU | Con Notariado |
|------|-----------|---------------|
| `precio_m2` | Media municipal | Precio real por CP |
| `precio_anual_positivo` | Variación vs año anterior | Requiere scrapeo periódico; inicialmente = True si hay precio |
| `en_maximo_historico` | Comparación con max histórico | Solo aplicable con histórico; inicialmente = False |

### 5. Manejo de CPs sin datos

El Notariado no publica datos para CPs con pocas transacciones (confidencialidad estadística). Para estos CPs:
- `precio_m2 = None`
- `precio_anual_positivo = None`
- No pasan el filtro de precio (mismo comportamiento que MIVAU cuando faltaban datos)

## Variables de entorno / Configuración

No se requieren APIs keys. El scraper es completamente autónomo.

## Dependencias nuevas

- `playwright` + chromium (misma dependencia que se intentó para idealista)

## Tests

- `test_notariado_scraper`: verifica que el scraper descubre el API y devuelve datos para al menos 1 CP conocido (ej: 46001 Valencia)
- `test_notariado_pipeline`: verifica que pipeline.py carga correctamente el nuevo CSV y que el merge por CP funciona
- `test_notariado_coverage`: verifica cobertura mínima de CPs con precio (al menos 30% de los ~2600 CPs)

## Lista de verificación

- [ ] Descubrir API con Playwright (interceptar peticiones)
- [ ] Implementar `scrape_notariado.py` (fase productiva)
- [ ] Generar `data/precios_notariado.csv`
- [ ] Modificar `pipeline.py`: añadir `load_notariado()` y `merge_notariado()`
- [ ] Modificar `pipeline.py`: cambiar prioridad de carga (notariado > mivau > idealista)
- [ ] Ejecutar pipeline completo
- [ ] Regenerar visor HTML
- [ ] Verificar que los precios varían entre CPs de un mismo municipio (ej: Valencia 46001 vs 46010)
- [ ] Tests
