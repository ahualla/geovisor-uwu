from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Union  # <-- IMPORTACIÓN CORREGIDA (Agregado Any y Union)
import ee
import os
import json

app = FastAPI()

# Configuración de CORS robusta para producción y desarrollo local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INICIALIZACIÓN SEGURA Y AUTOMÁTICA DE GOOGLE EARTH ENGINE ---
try:
    # 1. Buscamos primero si las credenciales están configuradas como variable de entorno
    gee_json_env = os.environ.get("GEE_JSON")
    
    if gee_json_env:
        info_credenciales = json.loads(gee_json_env)
        credentials = ee.ServiceAccountCredentials(
            info_credenciales['client_email'], 
            key_data=json.dumps(info_credenciales)
        )
        ee.Initialize(credentials, project='ee-tesistambopata1')
        print("✔ GEE conectado en producción usando variables de entorno.")
        
    else:
        # 2. Si no hay variable de entorno, cargamos el archivo JSON físico
        ruta_json_local = "ee-tesistambopata1-ecf622e54bef.json" 
        
        if os.path.exists(ruta_json_local):
            credentials = ee.ServiceAccountCredentials.from_json_keyfile(ruta_json_local)
            ee.Initialize(credentials, project='ee-tesistambopata1')
            print(f"✔ GEE conectado de forma local usando el archivo: {ruta_json_local}")
        else:
            # 3. Fallback local por defecto
            ee.Initialize(project='ee-tesistambopata1')
            print("✔ GEE conectado usando credenciales por defecto del sistema.")

except Exception as e:
    print("❌ Error crítico de conexión inicial con Earth Engine:", str(e))


# Esquema flexible para evitar errores 422 (Soporta 'año' con ñ y 'anio' con n)
class ConsultaMapa(BaseModel):
    indice: str
    anio: Union[int, str] = Field(..., alias="año")  # Soporta ambos y es obligatorio
    geometria: Dict[str, Any]

    @field_validator('anio', mode='before')
    @classmethod
    def limpiar_anio(cls, v):
        try:
            return int(v)  # Convierte strings como "2024" a enteros de forma segura
        except (ValueError, TypeError):
            raise ValueError("El año debe ser un número entero válido.")

    # Propiedad para que el backend no falle al buscar datos.año
    @property
    def año(self) -> int:
        return int(self.anio)


# --- 1. PROCESADOR Y FILTRADOR DE COLECCIONES SATELITALES ---
def obtener_imagen_por_año(año, region_ee):
    start_date = f"{año}-01-01"
    end_date = f"{año}-12-31"

    # Era Moderna (2015 - 2026): Sentinel-2 MSI
    if año >= 2015:
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)  
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40)))
        img = coleccion.median()
        return img.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11'], ['BLUE', 'GREEN', 'RED', 'RED_EDGE', 'NIR', 'SWIR'])

    # Era de Transición (2013 - 2014): Landsat 8 OLI
    elif año >= 2013:
        coleccion = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        img = coleccion.median()
        return img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR'])\
                  .addBands(ee.Image(0).rename('RED_EDGE'))

    # Era Histórica (1985 - 2012): Landsat 5 TM
    else:
        coleccion = (ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        img = coleccion.median()
        return img.select(['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR'])\
                  .addBands(ee.Image(0).rename('RED_EDGE'))


# --- 2. CALCULADORA AVANZADA DE ÍNDICES ESPECTRALES ---
def calcular_todos_los_indices(image, indice_nombre, año):
    blue = image.select('BLUE')
    green = image.select('GREEN')
    red = image.select('RED')
    red_edge = image.select('RED_EDGE')
    nir = image.select('NIR')
    swir = image.select('SWIR')

    ind = indice_nombre.upper()

    if ind == "NDRE" and año < 2015:
        red_edge_approx = red.add(nir).multiply(0.5)
        return nir.subtract(red_edge_approx).divide(nir.add(red_edge_approx)).rename('NDRE')

    # --- CATEGORÍA A: VEGETACIÓN ---
    if ind == "NDVI":
        return image.normalizedDifference(['NIR', 'RED']).rename('NDVI')
    elif ind == "EVI":
        return image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))', {'NIR': nir, 'RED': red, 'BLUE': blue}).rename('EVI')
    elif ind == "SAVI":
        return image.expression('((NIR - RED) / (NIR + RED + 0.5)) * 1.5', {'NIR': nir, 'RED': red}).rename('SAVI')
    elif ind == "GCI":
        return image.expression('(NIR / GREEN) - 1', {'NIR': nir, 'GREEN': green}).rename('GCI')
    elif ind == "MSAVI":
        return image.expression('(2 * NIR + 1 - ((2 * NIR + 1)**2 - 8 * (NIR - RED))**0.5) / 2', {'NIR': nir, 'RED': red}).rename('MSAVI')
    elif ind == "ARVI":
        return image.expression('(NIR - (RED - (BLUE - RED))) / (NIR + (RED - (BLUE - RED)))', {'NIR': nir, 'RED': red, 'BLUE': blue}).rename('ARVI')
    elif ind == "NDRE":
        return image.normalizedDifference(['NIR', 'RED_EDGE']).rename('NDRE')

    # --- CATEGORÍA B: RECURSOS HÍDRICOS ---
    elif ind == "NDWI":
        return image.normalizedDifference(['GREEN', 'NIR']).rename('NDWI')
    elif ind == "MNDWI":
        return image.normalizedDifference(['GREEN', 'SWIR']).rename('MNDWI')
    elif ind in ["NDMI", "LSWI"]:
        return image.normalizedDifference(['NIR', 'SWIR']).rename(ind)

    # --- CATEGORÍA C: SUELOS ---
    elif ind == "NDSI":
        return image.normalizedDifference(['GREEN', 'SWIR']).rename('NDSI')
    elif ind == "BAI":
        return image.expression('(SWIR / RED) - 1', {'SWIR': swir, 'RED': red}).rename('BAI')
    elif ind == "BSI":
        return image.expression('((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))', 
                                {'SWIR': swir, 'RED': red, 'NIR': nir, 'BLUE': blue}).rename('BSI')

    # --- CATEGORÍA D: INCENDIOS Y QUEMAS ---
    elif ind == "NBR":
        return image.normalizedDifference(['NIR', 'SWIR']).rename('NBR')
    elif ind == "CRI":
        return image.expression('(SWIR / GREEN) - 1', {'SWIR': swir, 'GREEN': green}).rename('CRI')
    
    return image.normalizedDifference(['NIR', 'RED']).rename('NDVI')


