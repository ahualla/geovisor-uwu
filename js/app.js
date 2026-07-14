/*=======================================================================
        GEOSPATIAL PERÚ - app.js
        Controlador principal GIS con Integración Científica y ANPs
        
        AUTOR ORIGINAL: Ing. Ambiental Alessandro Alonso Ahualla Molina
        CANAL DE YOUTUBE: Proyectos SIG
        LINK CANAL: https://youtube.com/@proyectossig?si=odNULsfVOKs7vOdW
        ID CANAL: UCisFhGgE5XmibX07QTUFhaA
=======================================================================*/

/*==========================
    MAPA LEAFLET
==========================*/

const map = L.map('map').setView([-9.19, -75.0152], 6);

// Capa base estándar internacional
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Capa global para el polígono GeoJSON dinámico
let capaGeoJson;
// Marcador global informativo
let marker;

/*==========================
    ELEMENTOS DOM
==========================*/

// Selectores de Tipo de Consulta y Áreas Ambientales
const tipoConsulta = document.getElementById("tipoConsulta");
const grupoAmbiental = document.getElementById("grupoAmbiental");
const capaAmbiental = document.getElementById("capaAmbiental");
const nombreArea = document.getElementById("nombreArea");

// Selectores políticos tradicionales
const departamento = document.getElementById("departamento");
const provincia = document.getElementById("provincia");
const distrito = document.getElementById("distrito");
const grupoPolitico = document.getElementById("grupoPolitico");

const anioInicio = document.getElementById("anioInicio");
const anioFinal = document.getElementById("anioFinal");

const satelite = document.getElementById("satelite");
const indice = document.getElementById("indice");
const objetivo = document.getElementById("objetivo");

const btnConsultar = document.getElementById("consultar");
const btnLimpiar = document.getElementById("limpiar");

/*==========================
    INFO PANEL
==========================*/

const indiceNombre = document.getElementById("indiceNombre");
const sensor = document.getElementById("sensor");
const anio = document.getElementById("anio");

/*==========================
    TABLA
==========================*/

const tabla = document.getElementById("tablaResultados");

/*==========================
    RESULTADOS CARDS (CON DOBLE COMPATIBILIDAD DE ID Y CLASE)
==========================*/

const areaTotal = document.getElementById("resArea") || document.querySelector(".result-card:nth-child(1) h1");
const valorProm = document.getElementById("resProm") || document.querySelector(".result-card:nth-child(2) h1");
const valorMax = document.getElementById("resMax") || document.querySelector(".result-card:nth-child(3) h1");
const valorMin = document.getElementById("resMin") || document.querySelector(".result-card:nth-child(4) h1");

/*=======================================================================
    RELACIÓN CIENTÍFICA: OBJETIVOS -> ÍNDICES ESPECTRALES
=======================================================================*/
const indicesPorObjetivo = {
    "Vegetación": ["NDVI", "EVI", "SAVI", "MSAVI", "GNDVI", "GCI", "ARVI", "NDRE"],
    "Agua": ["NDWI", "MNDWI", "NDMI", "LSWI"],
    "Área Glacial": ["NDSI"],
    "Temperatura": ["LST"],
    "Suelo": ["BI", "BSI", "BAI"],
    "Área Urbana": ["NDBI"],
    "Incendios y Antropización": ["NBR", "CRI"]
};

/*=======================================================================
    VALIDACIÓN CIENTÍFICA DE TEMPORALIDAD POR SATÉLITE
=======================================================================*/
const limitesSatelites = {
    "Landsat 5": { min: 1984, max: 2011, def: 2010 },
    "Landsat 7": { min: 1999, max: 2021, def: 2015 },
    "Landsat 8": { min: 2013, max: 2026, def: 2020 },
    "Landsat 9": { min: 2021, max: 2026, def: 2023 },
    "Sentinel 2": { min: 2015, max: 2026, def: 2022 }
};

/*==========================
    INICIALIZACIÓN
==========================*/

window.onload = () => {
    try {
        cargarDepartamentosReal(); 
        actualizarIndicesPorObjetivo(); 
        validarYFiltrarAniosPorSatelite(); 
        escucharCambiosTipoConsulta(); 
    } catch (error) {
        console.error("⚠️ Error controlado en inicialización de recursos:", error);
    } finally {
        const loader = document.getElementById("loader");
        if (loader) {
            loader.style.opacity = '0';
            setTimeout(() => { loader.style.display = "none"; }, 500);
        }
    }

    setTimeout(() => { map.invalidateSize(); }, 400); 
    console.log("GeoSpatial Perú inicializado correctamente. Desarrollado por Alessandro Alonso Ahualla Molina.");
};

