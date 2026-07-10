/*=======================================================================
        GEOSPATIAL PERÚ - app.js
        Controlador principal GIS con Integración Científica
=======================================================================*/

/*==========================
    MAPA LEAFLET
==========================*/

const map = L.map('map').setView([-9.19, -75.0152], 6);

// capa base estándar internacional
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Capa global para el polígono GeoJSON dinámico
let capaGeoJson;
// marcador global informativo
let marker;

/*==========================
    ELEMENTOS DOM
==========================*/

const departamento = document.getElementById("departamento");
const provincia = document.getElementById("provincia");
const distrito = document.getElementById("distrito");

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
    RESULTADOS CARDS
==========================*/

const areaTotal = document.querySelector(".result-card:nth-child(1) h1");
const valorProm = document.querySelector(".result-card:nth-child(2) h1");
const valorMax = document.querySelector(".result-card:nth-child(3) h1");
const valorMin = document.querySelector(".result-card:nth-child(4) h1");

/*=======================================================================
    NUEVA RELACIÓN CIENTÍFICA: OBJETIVOS -> ÍNDICES ESPECTRALES
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
    // Encapsulamos la carga inicial en un bloque seguro para evitar bloqueos infinitos de la pantalla
    try {
        cargarDepartamentosReal(); // Carga la data real de forma segura de ubigeo.js
        actualizarIndicesPorObjetivo(); // Ejecución inicial del filtro de índices espectrales
        validarYFiltrarAniosPorSatelite(); // Filtra los años válidos basándose en el satélite inicial
    } catch (error) {
        console.error("⚠️ Error controlado en inicialización de recursos:", error);
    } finally {
        // Oculta la pantalla de carga pase lo que pase, garantizando la visibilidad del sistema
        const loader = document.getElementById("loader");
        if (loader) {
            loader.style.display = "none";
        }
    }

    setTimeout(() => { map.invalidateSize(); }, 400); // Forzar a Leaflet a recalcular dimensiones
    console.log("GeoSpatial Perú inicializado con Layout corregido y candados cronológicos.");
};

/*==================================================
    LÓGICA DINÁMICA DE ÍNDICES ESPECTRALES
==================================================*/

function actualizarIndicesPorObjetivo() {
    const objSeleccionado = objetivo.value;
    const listaindices = indicesPorObjetivo[objSeleccionado] || [];

    indice.innerHTML = "";

    listaindices.forEach(ind => {
        let opt = document.createElement("option");
        opt.value = ind;
        opt.textContent = ind;
        indice.appendChild(opt);
    });
}

// Escuchar cambios en el selector de objetivos para actualizar el selector de índices
objetivo.addEventListener("change", actualizarIndicesPorObjetivo);

/*==================================================
    FILTRADO DINÁMICO DE AÑOS OPERATIVOS REALES
==================================================*/

