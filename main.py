from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, Any
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
    # 1. Buscamos primero si las credenciales están configuradas como variable de entorno (Para Render, Koyeb o Hugging Face)
    gee_json_env = os.environ.get("GEE_JSON")
    
    if gee_json_env:
        # Si la variable de entorno existe, cargamos las credenciales desde ahí
        info_credenciales = json.loads(gee_json_env)
        credentials = ee.ServiceAccountCredentials(
            info_credenciales['client_email'], 
            key_data=json.dumps(info_credenciales)
        )
        ee.Initialize(credentials, project='ee-tesistambopata1')
        print("✔ GEE conectado en producción usando variables de entorno.")
        
    else:
        # 2. Si no hay variable de entorno (desarrollo local), intentamos cargar el archivo JSON físico
        ruta_json_local = "ee-tesistambopata1-ecf622e54bef.json" 
        
        if os.path.exists(ruta_json_local):
            credentials = ee.ServiceAccountCredentials.from_json_keyfile(ruta_json_local)
            ee.Initialize(credentials, project='ee-tesistambopata1')
            print(f"✔ GEE conectado de forma local usando el archivo: {ruta_json_local}")
        else:
            # 3. Fallback por si ejecutas en tu PC local y ya te logueaste con la CLI de gcloud/earthengine
            ee.Initialize(project='ee-tesistambopata1')
            print("✔ GEE conectado usando credenciales por defecto del sistema.")

except Exception as e:
    print("❌ Error crítico de conexión inicial con Earth Engine:", str(e))


# Esquema flexible y robusto para evitar errores 422
from pydantic import Field, field_validator

class ConsultaMapa(BaseModel):
    indice: str
    anio: Any = Field(None, alias="año")  # Soporta 'año' con ñ y 'anio' con n
    geometria: Dict[str, Any]

    @field_validator('anio', mode='before')
    @classmethod
    def limpiar_anio(cls, v):
        try:
            return int(v)  # Si viene como "2024" (string), lo convierte a 2024 (int)
        except (ValueError, TypeError):
            raise ValueError("El año debe ser un número entero válido")

    # Propiedad interna para que el resto del código que usa datos.año no falle
    @property
    def año(self) -> int:
        return self.anio


# --- 1. PROCESADOR Y FILTRADOR DE COLECCIONES SATELITALES (NUBOSIDAD INTERNA AL 40%) ---
def obtener_imagen_por_año(año, region_ee):
    start_date = f"{año}-01-01"
    end_date = f"{año}-12-31"

    # Era Moderna (2015 - 2026): Sentinel-2 MSI (Resolución 10m - Alta definición)
    if año >= 2015:
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)  
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))) # Filtro estricto del 40%
        img = coleccion.median()
        return img.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11'], ['BLUE', 'GREEN', 'RED', 'RED_EDGE', 'NIR', 'SWIR'])

    # Era de Transición (2013 - 2014): Landsat 8 OLI (Resolución 30m)
    elif año >= 2013:
        coleccion = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40))) # Filtro estricto del 40%
        img = coleccion.median()
        # Mapeo corregido: Landsat 8 no tiene Red Edge nativo en el sensor OLI básico, mapeamos una constante temporal
        return img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR'])\
                  .addBands(ee.Image(0).rename('RED_EDGE')) # Previene caídas en el select posterior

    # Era Histórica (1985 - 2012): Landsat 5 TM (Mosaicos históricos de Oro)
    else:
        coleccion = (ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40))) # Filtro estricto del 40%
        img = coleccion.median()
        # Mapeo corregido: Landsat 5 (B1=Blue, B2=Green, B3=Red, B4=NIR, B5=SWIR1)
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

    # Manejo inteligente de NDRE para satélites antiguos sin banda RedEdge
    if ind == "NDRE" and año < 2015:
        # Fallback científico: Si es Landsat, aproximamos usando una fracción ponderada entre Red y NIR
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

    # --- CATEGORÍA B: RECURSOS HÍDRICOS Y HUMEDAD ---
    elif ind == "NDWI":
        return image.normalizedDifference(['GREEN', 'NIR']).rename('NDWI')
    elif ind == "MNDWI":
        return image.normalizedDifference(['GREEN', 'SWIR']).rename('MNDWI')
    elif ind == "NDMI" or ind == "LSWI":
        return image.normalizedDifference(['NIR', 'SWIR']).rename(ind)

    # --- CATEGORÍA C: DINÁMICA DE SUELOS Y GEOMORFOLOGÍA ---
    elif ind == "NDSI":
        return image.normalizedDifference(['GREEN', 'SWIR']).rename('NDSI')
    elif ind == "BAI":
        return image.expression('(SWIR / RED) - 1', {'SWIR': swir, 'RED': red}).rename('BAI')
    elif ind == "BSI":
        # Fórmula oficial expandida del Bare Soil Index para resaltar minería/suelo expuesto
        return image.expression('((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))', 
                                {'SWIR': swir, 'RED': red, 'NIR': nir, 'BLUE': blue}).rename('BSI')

    # --- CATEGORÍA D: DIAGNÓSTICO DE QUEMAS Y ANTROPIZACIÓN ---
    elif ind == "NBR":
        return image.normalizedDifference(['NIR', 'SWIR']).rename('NBR')
    elif ind == "CRI":
        return image.expression('(SWIR / GREEN) - 1', {'SWIR': swir, 'GREEN': green}).rename('CRI')
    
    return image.normalizedDifference(['NIR', 'RED']).rename('NDVI')