/*==================================================
    INTERFAZ DINÁMICA (POLÍTICO VS AMBIENTAL)
==================================================*/

function escucharCambiosTipoConsulta() {
    if (tipoConsulta) {
        tipoConsulta.addEventListener("change", () => {
            if (tipoConsulta.value === "conservacion") {
                if (grupoAmbiental) grupoAmbiental.style.display = "block";
                if (grupoPolitico) grupoPolitico.style.display = "none";
                deshabilitarUbigeo(true);
            } else {
                if (grupoAmbiental) grupoAmbiental.style.display = "none";
                if (grupoPolitico) grupoPolitico.style.display = "block";
                deshabilitarUbigeo(false);
            }
        });
    }

    if (capaAmbiental) {
        capaAmbiental.addEventListener("change", actualizarAreasEspecificas);
    }
}

function deshabilitarUbigeo(deshabilitar) {
    if (departamento) departamento.disabled = deshabilitar;
    if (provincia) provincia.disabled = deshabilitar;
    if (distrito) distrito.disabled = deshabilitar;
}

// Escáner Híbrido Unificador: Lee geojsons y junta sectores duplicados en el selector visual
async function actualizarAreasEspecificas() {
    if (!capaAmbiental || !nombreArea) return;
    
    const capa = capaAmbiental.value;
    nombreArea.innerHTML = "";
    
    if (capa === "Seleccione...") {
        nombreArea.disabled = true;
        nombreArea.innerHTML = '<option value="Seleccione...">Seleccione una categoría primero...</option>';
        return;
    }
    
    nombreArea.disabled = true;
    nombreArea.innerHTML = '<option value="Seleccione...">Mapeando y unificando registros espaciales...</option>';
    
    let archivosAPescar = [];
    if (capa === "acp") archivosAPescar = ["acp.geojson"];
    else if (capa === "acr") archivosAPescar = ["acr.geojson"];
    else if (capa === "zona_reservada") archivosAPescar = ["zona_reservada.geojson"];
    else if (capa === "anpdefinitivas") archivosAPescar = ["anpdefinitivas.geojson"];
    else if (capa === "zona_de_amortiguamiento") archivosAPescar = ["zona_de_amortiguamiento1.geojson", "zona_de_amortiguamiento2.geojson"];
    
    try {
        let mapaItems = new Map(); // Guarda -> Nombre: { etiqueta: string, partes: número }

        for (const url of archivosAPescar) {
            const response = await fetch(url);
            if (!response.ok) {
                console.warn(`No se pudo leer el archivo: ${url}`);
                continue;
            }
            
            const geojsonData = await response.json();
            
            geojsonData.features.forEach(f => {
                if (!f.properties) return;
                
                const props = f.properties;
                const llaves = Object.keys(props);
                
                let nombrePuro = "";
                const llaveNombre = llaves.find(k => 
                    k.toLowerCase() === "anp_nomb" || 
                    k.toLowerCase() === "za_nomb" || 
                    k.toLowerCase() === "acr_nomb" || 
                    k.toLowerCase() === "nombre" ||
                    k.toLowerCase() === "name"
                );
                
                if (llaveNombre && props[llaveNombre]) {
                    nombrePuro = props[llaveNombre].toString().trim();
                } else {
                    const fallbackLlave = llaves.find(k => k.toLowerCase().includes("nomb"));
                    if (fallbackLlave && props[fallbackLlave]) {
                        nombrePuro = props[fallbackLlave].toString().trim();
                    }
                }

                if (!nombrePuro) return;

                const categoria = props["c_nomb"] || props["anp_cate"] || props["anp_tipo"] || props["categoria"] || props["tipo"] || "";
                const ubicacion = props["za_ubig"] || props["anp_ubig"] || props["acr_dep"] || props["ubica"] || props["departamen"] || "";

                let textoVisual = "";
                if (categoria) {
                    textoVisual += `[${categoria.toString().trim().toUpperCase()}] `;
                } else if (capa === "zona_de_amortiguamiento") {
                    textoVisual += `[ZA] `;
                }
                
                textoVisual += nombrePuro.toUpperCase();

                if (ubicacion) {
                    textoVisual += ` - ${ubicacion.toString().trim().toUpperCase()}`;
                }

                if (mapaItems.has(nombrePuro)) {
                    let existente = mapaItems.get(nombrePuro);
                    existente.partes += 1;
                } else {
                    mapaItems.set(nombrePuro, { etiqueta: textoVisual, partes: 1 });
                }
            });
        }

        const itemsOrdenados = Array.from(mapaItems.entries()).sort((a, b) => 
            a[1].etiqueta.localeCompare(b[1].etiqueta, 'es', { sensitivity: 'base' })
        );

        if (itemsOrdenados.length === 0) {
            nombreArea.innerHTML = '<option value="Seleccione...">No se hallaron registros válidos</option>';
            return;
        }

        nombreArea.innerHTML = '<option value="Seleccione...">Seleccione un área de estudio...</option>';
        itemsOrdenados.forEach(([nombreReal, info]) => {
            let opt = document.createElement("option");
            opt.value = nombreReal;
            opt.textContent = info.partes > 1 ? `${info.etiqueta} (${info.partes} sectores unidos)` : info.etiqueta;
            nombreArea.appendChild(opt);
        });

        nombreArea.disabled = false;

    } catch (error) {
        console.error("❌ Error grave en la carga unificada:", error);
        nombreArea.innerHTML = '<option value="Seleccione...">Error al mapear capas</option>';
    }
}

