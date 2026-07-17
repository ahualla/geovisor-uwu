from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Union
import ee
import os
import json
import io
import requests

# --- VERIFICACIÓN Y CARGA DE REPORTLAB ---
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    REPORTLAB_DISPONIBLE = True
except ImportError:
    REPORTLAB_DISPONIBLE = False

app = FastAPI(
    title="Geoportal Nacional Peruano API",
    description="Backend de alto rendimiento para análisis geoespacial con Google Earth Engine",
    version="3.0.0"
)

# --- CONFIGURACIÓN DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INICIALIZACIÓN DE GOOGLE EARTH ENGINE ---
try:
    gee_json_env = os.environ.get("GEE_JSON")
    if gee_json_env:
        info_credenciales = json.loads(gee_json_env)
        credentials = ee.ServiceAccountCredentials(
            info_credenciales['client_email'], 
            key_data=json.dumps(info_credenciales)
        )
        ee.Initialize(credentials, project='ee-tesistambopata1')
        print("✔ GEE conectado en producción.")
    else:
        ruta_json_local = "ee-tesistambopata1-ecf622e54bef.json" 
        if os.path.exists(ruta_json_local):
            credentials = ee.ServiceAccountCredentials.from_json_keyfile(ruta_json_local)
            ee.Initialize(credentials, project='ee-tesistambopata1')
            print(f"✔ GEE conectado localmente usando: {ruta_json_local}")
        else:
            ee.Initialize(project='ee-tesistambopata1')
            print("✔ GEE conectado.")
except Exception as e:
    print("❌ Error de conexión con Earth Engine:", str(e))


# --- MODELOS DE DATOS (Mapeo estricto y flexible frontend/backend) ---
INDICES_SOPORTADOS = ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE", "NDWI", "MNDWI", "NDMI", "LSWI", "NDSI", "BAI", "BSI", "NBR", "CRI"]

class ConsultaMapa(BaseModel):
    indice: str
    anio: Any = Field(..., alias="año")  # Mapea dinámicamente "año" desde JS a la variable local "anio"
    geometria: Dict[str, Any]

    @field_validator('anio', mode='before')
    @classmethod
    def limpiar_anio(cls, v):
        try:
            if isinstance(v, dict): 
                return int(list(v.values())[0])
            return int(v)
        except (ValueError, TypeError):
            raise ValueError("El año debe ser un número entero válido.")

    @field_validator('indice')
    @classmethod
    def validar_indice(cls, v):
        if v.upper() not in INDICES_SOPORTADOS:
            raise ValueError(f"Índice '{v}' no soportado.")
        return v.upper()

class DatosReportePDF(BaseModel):
    indice: str
    anio: Any = Field(..., alias="año")
    geometria: Dict[str, Any]
    departamento: str
    provincia: str
    distrito: str
    satelite: str