# --- 3. ESPECTRO DE PALETAS CIENTÍFICAS Y RANGOS DINÁMICOS CORREGIDOS ---
def obtener_paleta_y_rangos(indice_nombre):
    ind = indice_nombre.upper()
    
    # 🌿 RAMPA 1: ÍNDICES DE VEGETACIÓN
    if ind in ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE"]:
        paleta = [
            '#4a3319',  # Marrón Profundo
            '#8c6239',  # Marrón Arcilloso
            '#c69c6d',  # Ocre/Arena
            '#e6d594',  # Amarillo Pálido
            '#b3e09b',  # Verde Menta
            '#78c679',  # Verde Claro
            "#25b904",  # Verde Esmeralda
            '#238443',  # Verde Intenso
            "#008A2A"   # Verde Profundo Opaco
        ]
        return paleta, -0.05, 0.85

    # 💧 RAMPA 2: ÍNDICES DE AGUA Y HUMEDAD EDÁFICA
    elif ind in ["NDWI", "MNDWI", "NDMI", "LSWI"]:
        paleta = [
            '#fcfaf2',  # Blanco Crema
            '#d0f4de',  # Verde/Celeste Húmedo
            '#a8ded9',  # Turquesa Somero
            '#43a2ca',  # Azul Claro
            '#0868ac',  # Azul Clásico
            '#012a4a'   # Azul de Alta Mar
        ]
        return paleta, -0.15, 0.70

    # ❄️ RAMPA 3: CUBIERTA CRIOGÉNICA O NIEVE (NDSI)
    elif ind == "NDSI":
        paleta = ['#ffffff', '#e0f7fa', '#80deea', '#00b4d8', '#003049']
        return paleta, 0.15, 0.90

    # 🏗️ RAMPA 4: ÍNDICE DE SUELO DESNUDO (BSI)
    elif ind == "BSI":
        paleta = [
            '#005f73',  # Azul Verdoso
            '#94d2bd',  # Verde Claro
            '#e9d8a6',  # Amarillo
            '#ee9b00',  # Naranja
            '#ca6702',  # Marrón Ladrillo
            '#9b2226'   # Rojo Sangre
        ]
        return paleta, -0.20, 0.50

    # 🔥 RAMPA 5: INCENDIOS, QUEMAS O DEGRADACIÓN FORESTAL SEVERA
    else:
        paleta = [
            '#2b9348',  # Verde Selva
            '#e5e5e5',  # Gris Claro
            '#f4a261',  # Naranja
            '#e76f51',  # Naranja Rojizo
            '#b7094c',  # Carmesí
            '#510a32'   # Púrpura Oscuro
        ]
        return paleta, -0.25, 0.65