/*==================================================
    LÓGICA DINÁMICA DE ÍNDICES ESPECTRALES
==================================================*/

function actualizarIndicesPorObjetivo() {
    if (!objetivo || !indice) return;
    const objSeleccionado = objetivo.value;
    const listaIndices = indicesPorObjetivo[objSeleccionado] || [];

    indice.innerHTML = "";

    listaIndices.forEach(ind => {
        let opt = document.createElement("option");
        opt.value = ind;
        opt.textContent = ind;
        indice.appendChild(opt);
    });
}

if (objetivo) {
    objetivo.addEventListener("change", actualizarIndicesPorObjetivo);
}

/*==================================================
    FILTRADO DINÁMICO DE AÑOS OPERATIVOS REALES
==================================================*/

function validarYFiltrarAniosPorSatelite() {
    if (!satelite || !anioInicio || !anioFinal) return;
    const satSeleccionado = satelite.value;
    const rango = limitesSatelites[satSeleccionado] || { min: 1985, max: 2026, def: 2020 };

    const valorPrevioIni = parseInt(anioInicio.value);
    const valorPrevioFin = parseInt(anioFinal.value);

    anioInicio.innerHTML = "";
    anioFinal.innerHTML = "";

    for (let i = rango.min; i <= rango.max; i++) {
        let opt1 = document.createElement("option");
        opt1.value = i;
        opt1.textContent = i;
        
        let opt2 = opt1.cloneNode(true);
        anioInicio.appendChild(opt1);
        anioFinal.appendChild(opt2);
    }

    if (valorPrevioIni >= rango.min && valorPrevioIni <= rango.max) {
        anioInicio.value = valorPrevioIni;
    } else {
        anioInicio.value = rango.def;
    }

    if (valorPrevioFin >= rango.min && valorPrevioFin <= rango.max) {
        anioFinal.value = valorPrevioFin;
    } else {
        anioFinal.value = rango.def;
    }
}

if (satelite) {
    satelite.addEventListener("change", validarYFiltrarAniosPorSatelite);
}

/*==================================================
    LÓGICA DE UBIGEO REAL Y DINÁMICO
==================================================*/

function cargarDepartamentosReal() {
    if (!departamento) return;
    if (typeof dataUbigeo !== 'undefined') {
        departamento.innerHTML = '<option value="Seleccione...">Seleccione...</option>';
        Object.keys(dataUbigeo).forEach(dep => {
            let opt = document.createElement("option");
            opt.value = dep;
            opt.textContent = dep;
            departamento.appendChild(opt);
        });
    } else {
        console.error("Error: 'dataUbigeo' no está definido.");
    }
}