# --- PROCESADORES SATELITALES ---
def obtener_imagen_por_año(año, region_ee):
    start_date = f"{año}-01-01"
    end_date = f"{año}-12-31"

    if año >= 2015:  # Sentinel-2
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)  
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40)))
        img = coleccion.median()
        return img.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11'], ['BLUE', 'GREEN', 'RED', 'RED_EDGE', 'NIR', 'SWIR'])

    elif año >= 2013:  # Landsat 8
        coleccion = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        img = coleccion.median()
        return img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR']).addBands(ee.Image(0).rename('RED_EDGE'))

    else:  # Landsat 5
        coleccion = (ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        img = coleccion.median()
        return img.select(['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR']).addBands(ee.Image(0).rename('RED_EDGE'))


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

    if ind == "NDVI": return image.normalizedDifference(['NIR', 'RED']).rename('NDVI')
    elif ind == "EVI": return image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))', {'NIR': nir, 'RED': red, 'BLUE': blue}).rename('EVI')
    elif ind == "SAVI": return image.expression('((NIR - RED) / (NIR + RED + 0.5)) * 1.5', {'NIR': nir, 'RED': red}).rename('SAVI')
    elif ind == "GCI": return image.expression('(NIR / GREEN) - 1', {'NIR': nir, 'GREEN': green}).rename('GCI')
    elif ind == "MSAVI": return image.expression('(2 * NIR + 1 - ((2 * NIR + 1)**2 - 8 * (NIR - RED))**0.5) / 2', {'NIR': nir, 'RED': red}).rename('MSAVI')
    elif ind == "ARVI": return image.expression('(NIR - (RED - (BLUE - RED))) / (NIR + (RED - (BLUE - RED)))', {'NIR': nir, 'RED': red, 'BLUE': blue}).rename('ARVI')
    elif ind == "NDRE": return image.normalizedDifference(['NIR', 'RED_EDGE']).rename('NDRE')
    elif ind == "NDWI": return image.normalizedDifference(['GREEN', 'NIR']).rename('NDWI')
    elif ind == "MNDWI": return image.normalizedDifference(['GREEN', 'SWIR']).rename('MNDWI')
    elif ind in ["NDMI", "LSWI"]: return image.normalizedDifference(['NIR', 'SWIR']).rename(ind)
    elif ind == "NDSI": return image.normalizedDifference(['GREEN', 'SWIR']).rename('NDSI')
    elif ind == "BAI": return image.expression('(SWIR / RED) - 1', {'SWIR': swir, 'RED': red}).rename('BAI')
    elif ind == "BSI": return image.expression('((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))', {'SWIR': swir, 'RED': red, 'NIR': nir, 'BLUE': blue}).rename('BSI')
    elif ind == "NBR": return image.normalizedDifference(['NIR', 'SWIR']).rename('NBR')
    elif ind == "CRI": return image.expression('(SWIR / GREEN) - 1', {'SWIR': swir, 'GREEN': green}).rename('CRI')
    
    return image.normalizedDifference(['NIR', 'RED']).rename('NDVI')


def obtener_paleta_y_rangos(indice_nombre):
    ind = indice_nombre.upper()
    if ind in ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE"]:
        return ['#4a3319', '#8c6239', '#c69c6d', '#e6d594', '#b3e09b', '#78c679', "#25b904", '#238443', "#008A2A"], -0.05, 0.85
    elif ind in ["NDWI", "MNDWI", "NDMI", "LSWI"]:
        return ['#fcfaf2', '#d0f4de', '#a8ded9', '#43a2ca', '#0868ac', '#012a4a'], -0.15, 0.70
    elif ind == "NDSI":
        return ['#ffffff', '#e0f7fa', '#80deea', '#00b4d8', '#003049'], 0.15, 0.90
    elif ind == "BSI":
        return ['#005f73', '#94d2bd', '#e9d8a6', '#ee9b00', '#ca6702', '#9b2226'], -0.20, 0.50
    else:
        return ['#2b9348', '#e5e5e5', '#f4a261', '#e76f51', '#b7094c', '#510a32'], -0.25, 0.65


# --- ENDPOINTS ---

@app.post("/calcular-indice-zona")
def procesar_mapa_zona(datos: ConsultaMapa):
    try:
        region_ee = ee.Geometry(datos.geometria)
        imagen_base = obtener_imagen_por_año(datos.anio, region_ee)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.anio)
        resultado_recortado = resultado_indice.clip(region_ee)
        
        # --- CÁLCULO DE ESTADÍSTICAS ---
        area_calculada = region_ee.area().divide(1000000).getInfo()
        
        stats = resultado_recortado.reduceRegion(
            reducer=ee.Reducer.mean().combine(
                reducer2=ee.Reducer.minMax(),
                sharedInputs=True
            ),
            geometry=region_ee,
            scale=30,
            maxPixels=1e9,
            bestEffort=True
        ).getInfo()
        
        if not stats:
            stats = {}
            
        nombre_banda = datos.indice.upper()
        valor_promedio = stats.get(f"{nombre_banda}_mean", 0.0)
        valor_maximo = stats.get(f"{nombre_banda}_max", 0.0)
        valor_minimo = stats.get(f"{nombre_banda}_min", 0.0)
        
        # Ajuste preventivo frente a nulos
        valor_promedio = 0.0 if valor_promedio is None else valor_promedio
        valor_maximo = 0.0 if valor_maximo is None else valor_maximo
        valor_minimo = 0.0 if valor_minimo is None else valor_minimo

        paleta, min_val, max_val = obtener_paleta_y_rangos(datos.indice)
        map_id_dict = resultado_recortado.getMapId({'min': min_val, 'max': max_val, 'palette': paleta})
        
        # Diccionario estructurado idénticamente a las llaves asociadas de app.js
        return {
            "status": "success",
            "indice": datos.indice.upper(),
            "año": datos.anio,
            "tile_url": map_id_dict['tile_fetcher'].url_format,
            "area_km2": round(area_calculada, 2),
            "val_prom": round(valor_promedio, 3),
            "val_max": round(valor_maximo, 3),
            "val_min": round(valor_minimo, 3)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/descargar-tiff")
def descargar_tiff_zona(datos: ConsultaMapa):
    try:
        region_ee = ee.Geometry(datos.geometria)
        imagen_base = obtener_imagen_por_año(datos.anio, region_ee)
        resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.anio)
        resultado_recortado = resultado_indice.clip(region_ee)
        
        scale = 10 if datos.anio >= 2015 else 30
        url_descarga = resultado_recortado.getDownloadURL({
            'scale': scale,
            'crs': 'EPSG:4326',
            'region': region_ee,
            'format': 'GEO_TIFF'
        })
        return {"status": "success", "download_url": url_descarga}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/descargar-pdf")