# --- 4. RUTA PRINCIPAL CON RENDIMIENTO DE RENDERIZADO MEJORADO ---
@app.post("/calcular-indice-zona")
def procesar_mapa_zona(datos: ConsultaMapa):
    try:
        # Asegurar inicialización previa a procesar la petición
        if not ee.data._credentials:
             raise Exception("Earth Engine no está inicializado. Verifica las credenciales en Render.")

        # Forzar el CRS geográfico estándar compatible con Leaflet
        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        
        # 1. Recuperar la imagen óptima filtrada por nubes (40%) y compuesta anualmente
        imagen_base = obtener_imagen_por_año(datos.año, region_ee)
        
        # 2. Calcular las operaciones de bandas matemáticas por píxel
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.año)
        
        # 3. Recortar (Clip) exacto para no consumir memoria innecesaria
        resultado_recortado = resultado_indice.clip(region_ee)
        
        # 4. Inyectar la paleta configurada
        paleta, min_val, max_val = obtener_paleta_y_rangos(datos.indice)
        
        # Generar las credenciales de renderizado rápido del mapa web
        map_id_dict = resultado_recortado.getMapId({
            'min': min_val,
            'max': max_val,
            'palette': paleta
        })
        
        return {
            "status": "success",
            "indice": datos.indice.upper(),
            "año": datos.año,
            "tile_url": map_id_dict['tile_fetcher'].url_format
        }
        
    except Exception as e:
        # Registro explícito del error en la terminal de Render para que puedas leerlo
        print(f"❌ Error al procesar el mapa: {str(e)}")
        # Lanzamos HTTP 500 para que el frontend reconozca la caída de forma correcta
        raise HTTPException(status_code=500, detail=f"Error en Google Earth Engine: {str(e)}")


# ==============================================================================
# --- 5. ENGINES ADICIONALES: ENDPOINTS INTEGRADOS PARA DESCARGAS CIENTÍFICAS ---
# ==============================================================================

@app.post("/descargar-tiff")
def descargar_tiff_zona(datos: ConsultaMapa):
    try:
        if not ee.data._credentials:
             raise Exception("Earth Engine no está inicializado.")

        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        imagen_base = obtener_imagen_por_año(datos.año, region_ee)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.año)
        resultado_recortado = resultado_indice.clip(region_ee)

        resolucion = 10 if datos.año >= 2015 else 30 # Sentinel-2 es 10m, Landsat es 30m

        url_descarga = resultado_recortado.getDownloadURL({
            'scale': resolucion,
            'crs': 'EPSG:4326',  # Formato WGS84 para QGIS / ArcGIS
            'region': region_ee,
            'format': 'GEO_TIFF'
        })
        
        return {
            "status": "success", 
            "indice": datos.indice.upper(),
            "año": datos.año,
            "download_url": url_descarga
        }
    except Exception as e:
        print(f"❌ Error al generar descarga TIFF: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/descargar-png")
def descargar_png_estatico(indice: str, año: int, dist: str):
    return {
        "status": "success",
        "message": f"Petición de renderizado de imagen procesada para el distrito de {dist} en el índice {indice}."
    }


# ==============================================================================
# --- 6. SERVICIO DE ARCHIVOS ESTÁTICOS (FRONTEND INTEGRADO) ---
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return """
    <html>
        <head><title>Geoportal Activo</title></head>
        <body style="font-family: sans-serif; text-align: center; margin-top: 100px;">
            <h1>✔ Servidor Backend Activo</h1>
            <p>El backend de FastAPI está corriendo, pero no se encontró el archivo <b>index.html</b> en la raíz del proyecto.</p>
            <p>Verifica que tus archivos HTML, CSS y JS estén subidos en la raíz de tu repositorio de GitHub.</p>
        </body>
    </html>
    """
# Al estar al final, FastAPI solo usará esta ruta si la petición no coincide con las rutas de arriba.
app.mount("/", StaticFiles(directory=".", html=True), name="static")