if (departamento) {
    departamento.addEventListener('change', () => {
        const depSeleccionado = departamento.value;
        provincia.innerHTML = '<option value="Seleccione...">Seleccione...</option>';
        distrito.innerHTML = '<option value="Seleccione...">Seleccione...</option>';

        if (depSeleccionado && depSeleccionado !== "Seleccione..." && typeof dataUbigeo !== 'undefined') {
            const provincias = dataUbigeo[depSeleccionado];
            if (provincias) {
                Object.keys(provincias).forEach(prov => {
                    let opt = document.createElement("option");
                    opt.value = prov;
                    opt.textContent = prov;
                    provincia.appendChild(opt);
                });
            }
        }
    });
}

if (provincia) {
    provincia.addEventListener('change', () => {
        const depSeleccionado = departamento.value;
        const provSeleccionada = provincia.value;
        distrito.innerHTML = '<option value="Seleccione...">Seleccione...</option>';

        if (provSeleccionada && provSeleccionada !== "Seleccione..." && typeof dataUbigeo !== 'undefined') {
            const distritos = dataUbigeo[depSeleccionado]?.[provSeleccionada];
            if (distritos) {
                distritos.forEach(dist => {
                    let opt = document.createElement("option");
                    opt.value = dist;
                    opt.textContent = dist;
                    distrito.appendChild(opt);
                });
            }
        }
    });
}

/*==================================================
    FUSIÓN GEOMÉTRICA DE COORDENADAS (MultiPolygon)
==================================================*/
function fusionarGeometrias(features) {
    if (features.length === 1) {
        return features[0].geometry;
    }
    let coordinates = [];
    features.forEach(f => {
        const geom = f.geometry;
        if (geom.type === "Polygon") {
            coordinates.push(geom.coordinates);
        } else if (geom.type === "MultiPolygon") {
            coordinates = coordinates.concat(geom.coordinates);
        }
    });
    return {
        type: "MultiPolygon",
        coordinates: coordinates
    };
}

/*=======================================================================
    SISTEMA DE ENLACE DE BACKEND (URL DE RENDER)
=======================================================================*/
const BASE_URL_API_REAL = "https://geovisor-uwu.onrender.com";

/*==========================
    EVENTO CONSULTAR
==========================*/

let capaSatelitalGEE = null;
let ultimaGeometriaConsultada = null;

