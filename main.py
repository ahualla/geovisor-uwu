from fastapi import FastAPI, HTTPException, status
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
    description="Backend de alto rendimiento blindado contra payloads vacíos para Google Earth Engine",
    version="4.0.0"
)

# --- CONFIGURACIÓN DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INICIALIZACIÓN SEGURA DE GOOGLE EARTH ENGINE ---
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
            print("✔ GEE conectado usando credenciales por defecto.")
except Exception as e:
    print("❌ Error crítico de conexión inicial con Earth Engine:", str(e))


# --- MODELOS DE DATOS (PYDANTIC) ---
INDICES_SOPORTADOS = ["NDVI", "EVI", "SAVI", "GCI", "MSAVI", "ARVI", "NDRE", "NDWI", "MNDWI", "NDMI", "LSWI", "NDSI", "BAI", "BSI", "NBR", "CRI"]

class ConsultaMapa(BaseModel):
    indice: str
    anio: Union[int, str] = Field(..., alias="año")
    geometria: Dict[str, Any]

    @field_validator('anio', mode='before')
    @classmethod
    def limpiar_anio(cls, v):
        try:
            return int(v)
        except (ValueError, TypeError):
            raise ValueError("El año debe ser un número entero válido.")

    @field_validator('indice')
    @classmethod
    def validar_indice(cls, v):
        if v.upper() not in INDICES_SOPORTADOS:
            raise ValueError(f"Índice '{v}' no soportado.")
        return v.upper()

    @property
    def año(self) -> int:
        return int(self.anio)

class DatosReportePDF(ConsultaMapa):
    departamento: str
    provincia: str
    distrito: str
    satelite: str


# --- PROCESADORES DE IMÁGENES SATELITALES ---
def obtener_imagen_por_año(año, region_ee):
    start_date = f"{año}-01-01"
    end_date = f"{año}-12-31"

    if año >= 2015:  # Sentinel-2
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)  
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40)))
        if coleccion.size().getInfo() == 0:
            raise ValueError(f"No se encontraron imágenes Sentinel-2 válidas (sin nubes) para el año {año} en esta zona.")
        img = coleccion.median()
        return img.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11'], ['BLUE', 'GREEN', 'RED', 'RED_EDGE', 'NIR', 'SWIR'])

    elif año >= 2013:  # Landsat 8
        coleccion = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        if coleccion.size().getInfo() == 0:
            raise ValueError(f"No se encontraron imágenes Landsat 8 para el año {año} en esta zona.")
        img = coleccion.median()
        return img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'], ['BLUE', 'GREEN', 'RED', 'NIR', 'SWIR']).addBands(ee.Image(0).rename('RED_EDGE'))

    else:  # Landsat 5
        coleccion = (ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
                     .filterDate(start_date, end_date)
                     .filterBounds(region_ee)
                     .filter(ee.Filter.lt('CLOUD_COVER', 40)))
        if coleccion.size().getInfo() == 0:
            raise ValueError(f"No hay registros limpios en el archivo histórico de Landsat 5 para el año {año}.")
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