# --- 3. ESPECTRO DE PALETAS CIENTÍFICAS ---
def obtener_paleta_y_rangos(indice_nombre):
    ind = indice_nombre.upper()
    
    if ind in ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE"]:
        paleta = ['#4a3319', '#8c6239', '#c69c6d', '#e6d594', '#b3e09b', '#78c679', "#25b904", '#238443', "#008A2A"]
        return paleta, -0.05, 0.85

    elif ind in ["NDWI", "MNDWI", "NDMI", "LSWI"]:
        paleta = ['#fcfaf2', '#d0f4de', '#a8ded9', '#43a2ca', '#0868ac', '#012a4a']
        return paleta, -0.15, 0.70

    elif ind == "NDSI":
        paleta = ['#ffffff', '#e0f7fa', '#80deea', '#00b4d8', '#003049']
        return paleta, 0.15, 0.90

    elif ind == "BSI":
        paleta = ['#005f73', '#94d2bd', '#e9d8a6', '#ee9b00', '#ca6702', '#9b2226']
        return paleta, -0.20, 0.50

    else:
        paleta = ['#2b9348', '#e5e5e5', '#f4a261', '#e76f51', '#b7094c', '#510a32']
        return paleta, -0.25, 0.65


# --- 4. RUTA PRINCIPAL ---
@app.post("/calcular-indice-zona")
def procesar_mapa_zona(datos: ConsultaMapa):
    try:
        if not ee.data._credentials:
             raise Exception("Earth Engine no está inicializado. Verifica las credenciales.")

        # Usamos .año (que lee la propiedad limpia del validador)
        año_limpio = datos.año
        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        
        imagen_base = obtener_imagen_por_año(año_limpio, region_ee)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, año_limpio)
        resultado_recortado = resultado_indice.clip(region_ee)
        
        paleta, min_val, max_val = obtener_paleta_y_rangos(datos.indice)
        
        map_id_dict = resultado_recortado.getMapId({
            'min': min_val,
            'max': max_val,
            'palette': paleta
        })
        
        return {
            "status": "success",
            "indice": datos.indice.upper(),
            "año": año_limpio,
            "tile_url": map_id_dict['tile_fetcher'].url_format
        }
        
    except Exception as e:
        print(f"❌ Error al procesar el mapa: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en Google Earth Engine: {str(e)}")


# --- 5. ENDPOINTS DE DESCARGA ---
@app.post("/descargar-tiff")
def descargar_tiff_zona(datos: ConsultaMapa):
    try:
        if not ee.data._credentials:
             raise Exception("Earth Engine no está inicializado.")

        año_limpio = datos.año
        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        imagen_base = obtener_imagen_por_año(año_limpio, region_ee)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, año_limpio)
        resultado_recortado = resultado_indice.clip(region_ee)

        resolucion = 10 if año_limpio >= 2015 else 30

        url_descarga = resultado_recortado.getDownloadURL({
            'scale': resolucion,
            'crs': 'EPSG:4326',
            'region': region_ee,
            'format': 'GEO_TIFF'
        })
        
        return {
            "status": "success", 
            "indice": datos.indice.upper(),
            "año": año_limpio,
            "download_url": url_descarga
        }
    except Exception as e:
        print(f"❌ Error al generar descarga TIFF: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/descargar-png")
def descargar_png_estatico(indice: str, año: int, dist: str):
    return {
        "status": "success",
        "message": f"Petición de renderizado para {dist} en {indice}."
    }


# --- 6. SERVICIO DE ARCHIVOS ESTÁTICOS ---
@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return """
    <html>
        <head><title>Geoportal Activo</title></head>
        <body style="font-family: sans-serif; text-align: center; margin-top: 100px;">
            <h1>✔ Servidor Backend Activo</h1>
            <p>No se encontró el archivo <b>index.html</b> en la raíz.</p>
        </body>
    </html>
    """

# Servir archivos estáticos como app.js, ubigeo.js, etc.
app.mount("/", StaticFiles(directory=".", html=True), name="static")