if (btnConsultar) {
    btnConsultar.addEventListener("click", async () => {
        const isAmbiental = tipoConsulta && tipoConsulta.value === "conservacion";
        const dep = departamento ? departamento.value : "Seleccione...";
        const prov = provincia ? provincia.value : "Seleccione...";
        const dist = distrito ? distrito.value : "Seleccione...";
        const ind = indice ? indice.value : "";
        const sat = satelite ? satelite.value : "";
        const anioIni = anioInicio ? anioInicio.value : "";
        const anioFin = anioFinal ? anioFinal.value : "";
        
        const capaAmb = capaAmbiental ? capaAmbiental.value : "";
        const nomArea = nombreArea ? nombreArea.value : "";

        // Validaciones de fecha
        if (parseInt(anioIni) > parseInt(anioFin)) {
            alert("Error de Periodo: El Año Inicial no puede ser mayor que el Año Final seleccionado.");
            return;
        }

        const loader = document.getElementById("loader");
        if (loader) loader.style.display = "flex";

        // Limpieza de capas previas
        if (capaGeoJson && map.hasLayer(capaGeoJson)) map.removeLayer(capaGeoJson);
        if (marker && map.hasLayer(marker)) map.removeLayer(marker);
        if (capaSatelitalGEE && map.hasLayer(capaSatelitalGEE)) map.removeLayer(capaSatelitalGEE);

        let archivosAPescar = [];
        let propiedadFiltro = "";
        let valorFiltro = "";
        let tituloPopup = "";

        if (isAmbiental) {
            if (!capaAmb || capaAmb === "Seleccione..." || !nomArea || nomArea === "Seleccione...") {
                alert("⚠️ Selecciona una categoría y un área ambiental de estudio.");
                if (loader) loader.style.display = "none";
                return;
            }
            if (capaAmb === "acp") archivosAPescar = ["acp.geojson"];
            else if (capaAmb === "acr") archivosAPescar = ["acr.geojson"];
            else if (capaAmb === "zona_reservada") archivosAPescar = ["zona_reservada.geojson"];
            else if (capaAmb === "anpdefinitivas") archivosAPescar = ["anpdefinitivas.geojson"];
            else if (capaAmb === "zona_de_amortiguamiento") archivosAPescar = ["zona_de_amortiguamiento1.geojson", "zona_de_amortiguamiento2.geojson"];
            
            valorFiltro = nomArea;
            tituloPopup = `Área: ${nomArea.toUpperCase()} (${capaAmb.toUpperCase()})`;
        } else {
            if (!dep || dep === "Seleccione...") {
                alert("Selecciona al menos un departamento para inicializar la consulta cartográfica.");
                if (loader) loader.style.display = "none";
                return;
            }
            if (dist && dist !== "Seleccione...") {
                archivosAPescar = [
                    "distrito1.geojson", "distrito2.geojson", "distrito3.geojson",
                    "distrito4.geojson", "distrito5.geojson", "distrito6.geojson", "distrito7.geojson"
                ];
                propiedadFiltro = "DISTRITO";
                valorFiltro = dist;
                tituloPopup = `Distrito: ${dist}`;
            } else if (prov && prov !== "Seleccione...") {
                archivosAPescar = ["provincia1.geojson", "provincia2.geojson", "provincia3.geojson", "provincia4.geojson"];
                propiedadFiltro = "PROVINCIA";
                valorFiltro = prov;
                tituloPopup = `Provincia: ${prov}`;
            } else {
                archivosAPescar = ["departamentos.geojson"];
                propiedadFiltro = "DEPARTAMENTO";
                valorFiltro = dep;
                tituloPopup = `Departamento: ${dep}`;
            }
        }

        const normalizarTexto = (str) => {
            if (!str) return "";
            return str.toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().trim();
        };

        try {
            let featuresFiltrados = [];
            const valorBuscadoNormalizado = normalizarTexto(valorFiltro);
            const depBuscadoNormalizado = normalizarTexto(dep);

            for (const url of archivosAPescar) {
                const response = await fetch(url);
                if (!response.ok) continue;

                const geojsonData = await response.json();

                const filtradosEnParte = geojsonData.features.filter(f => {
                    if (!f.properties) return false;

                    if (isAmbiental) {
                        const props = f.properties;
                        const llaves = Object.keys(props);
                        const llaveNombre = llaves.find(k => 
                            k.toLowerCase() === "anp_nomb" || 
                            k.toLowerCase() === "za_nomb" || 
                            k.toLowerCase() === "acr_nomb" || 
                            k.toLowerCase() === "nombre" ||
                            k.toLowerCase() === "name"
                        );
                        let nombreProp = "";
                        if (llaveNombre && props[llaveNombre]) {
                            nombreProp = props[llaveNombre].toString();
                        } else {
                            const fallbackLlave = llaves.find(k => k.toLowerCase().includes("nomb"));
                            if (fallbackLlave && props[fallbackLlave]) {
                                nombreProp = props[fallbackLlave].toString();
                            }
                        }
                        return normalizarTexto(nombreProp) === valorBuscadoNormalizado;
                    } else {
                        let propLugar = f.properties[propiedadFiltro] || 
                                        f.properties[propiedadFiltro.substring(0, 9)] || 
                                        f.properties[`NOM_${propiedadFiltro.substring(0, 4)}`] || 
                                        f.properties[`NOMB${propiedadFiltro.substring(0, 3)}`] || 
                                        f.properties["NOM_CAP"] || "";

                        let propDep = f.properties["DEPARTAMEN"] || 
                                      f.properties["DEPARTAMENTO"] || 
                                      f.properties["NOM_DEP"] || 
                                      f.properties["NOMDEP"] || "";

                        const textoPropiedad = normalizarTexto(propLugar);
                        const textoDepartamento = normalizarTexto(propDep);

                        if (propiedadFiltro === "DEPARTAMENTO") {
                            return textoPropiedad === valorBuscadoNormalizado || textoDepartamento === depBuscadoNormalizado;
                        }
                        return textoPropiedad === valorBuscadoNormalizado && textoDepartamento === depBuscadoNormalizado;
                    }
                });

                if (filtradosEnParte.length > 0) {
                    featuresFiltrados = featuresFiltrados.concat(filtradosEnParte);
                }
            }

            if (featuresFiltrados.length === 0) {
                alert(`Límites geométricos no encontrados para: ${valorFiltro}. Verifica tus archivos GeoJSON.`);
                if (loader) loader.style.display = "none";
                return;
            }

            // Fusión geométrica (Soporte multizona dinámico para todas las capas fragmentadas)
            const geometriaUnificada = fusionarGeometrias(featuresFiltrados);

            const geojsonFiltrado = { 
                type: "FeatureCollection", 
                features: [{ 
                    type: "Feature", 
                    geometry: geometriaUnificada, 
                    properties: { name: valorFiltro } 
                }] 
            };

            const estiloPoligono = isAmbiental ? 
                { color: "#27ae60", weight: 3, opacity: 0.9, fillColor: "#2ecc71", fillOpacity: 0.15 } : 
                { color: "#e74c3c", weight: 3, opacity: 0.9, fillColor: "#f1c40f", fillOpacity: 0.15 };

            capaGeoJson = L.geoJSON(geojsonFiltrado, { style: estiloPoligono }).addTo(map);
            const limites = capaGeoJson.getBounds();

            if (limites.isValid()) {
                map.fitBounds(limites);
                const centro = limites.getCenter();
                const indicadorSectores = featuresFiltrados.length > 1 ? 
                    `<br><span style="color:#27ae60; font-weight:bold;">⚠️ Unificados ${featuresFiltrados.length} sectores espaciales</span>` : "";
                
                let popText = isAmbiental ? 
                    `<b>${tituloPopup}</b>${indicadorSectores}<br><b>Índice:</b> ${ind}<br><b>Satélite:</b> ${sat}` : 
                    `<b>${tituloPopup}</b><br>Prov: ${prov}<br>Dist: ${dist}<br><b>Índice:</b> ${ind}`;
                
                marker = L.marker(centro).addTo(map).bindPopup(popText).openPopup();
            }

            if (indiceNombre) indiceNombre.textContent = ind;
            if (sensor) sensor.textContent = sat;
            if (anio) anio.textContent = anioIni === anioFin ? `${anioIni}` : `${anioIni} - ${anioFin}`;

            ultimaGeometriaConsultada = geometriaUnificada;

            // POST request al backend en Render (Mapeado exacto con "año" para Pydantic)
            const respuestaBackend = await fetch(`${BASE_URL_API_REAL}/calcular-indice-zona`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    indice: ind,
                    año: parseInt(anioIni),
                    geometria: geometriaUnificada
                })
            });

            const resultadoBackend = await respuestaBackend.json();

            if (resultadoBackend.status === "success" && resultadoBackend.tile_url) {
                capaSatelitalGEE = L.tileLayer(resultadoBackend.tile_url, {
                    maxZoom: 18,
                    attribution: 'Google Earth Engine | Geospatial Perú'
                }).addTo(map);
                
                capaGeoJson.setStyle({ fillColor: "transparent", fillOpacity: 0 });
                capaGeoJson.bringToFront();

                // Muestra de valores estadísticos en las tarjetas
                if (areaTotal) areaTotal.textContent = (resultadoBackend.area_km2 || 0) + " km²";
                if (valorProm) valorProm.textContent = resultadoBackend.val_prom || "0.000";
                if (valorMax) valorMax.textContent = resultadoBackend.val_max || "0.000";
                if (valorMin) valorMin.textContent = resultadoBackend.val_min || "0.000";

                const nombreFilaDep = isAmbiental ? "Área Ambiental" : dep;
                const nombreFilaProv = isAmbiental ? capaAmb.toUpperCase() : prov;
                const nombreFilaDist = isAmbiental ? nomArea : dist;

                agregarTabla(nombreFilaDep, nombreFilaProv, nombreFilaDist, ind, anioIni, sat, resultadoBackend.area_km2 || "0");
            } else {
                generarResultadosManejoFallas();
                const nombreFilaDep = isAmbiental ? "Área Ambiental" : dep;
                const nombreFilaProv = isAmbiental ? capaAmb.toUpperCase() : prov;
                const nombreFilaDist = isAmbiental ? nomArea : dist;
                agregarTabla(nombreFilaDep, nombreFilaProv, nombreFilaDist, ind, anioIni, sat, "Error GEE");
            }

        } catch (error) {
            console.error("Error en consulta:", error);
            alert("Error de red o procesamiento con servidores GEE.");
            generarResultadosManejoFallas();
        } finally {
            if (loader) loader.style.display = "none";
        }
    });
}