# --- CAPA DE SEGURIDAD INTERNA: EXTRACTOR UNIVERSAL DE GEOMETRÍAS ---
def procesar_pipeline_gee(datos: ConsultaMapa):
    geom_cruda = datos.geometria
    
    # Validador y extractor robusto de GeoJSON
    if not geom_cruda or not isinstance(geom_cruda, dict):
        raise ValueError("El cuerpo de la geometría está vacío o no es un JSON válido.")
        
    # Si viene envuelto en un FeatureCollection extrae el primer elemento
    if geom_cruda.get("type") == "FeatureCollection" and "features" in geom_cruda:
        if len(geom_cruda["features"]) == 0:
            raise ValueError("El FeatureCollection no contiene ningún polígono válido.")
        geom_cruda = geom_cruda["features"][0]
        
    # Si viene envuelto en un Feature extrae la geometría interna
    if geom_cruda.get("type") == "Feature" and "geometry" in geom_cruda:
        geom_cruda = geom_cruda["geometry"]
        
    # Verificación final de coordenadas básicas antes de enviarlo a los servidores de Google
    if "coordinates" not in geom_cruda or not geom_cruda["coordinates"]:
        raise ValueError("Estructura GeoJSON inválida: No se encontraron 'coordinates' válidas en la petición.")

    try:
        region_ee = ee.Geometry(geom_cruda, 'EPSG:4326').buffer(0)
    except Exception as ex_geom:
        raise ValueError(f"Google Earth Engine no pudo mapear este polígono. Detalles geométricos: {str(ex_geom)}")
    
    imagen_base = obtener_imagen_por_año(datos.año, region_ee)
    resultado_indice = calcular_todos_los_indices(imagen_base, datos.indice, datos.año)
    resultado_recortado = resultado_indice.clip(region_ee)
    
    scale = 10 if datos.año >= 2015 else 30
    
    try:
        area_km2 = round(region_ee.area(maxError=1).getInfo() / 1000000.0, 2)
        if area_km2 <= 0.0:
            raise ValueError("El polígono dibujado tiene un área de 0 km² o está superpuesto erróneamente.")
    except Exception:
        area_km2 = 0.0
    
    # Forzar el cálculo inmediato en GEE. Si la zona procesada arroja nulos, se detiene el flujo aquí.
    try:
        estadisticas = resultado_recortado.reduceRegion(
            reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.max(), sharedInputs=True).combine(reducer2=ee.Reducer.min(), sharedInputs=True),
            geometry=region_ee,
            scale=scale,
            maxPixels=1e9
        ).getInfo()
    except Exception as ex_gee:
        raise ValueError(f"Fallo matemático al calcular los píxeles de la zona. Asegúrate de que las coordenadas correspondan a Perú. Detalles: {str(ex_gee)}")
    
    if not estadisticas or list(estadisticas.values())[0] is None:
        raise ValueError("El análisis espacial retornó valores vacíos (NaN/Null). La zona seleccionada no contiene imágenes de satélite legibles en este período.")

    nombre_banda = datos.indice.upper()
    val_prom = f"{round(estadisticas.get(f'{nombre_banda}_mean') or 0.0, 3):.3f}"
    val_max = f"{round(estadisticas.get(f'{nombre_banda}_max') or 0.0, 3):.3f}"
    val_min = f"{round(estadisticas.get(f'{nombre_banda}_min') or 0.0, 3):.3f}"
    
    return {
        "imagen_recortada": resultado_recortado,
        "region_ee": region_ee,
        "area_km2": area_km2,
        "scale": scale,
        "val_prom": val_prom,
        "val_max": val_max,
        "val_min": val_min
    }


# --- ENDPOINTS OPTIMIZADOS ---