function validarYFiltrarAniosPorSatelite() {
    const satSeleccionado = satelite.value;
    const rango = limitesSatelites[satSeleccionado] || { min: 1985, max: 2026, def: 2020 };

    // Guardar selecciones previas para intentar mantener la persistencia si entra en el rango
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

    // Asignar el año por defecto seguro del satélite o mantener el previo si es compatible
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

// Monitorear el cambio de sensor satelital para actualizar las restricciones temporales de inmediato
satelite.addEventListener("change", validarYFiltrarAniosPorSatelite);


/*==================================================
    LÓGICA DE UBIGEO REAL Y DINÁMICO
==================================================*/

function cargarDepartamentosReal() {
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

/*==========================
    EVENTO CONSULTAR
==========================*/

let capaSatelitalGEE = null;
let ultimaGeometriaConsultada = null;

btnConsultar.addEventListener("click", async () => {
    const dep = departamento.value;
    const prov = provincia.value;
    const dist = distrito.value;
    const ind = indice.value;
    const sat = satelite.value;
    const anioIni = anioInicio.value;
    const anioFin = anioFinal.value;

    if (!dep || dep === "Seleccione...") {
        alert("Selecciona al menos un departamento para inicializar la consulta cartográfica.");
        return;
    }

    if (parseInt(anioIni) > parseInt(anioFin)) {
        alert("Error de Periodo: El Año Inicial no puede ser mayor que el Año Final seleccionado.");
        return;
    }

    // Encendemos el loader dinámico para procesos de teledetección pesados
    const loader = document.getElementById("loader");
    if (loader) loader.style.display = "flex";

    if (capaGeoJson && map.hasLayer(capaGeoJson)) map.removeLayer(capaGeoJson);
    if (marker && map.hasLayer(marker)) map.removeLayer(marker);
    if (capaSatelitalGEE && map.hasLayer(capaSatelitalGEE)) map.removeLayer(capaSatelitalGEE);

    let archivosAPescar = [];
    let nivelFiltro = ""; // Guardará si es DEP, PROV o DIST para flexibilizar la lectura
    let valorFiltro = "";
    let tituloPopup = "";

    if (dist && dist !== "Seleccione...") {
        archivosAPescar = [
            "distrito1.geojson", 
            "distrito2.geojson", 
            "distrito3.geojson", 
            "distrito4.geojson", 
            "distrito5.geojson", 
            "distrito6.geojson",
            "distrito7.geojson"
        ];
        nivelFiltro = "DISTRITO";
        valorFiltro = dist;
        tituloPopup = `Distrito: ${dist}`;
    } else if (prov && prov !== "Seleccione...") {
        archivosAPescar = [
            "provincia1.geojson",
            "provincia2.geojson",
            "provincia3.geojson",
            "provincia4.geojson"
        ];
        nivelFiltro = "PROVINCIA";
        valorFiltro = prov;
        tituloPopup = `Provincia: ${prov}`;
    } else {
        archivosAPescar = ["departamentos.geojson"];
        nivelFiltro = "DEPARTAMENTO";
        valorFiltro = dep;
        tituloPopup = `Departamento: ${dep}`;
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

                // --- SISTEMA TOLERANTE AUTOMÁTICO DE ATRIBUTOS ---
                // Lee dinámicamente nombres completos, abreviados o con prefijos de QGIS/INEI
                let propLugar = f.properties[nivelFiltro] || 
                                f.properties[nivelFiltro.substring(0, 9)] || // Ej: DEPARTAMEN en lugar de DEPARTAMENTO
                                f.properties[`NOM_${nivelFiltro.substring(0, 4)}`] || // Ej: NOM_PROV, NOM_DIST
                                f.properties[`NOMB${nivelFiltro.substring(0, 3)}`] || // Ej: NOMBDIST
                                f.properties["NOM_CAP"] || 
                                "";

                let propDep = f.properties["DEPARTAMEN"] || 
                              f.properties["DEPARTAMENTO"] || 
                              f.properties["NOM_DEP"] || 
                              f.properties["NOMDEP"] || 
                              "";

                const textoPropiedad = normalizarTexto(propLugar);
                const textoDepartamento = normalizarTexto(propDep);

                // Si buscamos solo a nivel de región/departamento completo
                if (nivelFiltro === "DEPARTAMENTO") {
                    return textoPropiedad === valorBuscadoNormalizado || textoDepartamento === depBuscadoNormalizado;
                }

                // Si buscamos provincia/distrito, debe validar que esté dentro de la región seleccionada
                return textoPropiedad === valorBuscadoNormalizado && textoDepartamento === depBuscadoNormalizado;
            });

            if (filtradosEnParte.length > 0) {
                featuresFiltrados = filtradosEnParte;
                break; 
            }
        }

        if (featuresFiltrados.length === 0) {
            alert(`Límites geométricos no encontrados en ninguna de las partes del sistema para: ${valorFiltro} (${dep}). Revisa los atributos internos de tus archivos GeoJSON.`);
            if (loader) loader.style.display = "none";
            return;
        }

        const geojsonFiltrado = { type: "FeatureCollection", features: featuresFiltrados };
        const estiloPoligono = { color: "#e74c3c", weight: 3, opacity: 0.9, fillColor: "#f1c40f", fillOpacity: 0.15 };

        capaGeoJson = L.geoJSON(geojsonFiltrado, { style: estiloPoligono }).addTo(map);
        const limites = capaGeoJson.getBounds();
        
        if (limites.isValid()) {
            map.fitBounds(limites);
            const centro = limites.getCenter();
            let popText = `<b>${tituloPopup}</b><br>Prov: ${prov}<br>Dist: ${dist}<br><b>Índice:</b> ${ind}`;
            marker = L.marker(centro).addTo(map).bindPopup(popText).openPopup();
        }

        indiceNombre.textContent = ind;
        sensor.textContent = sat;
        anio.textContent = anioIni === anioFin ? `${anioIni}` : `${anioIni} - ${anioFin}`;

        const geometryParaPython = featuresFiltrados[0].geometry;
        ultimaGeometriaConsultada = geometryParaPython;

        const respuestaBackend = await fetch('http://127.0.0.1:8000/calcular-indice-zona', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                indice: ind,
                año: parseInt(anioIni),
                geometria: geometryParaPython
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

            areaTotal.textContent = (resultadoBackend.area_km2 || 0) + " km²";
            valorProm.textContent = resultadoBackend.val_prom || "0.000";
            valorMax.textContent = resultadoBackend.val_max || "0.000";
            valorMin.textContent = resultadoBackend.val_min || "0.000";

            agregarTabla(dep, prov, dist, ind, anioIni, sat, resultadoBackend.area_km2 || "0");
        } else {
            generarResultadosManejoFallas();
            agregarTabla(dep, prov, dist, ind, anioIni, sat, "Error GEE");
        }

    } catch (error) {
        console.error(error);
        alert("Error de red o procesamiento con servidores GEE.");
        generarResultadosManejoFallas();
    } toggleLoader: {
        if (loader) loader.style.display = "none";
    }
});