/*==========================
    PROCESADOR DE TABLA 
==========================*/

function agregarTabla(dep, prov, dist, ind, anioIni, sat, areaKm2) {
    if (!tabla) return;
    const nombreProvincia = (prov === 'Seleccione...' || !prov) ? 'No especificado' : prov;
    const nombreDistrito = (dist === 'Seleccione...' || !dist) ? 'No especificado' : dist;
    
    const row = document.createElement("tr");
    row.innerHTML = `
        <td>${dep}</td>
        <td>${nombreProvincia}</td>
        <td>${nombreDistrito}</td>
        <td>${ind}</td>
        <td>${anioIni}</td>
        <td>${sat}</td>
        <td>${areaKm2} km²</td>
    `;
    tabla.prepend(row);
}

function generarResultadosManejoFallas() {
    if (areaTotal) areaTotal.textContent = "N/A km²";
    if (valorProm) valorProm.textContent = "0.000";
    if (valorMax) valorMax.textContent = "0.000";
    if (valorMin) valorMin.textContent = "0.000";
}

/*==========================
    LIMPIAR PANEL Y CAPAS
==========================*/

if (btnLimpiar) {
    btnLimpiar.addEventListener("click", () => {
        if (tipoConsulta) tipoConsulta.value = "politico";
        if (grupoAmbiental) grupoAmbiental.style.display = "none";
        if (grupoPolitico) grupoPolitico.style.display = "block";
        if (capaAmbiental) capaAmbiental.value = "Seleccione...";
        
        if (nombreArea) {
            nombreArea.innerHTML = '<option value="Seleccione...">Seleccione una categoría primero...</option>';
            nombreArea.disabled = true;
        }

        deshabilitarUbigeo(false);
        cargarDepartamentosReal();

        if (provincia) provincia.innerHTML = '<option value="Seleccione...">Seleccione...</option>';
        if (distrito) distrito.innerHTML = '<option value="Seleccione...">Seleccione...</option>';

        if (satelite) satelite.value = "Landsat 5";
        validarYFiltrarAniosPorSatelite();
        
        if (objetivo) objetivo.value = "Vegetación";
        actualizarIndicesPorObjetivo();

        if (indiceNombre) indiceNombre.textContent = "NDVI";
        if (sensor) sensor.textContent = "Landsat 5";
        if (anio) anio.textContent = "2010";

        if (areaTotal) areaTotal.textContent = "0 km²";
        if (valorProm) valorProm.textContent = "0.00";
        if (valorMax) valorMax.textContent = "0.00";
        if (valorMin) valorMin.textContent = "0.00";

        if (tabla) tabla.innerHTML = "";

        if (capaGeoJson && map.hasLayer(capaGeoJson)) map.removeLayer(capaGeoJson);
        if (marker && map.hasLayer(marker)) map.removeLayer(marker);
        if (capaSatelitalGEE && map.hasLayer(capaSatelitalGEE)) map.removeLayer(capaSatelitalGEE);

        ultimaGeometriaConsultada = null;
        map.setView([-9.19, -75.0152], 6);
    });
}