@app.post("/calcular-indice-zona")
def procesar_mapa_zona(datos: ConsultaMapa):
    try:
        pipeline = procesar_pipeline_gee(datos)
        paleta, min_val, max_val = obtener_paleta_y_rangos(datos.indice)
        map_id_dict = pipeline["imagen_recortada"].getMapId({'min': min_val, 'max': max_val, 'palette': paleta})
        
        return {
            "status": "success",
            "indice": datos.indice.upper(),
            "año": datos.año,
            "tile_url": map_id_dict['tile_fetcher'].url_format,
            "area_km2": pipeline["area_km2"],
            "val_prom": pipeline["val_prom"],
            "val_max": pipeline["val_max"],
            "val_min": pipeline["val_min"]
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en GEE: {str(e)}")


@app.post("/descargar-tiff")
def descargar_tiff_zona(datos: ConsultaMapa):
    try:
        pipeline = procesar_pipeline_gee(datos)
        url_descarga = pipeline["imagen_recortada"].getDownloadURL({
            'scale': pipeline["scale"],
            'crs': 'EPSG:4326',
            'region': pipeline["region_ee"],
            'format': 'GEO_TIFF'
        })
        return {"status": "success", "download_url": url_descarga}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/descargar-pdf")
def descargar_pdf_reporte(datos: DatosReportePDF):
    if not REPORTLAB_DISPONIBLE:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ReportLab no configurado en este entorno.")
        
    try:
        # El pipeline arrojará un error explícito si la geometría o los datos espaciales están en blanco
        pipeline = procesar_pipeline_gee(datos)
        buffer = io.BytesIO()
        
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        
        styles = getSampleStyleSheet()
        style_titulo = ParagraphStyle('T1', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0F3A20'), spaceAfter=12)
        style_sub = ParagraphStyle('T2', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#2C3E50'), spaceAfter=8)
        style_txt = ParagraphStyle('TXT', parent=styles['Normal'], fontSize=10, leading=14)
        style_th = ParagraphStyle('TH', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.white)

        story.append(Paragraph("GEOPORTAL NACIONAL PERUANO — REPORTE TÉCNICO GEOESPACIAL", style_titulo))
        story.append(Paragraph(f"<b>Ubicación:</b> {datos.departamento} -> {datos.provincia} -> {datos.distrito}", style_txt))
        story.append(Paragraph(f"<b>Satélite Utilizado:</b> {datos.satelite} | <b>Motor de cálculo:</b> GEE Cloud Engine", style_txt))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("Resultados Estadísticos del Análisis de Píxeles", style_sub))
        
        tabla_datos = [
            [Paragraph("Métrica Evaluada", style_th), Paragraph("Valor Calculado", style_th)],
            [Paragraph("Índice Espectral Seleccionado", style_txt), Paragraph(datos.indice.upper(), style_txt)],
            [Paragraph("Año de Muestreo Temporal", style_txt), Paragraph(str(datos.año), style_txt)],
            [Paragraph("Superficie Evaluada (km²)", style_txt), Paragraph(f"{pipeline['area_km2']} km²", style_txt)],
            [Paragraph("Resolución del Sensor Espacial", style_txt), Paragraph(f"{pipeline['scale']} metros", style_txt)],
            [Paragraph("Valor Medio Obtenido (Mean)", style_txt), Paragraph(pipeline["val_prom"], style_txt)],
            [Paragraph("Valor Máximo Encontrado (Max)", style_txt), Paragraph(pipeline["val_max"], style_txt)],
            [Paragraph("Valor Mínimo Encontrado (Min)", style_txt), Paragraph(pipeline["val_min"], style_txt)],
        ]
        
        t = Table(tabla_datos, colWidths=[240, 240])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (1,0), colors.HexColor('#0F3A20')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F8F9F9'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(KeepTogether([t]))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("<b>Certificación:</b> Archivo generado dinámicamente conectando los servidores de procesamiento espacial. Sistema de Referencia Geográfico base: WGS84 / EPSG:4326.", style_txt))
        
        doc.build(story)
        buffer.seek(0)
        
        return StreamingResponse(
            buffer, 
            media_type="application/pdf", 
            headers={"Content-Disposition": f"attachment; filename=REPORTE_{datos.indice.upper()}_{datos.año}.pdf"}
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al estructurar el PDF: {str(e)}")


@app.post("/descargar-shp")
def descargar_shp_data(datos: DatosReportePDF):
    try:
        pipeline = procesar_pipeline_gee(datos)
        
        # Mapeo blindado de atributos para la tabla .dbf del Shapefile (Conversiones explícitas de tipo)
        feature = ee.Feature(pipeline["region_ee"], {
            'DEPARTAMEN': str(datos.departamento)[:254], 
            'PROVINCIA': str(datos.provincia)[:254],
            'DISTRITO': str(datos.distrito)[:254],
            'INDICE': str(datos.indice.upper()),
            'ANIO': int(datos.año),
            'AREA_KM2': float(pipeline["area_km2"]),
            'VAL_PROM': float(pipeline["val_prom"])
        })
        
        fc = ee.FeatureCollection([feature])
        
        url_shp_gee = fc.getDownloadURL(
            filetype='SHP', 
            selectors=['DEPARTAMEN', 'PROVINCIA', 'DISTRITO', 'INDICE', 'ANIO', 'AREA_KM2', 'VAL_PROM'], 
            filename='Geoportal_Export_Vectorial'
        )
        
        respuesta_gee = requests.get(url_shp_gee, timeout=30)
        if respuesta_gee.status_code != 200:
            raise ValueError("Google Earth Engine no pudo empaquetar los archivos internos del Shapefile.")
            
        buffer_zip = io.BytesIO(respuesta_gee.content)
        buffer_zip.seek(0)
        
        filename_limpio = f"SHP_{datos.departamento}_{datos.provincia}_{datos.distrito}".replace(" ", "_")
        return StreamingResponse(
            buffer_zip, 
            media_type="application/zip", 
            headers={"Content-Disposition": f"attachment; filename={filename_limpio}.zip"}
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Falla en la compresión SHP: {str(e)}")


# --- ENRUTAMIENTO ESTÁTICO DE INTERFAZ ---
@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>✔ Servidor Backend Activo y Protegido</h1>"

app.mount("/", StaticFiles(directory=".", html=True), name="static")