/*==========================
    PROCESADOR DE TABLA 
==========================*/

function agregarTabla(dep, prov, dist, ind, anioIni, sat, areaKm2) {
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
    areaTotal.textContent = "N/A km²";
    valorProm.textContent = "0.000";
    valorMax.textContent = "0.000";
    valorMin.textContent = "0.000";
}

/*==========================
    LIMPIAR PANEL Y CAPAS
==========================*/

btnLimpiar.addEventListener("click", () => {
    cargarDepartamentosReal();
    provincia.innerHTML = '<option value="Seleccione...">Seleccione...</option>';
    distrito.innerHTML = '<option value="Seleccione...">Seleccione...</option>';

    satelite.value = "Landsat 5";
    validarYFiltrarAniosPorSatelite();
    
    objetivo.value = "Vegetación";
    actualizarIndicesPorObjetivo();

    indiceNombre.textContent = "NDVI";
    sensor.textContent = "Landsat 5";
    anio.textContent = "2010";

    areaTotal.textContent = "0 km²";
    valorProm.textContent = "0.00";
    valorMax.textContent = "0.00";
    valorMin.textContent = "0.00";

    tabla.innerHTML = "";

    if (capaGeoJson && map.hasLayer(capaGeoJson)) map.removeLayer(capaGeoJson);
    if (marker && map.hasLayer(marker)) map.removeLayer(marker);
    if (capaSatelitalGEE && map.hasLayer(capaSatelitalGEE)) map.removeLayer(capaSatelitalGEE);

    ultimaGeometriaConsultada = null;

    map.setView([-9.19, -75.0152], 6);
});

/*==========================
    GEOFOCALIZACIÓN Y FULLSCREEN
==========================*/

document.querySelector(".toolbar-right button:nth-child(2)").addEventListener("click", () => {
    map.locate({ setView: true, maxZoom: 10 });
    map.on("locationfound", e => {
        if (marker && map.hasLayer(marker)) map.removeLayer(marker);
        marker = L.marker(e.latlng).addTo(map).bindPopup("Ubicación actual GPS").openPopup();
    });
});

document.querySelector(".toolbar-right button:nth-child(3)").addEventListener("click", () => {
    const elem = document.getElementById("map");
    if (!document.fullscreenElement) {
        elem.requestFullscreen();
    } else {
        document.exitFullscreen();
    }
});

/*=======================================================================
    SISTEMA DE DESCARGAS CIENTÍFICAS MEJORADO
=======================================================================*/

const BASE_URL_API_REAL = "http://127.0.0.1:8000";

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
                alert("❌ Error: " + data.message);
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
        if (departamento.value === "Seleccione...") return alert("⚠️ Realiza una consulta primero.");
        window.location.href = `${BASE_URL_API_REAL}/descargar-shp?dep=${departamento.value}&prov=${provincia.value}&dist=${distrito.value}`;
    });
}

if (btnPng) {
    btnPng.addEventListener("click", (e) => {
        e.preventDefault();
        if (departamento.value === "Seleccione...") return alert("⚠️ Realiza una consulta primero.");
        
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

        try {
            const response = await fetch(`${BASE_URL_API_REAL}/descargar-pdf`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    departamento: departamento.value,
                    provincia: provincia.value,
                    distrito: distrito.value,
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
                link.download = `REPORTE_${indice.value}.pdf`;
                link.click();
            }
        } catch (error) {
            alert("❌ Error al descargar el reporte PDF.");
        } finally {
            if (loader) loader.style.display = "none";
        }
    });
}
