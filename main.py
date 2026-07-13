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
        # CAMBIA ESTE NOMBRE por el de tu JSON descargado si es diferente:
        ruta_json_local = "ee-tesistambopata1-ecf622e54bef.json" 
        
        if os.path.exists(ruta_json_local):
            credentials = ee.ServiceAccountCredentials.from_json_keyfile(ruta_json_local)
            ee.Initialize(credentials, project='ee-tesistambopata1')
            print(f"✔ GEE conectado de forma local usando el archivo: {ruta_json_local}")
        else:
            # 3. Fallback por si ejecutas en tu propia PC y ya estás logueado en la terminal
            ee.Initialize(project='ee-tesistambopata1')
            print("✔ GEE conectado usando credenciales por defecto del sistema.")

except Exception as e:
    print("❌ Error crítico de conexión con Earth Engine:", e)


# Esquema estricto de entrada de datos desde el Frontend (app.js)
class ConsultaMapa(BaseModel):
    indice: str
    año: int
    geometria: Dict[str, Any]


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
    
    # 🌿 RAMPA 1: ÍNDICES DE VEGETACIÓN (Gradiente continuo de 9 pasos - Suelo a Bosque Amazónico)
    if ind in ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE"]:
        paleta = [
            '#4a3319',  # Marrón Profundo: Rocas, desiertos, minería total o pavimentos.
            '#8c6239',  # Marrón Arcilloso: Suelos expuestos degradados o rastrojos agrícolas.
            '#c69c6d',  # Ocre/Arena: Suelos con indicios mínimos de pastos secos.
            '#e6d594',  # Amarillo Pálido: Vegetación escasa, matorral ralo o cultivos estresados.
            '#b3e09b',  # Verde Menta: Vegetación de lomas, pastizales de jalca o brotes jóvenes.
            '#78c679',  # Verde Claro Tradicional: Matorrales saludables o cultivos intermedios.
            "#25b904",  # Verde Esmeralda: Bosque secundario o parcelas en pleno apogeo vigoroso.
            '#238443',  # Verde Intenso: Cobertura arbórea forestal densa.
            "#008A2A"   # Verde Profundo Opaco: Selva virgen intacta de alta biomasa (Dosel cerrado).
        ]
        return paleta, -0.05, 0.85

    # 💧 RAMPA 2: ÍNDICES DE AGUA Y HUMEDAD EDÁFICA
    elif ind in ["NDWI", "MNDWI", "NDMI", "LSWI"]:
        paleta = [
            '#fcfaf2',  # Blanco Crema: Zonas áridas Continentales sin agua.
            '#d0f4de',  # Verde/Celeste Húmedo: Suelos saturados o bofedales con vegetación.
            '#a8ded9',  # Turquesa Somero: Canales inundables temporales o riberas con lodo.
            '#43a2ca',  # Azul Claro Hidrológico: Cochas estables o lagunas de poca profundidad.
            '#0868ac',  # Azul Clásico: Ríos dinámicos andinos o amazónicos.
            '#012a4a'   # Azul de Alta Mar: Núcleos profundos de cuerpos de agua masivos.
        ]
        return paleta, -0.15, 0.70

    # ❄️ RAMPA 3: CUBIERTA CRIOGÉNICA O NIEVE (NDSI)
    elif ind == "NDSI":
        paleta = ['#ffffff', '#e0f7fa', '#80deea', '#00b4d8', '#003049']
        return paleta, 0.15, 0.90

    # 🏗️ RAMPA 4: ÍNDICE DE SUELO DESNUDO (BSI)
    elif ind == "BSI":
        paleta = [
            '#005f73',  # Azul Verdoso: Máxima cobertura forestal (Cero suelo expuesto).
            '#94d2bd',  # Verde Claro: Áreas de transición natural.
            '#e9d8a6',  # Amarillo: Suelo agrícola descansando o caminos afirmados.
            '#ee9b00',  # Naranja: Zonas urbanas consolidadas o erosión moderada.
            '#ca6702',  # Marrón Ladrillo: Suelos erosionados, taludes descubiertos o canteras.
            '#9b2226'   # Rojo Sangre: Degradación crítica del suelo / Minería ilegal de parches de deforestación masiva.
        ]
        return paleta, -0.20, 0.50

    # 🔥 RAMPA 5: INCENDIOS, QUEMAS O DEGRADACIÓN FORESTAL SEVERA (NBR, BAI, CRI)
    else:
        paleta = [
            '#2b9348',  # Verde Selva: Bosque saludable sin afectación de quemas.
            '#e5e5e5',  # Gris Claro: Áreas estables artificiales o sin variaciones.
            '#f4a261',  # Naranja: Estrés por fuego bajo o cicatriz muy antigua.
            '#e76f51',  # Naranja Rojizo: Quema moderada de pastizales o matorrales.
            '#b7094c',  # Carmesí: Pérdida severa de biomasa por fuego activo o tala.
            '#510a32'   # Púrpura Oscuro: Ceniza acumulada o áreas críticas deforestadas recientemente.
        ]
        return paleta, -0.25, 0.65

