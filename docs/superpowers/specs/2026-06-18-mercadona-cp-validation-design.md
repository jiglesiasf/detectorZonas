# Validar presencia de Mercadona por código postal

## Resumen

Añadir un nuevo atributo booleano `tiene_mercadona` al dataset de códigos postales, independiente del existente `tiene_supermercado`, validando contra la API oficial de la tienda online de Mercadona si cada CP tiene cobertura.

## Fuente de datos

Se utiliza la API no documentada de `tienda.mercadona.es`:

```
GET /api/postal-codes/actions/retrieve-pc/<cp>/
```

- **204 No Content** → El CP está dentro del área de operación de Mercadona (tiene tienda o almacén que da servicio)
- **404 Not Found** → El CP no tiene cobertura

La respuesta incluye headers `x-customer-wh` que identifican el almacén asignado.

## Nuevo script: `validate_mercadona.py`

Script independiente y autocontenido que:

1. **Carga los CPs objetivo** desde la lógica de provincias del proyecto (mismos códigos provincia que `pipeline.py`)
2. **Para cada CP**, realiza una petición GET a la API de Mercadona
3. **Sleep aleatorio entre 2 y 5 segundos** entre peticiones (~3h para 2600 CPs)
4. **Reintentos**: hasta 3 intentos con backoff si hay error de red/timeout
5. **Guardado incremental** en `data/mercadona_cps.json` (diccionario `{cp: bool}`) para no perder progreso si se interrumpe
6. **Output final**: `data/mercadona_cps.csv` con columnas `codigo_postal`, `tiene_mercadona`
7. **Modo resume**: si ya existe el JSON incremental, retoma desde donde quedó

### Manejo de errores

- Timeout de 10s por petición
- Si después de 3 intentos falla, se marca como `False` y se registra warning
- Cualquier error HTTP no esperado (5xx) también se reintenta

## Pipeline (`pipeline.py`)

En el bloque de amenities (línea ~317), después de cargar `pois_osm.csv`:

```python
mercadona_path = Path("data/mercadona_cps.csv")
if mercadona_path.exists():
    mercadona = pd.read_csv(mercadona_path, dtype={"codigo_postal": str})
    mercadona["codigo_postal"] = mercadona["codigo_postal"].str.zfill(5)
    cp_mercadona = set(mercadona[mercadona["tiene_mercadona"] == True]["codigo_postal"])
    grouped["tiene_mercadona"] = grouped["codigo_postal"].isin(cp_mercadona)
else:
    grouped["tiene_mercadona"] = False
```

La columna `tiene_mercadona` es independiente de `tiene_supermercado`. NO afecta a `tiene_todos_servicios`.

## HTML Viewer (`build_html.py`)

### Nuevo filtro (línea ~82):
```html
<label><input type="checkbox" id="filterMercadona" onchange="render()"> <span>🛍️ Mercadona</span></label>
```

### Nuevo badge en filas (línea ~152):
```javascript
if (d.tiene_mercadona) badges.push('<span class="badge badge-servicio" title="Mercadona">🛍️</span>');
```

### Filtro en JS (`render()`, línea ~135):
```javascript
if (fMercadona && !d.tiene_mercadona) return false;
```

## Tests

En `test_pipeline.py`, nuevo test en `TestAmenityIntegration`:

- `test_mercadona_column_exists`: verifica que `tiene_mercadona` está en el CSV
- `test_mercadona_is_boolean`: verifica que solo contiene True/False
- `test_mercadona_coverage`: verifica que hay al menos algunos CPs con Mercadona (sin número fijo, solo que el proceso corrió)

## Consideraciones

- **API no oficial**: puede cambiar sin previo aviso. El script es autocontenido y fácil de actualizar.
- **Rate limiting**: el sleep de 2-5s entre requests y los headers de Akamai/Bot Manager pueden activarse. Si ocurre, aumentar el sleep.
- **Entrega vs tienda física**: la API mide cobertura de entrega, no presencia de tienda física. Para inversión inmobiliaria ambos indicadores son relevantes.
- **Independencia semántica**: `tiene_mercadona` evalúa una cadena específica; `tiene_supermercado` evalúa presencia de cualquier cadena grande vía OSM.