/*==========================
    GEOFOCALIZACIÓN Y FULLSCREEN
==========================*/

const btnGps = document.querySelector(".toolbar-right button:nth-child(2)");
if (btnGps) {
    btnGps.addEventListener("click", () => {
        map.locate({ setView: true, maxZoom: 10 });
        map.on("locationfound", e => {
            if (marker && map.hasLayer(marker)) map.removeLayer(marker);
            marker = L.marker(e.latlng).addTo(map).bindPopup("Ubicación actual GPS").openPopup();
        });
    });
}

const btnFullscreen = document.querySelector(".toolbar-right button:nth-child(3)");
if (btnFullscreen) {
    btnFullscreen.addEventListener("click", () => {
        const elem = document.getElementById("map");
        if (!elem) return;
        if (!document.fullscreenElement) {
            elem.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    });
}

/*=======================================================================
    SISTEMA DE DESCARGAS CIENTÍFICAS MEJORADO
=======================================================================*/

const btnTiff = document.getElementById("btnTiff");
const btnShp  = document.getElementById("btnShp");
const btnPng  = document.getElementById("btnPng");
const btnPdf  = document.getElementById("btnPdf");

if (btnTiff) {
    btnTiff.addEventListener("click", async (e) => {
        e.preventDefault();
        if (!ultimaGeometriaConsultada) return alert("⚠️ No se detectó ninguna geometría activa procesada.");
        
        const loader = document.getElementById("loader");
        if (loader) loader.style.display = "flex";

        try {
            const response = await fetch(`${BASE_URL_API_REAL}/descargar-tiff`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    indice: indice.value,
                    año: parseInt(anioInicio.value),
                    geometria: ultimaGeometriaConsultada
                })
            });
            const data = await response.json();
            if (data.status === "success" && data.download_url) {
                window.location.href = data.download_url;
            } else {
                alert("❌ Error: " + (data.detail || data.message || "No se pudo generar la descarga"));
            }
        } catch (error) {
            alert("❌ Error conectando con el backend.");
        } finally {
            if (loader) loader.style.display = "none";
        }
    });
}