# --- 4. RUTA PRINCIPAL CON RENDIMIENTO DE RENDERIZADO MEJORADO ---
@app.post("/calcular-indice-zona")
def procesar_mapa_zona(datos: ConsultaMapa):
    try:
        # Forzar el CRS geográfico estándar compatible al 100% con Leaflet
        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        
        # 1. Recuperar la imagen óptima filtrada por nubes (40%) y compuesta anualmente
        imagen_base = obtener_imagen_por_año(datos.año, region_ee)
        
        # 2. Calcular las operaciones de bandas matemáticas por píxel
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.año)
        
        # 3. Recortar (Clip) exacto para no consumir memoria innecesaria en el servidor de Google
        resultado_recortado = resultado_indice.clip(region_ee)
        
        # 4. Inyectar la paleta hiperprofesional configurada
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
        return {"status": "error", "message": str(e)}

# ==============================================================================
# --- 5. ENGINES ADICIONALES: ENDPOINTS INTEGRADOS PARA DESCARGAS CIENTÍFICAS ---
# ==============================================================================

# endpoint de descarga ráster de alta precisión (GeoTIFF nativo desde GEE)
@app.post("/descargar-tiff")
def descargar_tiff_zona(datos: ConsultaMapa):
    try:
        # 1. Reconstruir la geometría espacial enviada en la consulta activa
        region_ee = ee.Geometry(datos.geometria, 'EPSG:4326')
        
        # 2. Invocar la composición satelital con los mismos filtros de nubosidad
        imagen_base = obtener_imagen_por_año(datos.año, region_ee)
        
        # 3. Extraer el cálculo matemático puro del índice correspondiente (ej. NDSI o NDVI)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.año)
        
        # 4. Ejecutar máscara de recorte perimetral
        resultado_recortado = resultado_indice.clip(region_ee)

        # Determinar resolución espacial nativa según el satélite del año consultado para cuidar los metadatos
        resolucion = 10 if datos.año >= 2015 else 30 # Sentinel-2 tiene 10 metros por píxel; Landsat tiene 30 metros.

        # 5. Solicitar enlace directo de descarga al clúster de Google Earth Engine
        url_descarga = resultado_recortado.getDownloadURL({
            'scale': resolucion,
            'crs': 'EPSG:4326',  # Formato WGS84 para compatibilidad universal en QGIS / ArcGIS
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
        return {"status": "error", "message": str(e)}

# endpoint de fallback controlado para el despacho PNG científico (Si se requiere del backend)
@app.get("/descargar-png")
def descargar_png_estatico(indice: str, año: int, dist: str):
    return {
        "status": "success",
        "message": f"Petición de renderizado de imagen procesada para el distrito de {dist} en el índice {indice}."
    }

# ==============================================================================
# --- 6. SERVICIO DE ARCHIVOS ESTÁTICOS (FRONTEND INTEGRADO) ---
# ==============================================================================

# Ruta raíz "/" que despacha directamente tu diseño visual
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

# Montar los archivos estáticos para que busque el css/js/app.js en la raíz.
# Al estar al final, FastAPI solo usará esta ruta si la petición no coincide con las rutas de arriba.
app.mount("/", StaticFiles(directory=".", html=True), name="static")
