# Pipeline INE → CSV de Códigos Postales

## Objetivo
Generar un CSV con los códigos postales de **Comunidad Valenciana, Galicia, Murcia y provincia de Tarragona** que cumplan:
- **Población > 20.000 habitantes**
- **Crecimiento poblacional positivo en los últimos 5 años**

## Fuentes de Datos INE

1. **Padrón Municipal** — Cifras oficiales de población municipal (año actual y hace 5 años)
2. **Callejero del Censo Electoral** — mapea calles → sección censal → código postal

## Pipeline

```
INE Padrón → Python → CSV intermedio (población por CP) → filtro (>20K + crecimiento >0) → CSV final
```

## Procesamiento

1. Descargar población municipal por año para zonas objetivo
2. Cargar callejero INE y mapear municipio+sección → código postal
3. Agregar población por código postal
4. Calcular crecimiento: (pob_actual / pob_hace_5años - 1) * 100
5. Filtrar >20K hab y crecimiento >0
6. Exportar CSV

## Stack
- Python 3.10+ + pandas + requests

## Columnas CSV Final
`codigo_postal, municipio, provincia, poblacion_actual, poblacion_hace_5años, crecimiento_%`