if (btnShp) {
    btnShp.addEventListener("click", (e) => {
        e.preventDefault();
        const isAmbiental = tipoConsulta && tipoConsulta.value === "conservacion";

        if (!isAmbiental && (departamento.value === "Seleccione..." || !departamento.value)) {
            return alert("⚠️ Realiza una consulta primero.");
        }
        if (isAmbiental && (capaAmbiental.value === "Seleccione..." || !nombreArea.value)) {
            return alert("⚠️ Realiza una consulta primero.");
        }
        
        const pDep = isAmbiental ? "Area Ambiental" : departamento.value;
        const pProv = isAmbiental ? capaAmbiental.value.toUpperCase() : (provincia.value === "Seleccione..." ? "" : provincia.value);
        const pDist = isAmbiental ? nombreArea.value : (distrito.value === "Seleccione..." ? "" : distrito.value);

        window.location.href = `${BASE_URL_API_REAL}/descargar-shp?dep=${pDep}&prov=${pProv}&dist=${pDist}`;
    });
}

if (btnPng) {
    btnPng.addEventListener("click", (e) => {
        e.preventDefault();
        const isAmbiental = tipoConsulta && tipoConsulta.value === "conservacion";
        if (!isAmbiental && departamento.value === "Seleccione...") return alert("⚠️ Realiza una consulta primero.");
        if (isAmbiental && capaAmbiental.value === "Seleccione...") return alert("⚠️ Realiza una consulta primero.");

        const contenedorMapa = document.getElementById("map");
        if (typeof html2canvas !== "undefined" && contenedorMapa) {
            const loader = document.getElementById("loader");
            if (loader) loader.style.display = "flex";

            html2canvas(contenedorMapa, { useCORS: true }).then(canvas => {
                const link = document.createElement("a");
                link.download = `MAPA_${indice.value}_${anioInicio.value}.png`;
                link.href = canvas.toDataURL("image/png");
                link.click();
            }).finally(() => {
                if (loader) loader.style.display = "none";
            });
        }
    });
}

if (btnPdf) {
    btnPdf.addEventListener("click", async (e) => {
        e.preventDefault();
        if (!ultimaGeometriaConsultada) return alert("⚠️ No hay consulta activa.");
        
        const loader = document.getElementById("loader");
        if (loader) loader.style.display = "flex";

        const isAmbiental = tipoConsulta && tipoConsulta.value === "conservacion";

        try {
            const response = await fetch(`${BASE_URL_API_REAL}/descargar-pdf`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    departamento: isAmbiental ? "Área Ambiental" : departamento.value,
                    provincia: isAmbiental ? capaAmbiental.value.toUpperCase() : provincia.value,
                    distrito: isAmbiental ? nombreArea.value : distrito.value,
                    indice: indice.value,
                    año: parseInt(anioInicio.value),
                    satelite: satelite.value,
                    geometria: ultimaGeometriaConsultada
                })
            });
            if (response.ok) {
                const blob = await response.blob();
                const link = document.createElement("a");
                link.href = window.URL.createObjectURL(blob);
                link.download = `REPORTE_${indice.value}_${anioInicio.value}.pdf`;
                link.click();
            } else {
                alert("❌ El servidor reportó un error al estructurar el reporte PDF.");
            }
        } catch (error) {
            alert("❌ Error al descargar el reporte PDF.");
        } finally {
            if (loader) loader.style.display = "none";
        }
    });
}