def descargar_pdf_reporte(datos: DatosReportePDF):
    if not REPORTLAB_DISPONIBLE:
        raise HTTPException(status_code=500, detail="ReportLab no disponible.")
        
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        
        styles = getSampleStyleSheet()
        style_titulo = ParagraphStyle('T1', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0F3A20'), spaceAfter=12)
        style_sub = ParagraphStyle('T2', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#2C3E50'), spaceAfter=8)
        style_txt = ParagraphStyle('TXT', parent=styles['Normal'], fontSize=10, leading=14)
        style_th = ParagraphStyle('TH', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.white)

        story.append(Paragraph("GEOPORTAL NACIONAL PERUANO — REPORTE TÉCNICO", style_titulo))
        story.append(Paragraph(f"<b>Ubicación:</b> {datos.departamento} -> {datos.provincia} -> {datos.distrito}", style_txt))
        story.append(Paragraph(f"<b>Satélite:</b> {datos.satelite}", style_txt))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("Resultados del Análisis", style_sub))
        
        tabla_datos = [
            [Paragraph("Métrica", style_th), Paragraph("Valor", style_th)],
            [Paragraph("Índice Seleccionado", style_txt), Paragraph(datos.indice.upper(), style_txt)],
            [Paragraph("Año", style_txt), Paragraph(str(datos.anio), style_txt)],
        ]
        
        t = Table(tabla_datos, colWidths=[240, 240])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (1,0), colors.HexColor('#0F3A20')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
        ]))
        story.append(KeepTogether([t]))
        
        doc.build(story)
        buffer.seek(0)
        
        return StreamingResponse(
            buffer, 
            media_type="application/pdf", 
            headers={"Content-Disposition": f"attachment; filename=REPORTE_{datos.indice.upper()}_{datos.anio}.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/descargar-shp")
def descargar_shp_data(datos: DatosReportePDF):
    try:
        region_ee = ee.Geometry(datos.geometria)
        feature = ee.Feature(region_ee, {
            'DEPARTAMEN': datos.departamento, 
            'PROVINCIA': datos.provincia,
            'DISTRITO': datos.distrito,
            'INDICE': datos.indice.upper(),
            'ANIO': datos.anio
        })
        
        fc = ee.FeatureCollection([feature])
        url_shp_gee = fc.getDownloadURL(
            filetype='SHP', 
            selectors=['DEPARTAMEN', 'PROVINCIA', 'DISTRITO', 'INDICE', 'ANIO'], 
            filename='Geoportal_Export'
        )
        
        respuesta_gee = requests.get(url_shp_gee, timeout=30)
        buffer_zip = io.BytesIO(respuesta_gee.content)
        buffer_zip.seek(0)
        
        return StreamingResponse(
            buffer_zip, 
            media_type="application/zip", 
            headers={"Content-Disposition": "attachment; filename=export_shp.zip"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- ENRUTAMIENTO ESTÁTICO DE SEGURIDAD ---
@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>✔ Servidor Backend Activo</h1>"

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
