#!/usr/bin/env python3
# =============================================================================
# etl_educacion_educ.py — Capa escolar de OnLife Afro desde los microdatos EDUC 2023
# -----------------------------------------------------------------------------
# Complemento de etl_educacion_cnpv.py. Los dos scripts miden educación, pero no
# lo mismo y no sobre la misma unidad:
#
#   · etl_educacion_cnpv.py  → CENSO de población. Unidad: la persona en su hogar.
#                              Responde «¿asiste? ¿sabe leer? ¿hasta dónde llegó?»
#   · etl_educacion_educ.py  → CENSO de sedes educativas (formulario C600).
#                              Unidad: la sede y la jornada. Responde «¿cuántos
#                              están matriculados, quiénes son y qué pasó con
#                              ellos al terminar el año?»
#
# Las dos cifras NO se promedian. Se publican por separado, con su unidad de
# observación declarada, tal como exige el apartado 3.7.6 de la tesis.
#
# Archivos de entrada (microdatos EDUC del Archivo Nacional de Datos del DANE):
#   Alumnos_pertenecientes_a_grupos_étnicos_según_sexo_por_nivel_educativo_y_jornada.CSV
#   Tipo_de_matrícula_propia_o_contratada_según_nivel_educativo_por_jornada.CSV
#   Situación_académica_al_finalizar_el_año_escolar_2022_según_educación_tradicional_por_jornada.CSV
#   Tenencia__acceso_y_uso_de_los_bienes_y_servicios_TIC_por_sede_educativa.CSV
#
# El municipio se deduce de SEDE_CODIGO: es un código de doce dígitos cuyos
# caracteres 2 a 6 son el código DANE del municipio (76109 = Buenaventura).
#
# Uso:
#   python etl_educacion_educ.py --microdatos ./educ2023 --municipio 76109 \
#       --salida data/
# =============================================================================

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

VERSION = "1.1"
FUENTE = ("DANE–MEN — Educación Formal (EDUC) 2023, microdatos por sede educativa "
          "y jornada, formulario único censal C600")

ARCHIVOS = {
    "etnico": "Alumnos_pertenecientes_a_grupos_étnicos_según_sexo_por_nivel_educativo_y_jornada.CSV",
    "matricula": "Tipo_de_matrícula_propia_o_contratada_según_nivel_educativo_por_jornada.CSV",
    "situacion": "Situación_académica_al_finalizar_el_año_escolar_2022_según_educación_tradicional_por_jornada.CSV",
    "tic": "Tenencia__acceso_y_uso_de_los_bienes_y_servicios_TIC_por_sede_educativa.CSV",
    "personal": "Personal_ocupado_en_la_sede_educativa.CSV",
    "vinculacion": ("Docentes_ocupados_en_la_sede_educativa_según_escalafón_"
                    "y_tipo_de_vinculación_laboral.CSV"),
    "nivel_docente": ("Docentes_por_jornada_según_máximo_nivel_educativo_alcanzado_"
                      "y_rangos_de_edad.CSV"),
    "poblacion": "Población_escolar_atendida_en_la_sede_educativa.CSV",
}

# Archivos opcionales: si no están en la carpeta, el script omite el bloque
# correspondiente en lugar de fallar. Permite correr el ETL con una descarga
# parcial del Archivo Nacional de Datos.
OPCIONALES = {"personal", "vinculacion", "nivel_docente", "poblacion", "tic"}

# GRUPOETN_ID según el codebook DDI de la operación: la categoría analítica NARP
# del proyecto agrupa 3 (negro/mulato/afrocolombiano), 4 (raizal) y 5 (palenquero).
CODIGOS_NARP = {"3", "4", "5"}

CAMPOS_TIC = [
    ("TIENEELECTRICIDAD", "Electricidad"),
    ("TIENEINTERNET", "Internet"),
    ("TIENEEQUIPOCOMPUTO", "Equipos de cómputo"),
    ("TIENEAULASINFORMATICA", "Aula de informática"),
    ("TIENELAN", "Red local (LAN)"),
    ("TIENETELEVISION", "Televisión"),
    ("TIENELINEATELEFONICA", "Línea telefónica"),
    ("TIENERADIO", "Radio"),
]

ORDEN_NIVEL = ["Preescolar", "Básica primaria", "Básica secundaria", "Media", "CLEI"]


def municipio_de(sede_codigo: str) -> str:
    return sede_codigo[1:6] if len(sede_codigo) >= 6 else ""


def normaliza_nivel(nombre: str) -> str:
    n = (nombre or "").strip()
    return "CLEI" if n.startswith("CLEI") else n


def entero(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0




# =============================================================================
# Resolución de archivos por nombre aproximado
# -----------------------------------------------------------------------------
# El Archivo Nacional de Datos entrega cada cuadro en su propio ZIP, y al
# descomprimirlos quedan carpetas cuyo nombre pierde tildes, cambia guiones bajos
# por espacios y a veces se trunca. Exigir una ruta exacta obligaría a renombrar
# a mano quince carpetas; en vez de eso, cada archivo se busca por palabras clave
# dentro del árbol que se pase en --microdatos.
# =============================================================================
def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    for signo in ("_", "-", ",", ".", "(", ")"):
        s = s.replace(signo, " ")
    return " ".join(s.upper().split())


def _candidatos(raiz):
    """Todos los CSV bajo la raíz, con su ruta normalizada para comparar."""
    encontrados = []
    if os.path.isfile(raiz):
        return [(raiz, _norm(os.path.basename(raiz)))]
    for base, _, nombres in os.walk(raiz):
        for n in nombres:
            if not n.lower().endswith((".csv", ".txt")):
                continue
            ruta = os.path.join(base, n)
            # se compara contra el nombre del archivo y el de su carpeta: el DANE
            # a veces pone el título del cuadro en uno y a veces en la otra
            etiqueta = _norm(os.path.basename(base) + " " + n)
            encontrados.append((ruta, etiqueta))
    return encontrados


def resolver(raiz, palabras, descripcion="", excluir=(), requiere=()):
    """Ubica el archivo de un cuadro por nombre y lo confirma por sus columnas.

    El nombre solo no basta. «Tipo de matrícula propia o contratada» y «Alumnos
    matriculados según tipo de población especial» comparten las palabras «tipo»
    y «matrícula», y elegir el equivocado no produce un error visible: produce
    un KeyError en mitad del cálculo, o algo peor, una cifra plausible extraída
    de la tabla que no era. Por eso, cuando hay más de un candidato, se abre la
    cabecera de cada uno y se conserva el que trae las columnas que el indicador
    necesita. La ambigüedad se resuelve con evidencia, no con una heurística de
    profundidad de carpeta.
    """
    # La comparación es por palabra completa y no por subcadena. Buscar «TIC»
    # como subcadena encuentra ochenta y seis archivos, porque aparece dentro de
    # «características» y de «estadística»; buscarla como palabra encuentra el
    # cuadro de tenencia de bienes y servicios TIC y ninguno más.
    palabras = [_norm(p) for p in palabras]
    excluir = [_norm(p) for p in excluir]
    coincide = []
    for ruta, etiqueta in _candidatos(raiz):
        tokens = set(etiqueta.split())
        if all(p in tokens for p in palabras) and not any(x in tokens for x in excluir):
            coincide.append(ruta)
    if not coincide:
        return None
    coincide.sort(key=lambda r: (len(r.split(os.sep)), len(r)))
    if len(coincide) == 1 or not requiere:
        if len(coincide) > 1:
            print(f"  aviso: {len(coincide)} archivos coinciden con "
                  f"«{descripcion}»; se usa {os.path.relpath(coincide[0], raiz)}")
        return coincide[0]

    validos = []
    for ruta in coincide:
        try:
            lector, f = abrir_csv(ruta)
            campos = {(_norm(c)) for c in (lector.fieldnames or [])}
            f.close()
        except SystemExit:
            continue
        if all(_norm(c) in campos for c in requiere):
            validos.append(ruta)
    if not validos:
        # No se descarta el candidato: se avisa. Los nombres de columna cambian
        # entre ediciones de la operación estadística, y detener el proceso por
        # una comprobación que puede estar desactualizada sería peor que
        # intentar leerlo y decir con precisión qué falló.
        print(f"  aviso: {len(coincide)} archivo(s) coinciden de nombre con "
              f"«{descripcion}» pero no se pudo confirmar que traigan "
              f"{', '.join(requiere)}; se usa "
              f"{os.path.relpath(coincide[0], raiz)} y se verá al leerlo.")
        return coincide[0]
    if len(validos) > 1:
        print(f"  aviso: {len(validos)} archivos válidos para «{descripcion}»; "
              f"se usa {os.path.relpath(validos[0], raiz)}")
    elif len(coincide) > 1:
        print(f"  «{descripcion}» → {os.path.relpath(validos[0], raiz)} "
              f"(descartados {len(coincide) - 1} por columnas)")
    return validos[0]


def ruta_larga(ruta):
    """Devuelve la ruta en forma utilizable por Windows cuando supera 260 caracteres.

    Windows limita las rutas a 260 caracteres salvo que se use el prefijo de ruta
    extendida. Los nombres de los cuadros del DANE son largos —y al descomprimir
    quedan repetidos como carpeta y como archivo—, de modo que basta con dos
    niveles para pasarse del límite: os.walk los encuentra, pero open() falla con
    «No such file or directory» sobre un archivo que existe y se ve en el
    explorador. El prefijo elimina el problema sin afectar a Linux ni a macOS.
    """
    if os.name != "nt":
        return ruta
    absoluta = os.path.abspath(ruta)
    if absoluta.startswith("\\\\?\\"):
        return absoluta
    if absoluta.startswith("\\\\"):
        return "\\\\?\\UNC" + absoluta[1:]
    return "\\\\?\\" + absoluta


def abrir_csv(ruta):
    """Abre resolviendo codificación y delimitador, que varían entre entregas."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            f = open(ruta_larga(ruta), newline="", encoding=encoding)
            cabecera = f.readline()
            f.seek(0)
            delim = ";" if cabecera.count(";") > cabecera.count(",") else ","
            return csv.DictReader(f, delimiter=delim), f
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"✗ No se pudo leer {ruta} en utf-8 ni en latin-1.")


# Palabras clave por archivo. Se eligieron para distinguir cuadros parecidos: hay
# dos «Situación académica al finalizar el año escolar», uno por educación
# tradicional y otro por modelos educativos flexibles, y solo el primero es el
# que alimenta las tasas de eficiencia interna del apartado 3.7.6.
# Para cada cuadro: palabras que debe contener el nombre, palabras que lo
# descartan, y columnas que el archivo tiene que traer para ser el correcto.
# Las columnas son el criterio decisivo; el nombre solo reduce la búsqueda.
PALABRAS = {
    "etnico":        (["ALUMNOS", "GRUPOS", "ETNICOS"], ["ESPECIAL"],
                      ["SEDE_CODIGO", "GRUPOETN_ID", "JORNETN_CANTIDAD_HOMBRE"]),
    "matricula":     (["MATRICULA"], ["ETNICOS", "ESPECIAL", "POBLACION"],
                      ["SEDE_CODIGO", "TIPOMATRI_NOMBRE", "JORMAT_CANTIDAD_ALUMNO"]),
    "situacion":     (["SITUACION", "ACADEMICA"], ["MODELOS"],
                      ["SEDE_CODIGO", "SITUACADE_NOMBRE", "JORNSITU_CANTIDAD_HOMBRE"]),
    "tic":           (["TENENCIA", "USO"], ["FRECUENCIA", "ACTIVIDADES"],
                      ["SEDE_CODIGO", "TIENEINTERNET"]),
    "personal":      (["PERSONAL", "OCUPADO"], ["DOCENTES"],
                      ["SEDE_CODIGO", "SEDEPERO_CANTIDAD_HOMBRE"]),
    "vinculacion":   (["DOCENTES", "OCUPADOS"], ["JORNADA"],
                      ["SEDE_CODIGO", "VINCULA_NOMBRE", "SEDEDOC_CANTIDAD_HOMBRE"]),
    "nivel_docente": (["DOCENTES", "JORNADA"], [],
                      ["SEDE_CODIGO", "NIVELEDUCDOC_NOMBRE", "JORDOC_CANTIDAD_HOMBRE"]),
    "poblacion":     (["POBLACION", "ESCOLAR"], [],
                      ["SEDE_CODIGO", "POBLACION_NOMBRE"]),
}

_CACHE = {}


def ruta_de(carpeta, clave):
    """Ubica el archivo de un cuadro, primero por nombre exacto y luego por
    palabras clave. El resultado se memoriza: el árbol se recorre una sola vez
    por cuadro aunque varios indicadores lo consulten."""
    if (carpeta, clave) in _CACHE:
        return _CACHE[(carpeta, clave)]
    exacta = os.path.join(carpeta, ARCHIVOS[clave])
    ruta = exacta if os.path.exists(exacta) else None
    if ruta is None:
        palabras, excluir, requiere = PALABRAS[clave]
        ruta = resolver(carpeta, palabras, clave, excluir, requiere)
    _CACHE[(carpeta, clave)] = ruta
    return ruta


def disponible(carpeta, clave):
    return ruta_de(carpeta, clave) is not None


def leer(carpeta, clave, municipio=None):
    """Itera un archivo de microdato EDUC, opcionalmente filtrado por municipio."""
    ruta = ruta_de(carpeta, clave)
    if ruta is None:
        if clave in OPCIONALES:
            return
        palabras, _, requiere = PALABRAS[clave]
        raise SystemExit(
            f"✗ No se encontró bajo {carpeta} ningún CSV cuyo nombre contenga "
            f"{', '.join(palabras)} y que traiga las columnas "
            f"{', '.join(requiere)}.\n"
            f"  Descomprime el cuadro correspondiente del catálogo EDUC y vuelve "
            f"a ejecutar; no hace falta renombrar nada.")
    lector, f = abrir_csv(ruta)
    try:
        for fila in lector:
            if municipio and municipio_de(fila.get("SEDE_CODIGO", "")) != municipio:
                continue
            yield fila
    finally:
        f.close()


# =============================================================================
# Indicadores
# =============================================================================
def matricula_etnica(carpeta, municipio):
    """Matrícula por grupo étnico, nivel y sexo. Devuelve tabla larga y totales."""
    conteo = defaultdict(Counter)
    sedes = set()
    for r in leer(carpeta, "etnico", municipio):
        sedes.add(r["SEDE_CODIGO"])
        nivel = normaliza_nivel(r["NIVELENSE_NOMBRE"])
        grupo = "NARP" if r["GRUPOETN_ID"] in CODIGOS_NARP else r["GRUPOETN_NOMBRE"]
        conteo[(grupo, nivel)]["Hombre"] += entero(r["JORNETN_CANTIDAD_HOMBRE"])
        conteo[(grupo, nivel)]["Mujer"] += entero(r["JORNETN_CANTIDAD_MUJER"])
    tabla = []
    for (grupo, nivel), c in conteo.items():
        tabla.append({"grupo": grupo, "nivel_educativo": nivel,
                      "hombres": c["Hombre"], "mujeres": c["Mujer"],
                      "total": c["Hombre"] + c["Mujer"]})
    tabla.sort(key=lambda r: (r["grupo"] != "NARP", r["grupo"],
                              ORDEN_NIVEL.index(r["nivel_educativo"])
                              if r["nivel_educativo"] in ORDEN_NIVEL else 99))
    return tabla, sedes


def matricula_total(carpeta, municipio):
    """Matrícula total por nivel y por tipo (propia o contratada)."""
    por_nivel, por_tipo = Counter(), Counter()
    for r in leer(carpeta, "matricula", municipio):
        q = entero(r["JORMAT_CANTIDAD_ALUMNO"])
        por_nivel[normaliza_nivel(r["NIVELENSE_NOMBRE"])] += q
        por_tipo[r["TIPOMATRI_NOMBRE"]] += q
    return por_nivel, por_tipo


def eficiencia_interna(carpeta, municipio):
    """Aprobación, reprobación y deserción al cierre del año lectivo anterior."""
    conteo = defaultdict(Counter)
    for r in leer(carpeta, "situacion", municipio):
        q = (entero(r["JORNSITU_CANTIDAD_HOMBRE"])
             + entero(r["JORNSITU_CANTIDAD_MUJER"]))
        conteo[normaliza_nivel(r["NIVELENSE_NOMBRE"])][r["SITUACADE_NOMBRE"]] += q
    tabla, global_ = [], Counter()
    for nivel, c in conteo.items():
        global_.update(c)
        base = c["Aprobados"] + c["Reprobados"] + c["Desertores"]
        if not base:
            continue
        tabla.append({
            "nivel_educativo": nivel,
            "aprobados": c["Aprobados"], "reprobados": c["Reprobados"],
            "desertores": c["Desertores"],
            "transferidos": c["Transferidos/Transladados"],
            "base": base,
            "tasa_aprobacion_pct": round(100 * c["Aprobados"] / base, 1),
            "tasa_reprobacion_pct": round(100 * c["Reprobados"] / base, 1),
            "tasa_desercion_pct": round(100 * c["Desertores"] / base, 1),
        })
    tabla.sort(key=lambda r: ORDEN_NIVEL.index(r["nivel_educativo"])
               if r["nivel_educativo"] in ORDEN_NIVEL else 99)
    return tabla, global_


def dotacion_tic(carpeta, municipio):
    """Tenencia de bienes y servicios TIC por sede, municipio y total nacional."""
    def contar(mun):
        n, c = 0, Counter()
        for r in leer(carpeta, "tic", mun):
            n += 1
            for campo, _ in CAMPOS_TIC:
                if r.get(campo) == "Si":
                    c[campo] += 1
        return n, c

    n_mun, c_mun = contar(municipio)
    n_nal, c_nal = contar(None)
    tabla = []
    for campo, etiqueta in CAMPOS_TIC:
        tabla.append({
            "bien_o_servicio": etiqueta,
            "sedes_municipio": c_mun[campo],
            "base_municipio": n_mun,
            "pct_municipio": round(100 * c_mun[campo] / n_mun, 1) if n_mun else "",
            "pct_nacional": round(100 * c_nal[campo] / n_nal, 1) if n_nal else "",
            "brecha_pp": (round(100 * c_mun[campo] / n_mun - 100 * c_nal[campo] / n_nal, 1)
                          if n_mun and n_nal else ""),
        })
    return tabla, n_mun, n_nal



def planta_docente(carpeta, municipio):
    """Personal ocupado, vinculación y cualificación de la planta docente.

    Cada bloque se compara con el total nacional, porque el dato municipal por sí
    solo no dice si una cifra es alta o baja: son las brechas las que informan.
    """
    def personal(mun):
        c, mujeres = Counter(), Counter()
        for r in leer(carpeta, "personal", mun):
            h = entero(r["SEDEPERO_CANTIDAD_HOMBRE"])
            m = entero(r["SEDEPERO_CANTIDAD_MUJER"])
            cat = (r["CATEGORIA_NOMBRE"] or "").strip()
            clave = "Docentes de aula" if cat.startswith("Docentes de aula") else cat[:60]
            c[clave] += h + m
            mujeres[clave] += m
        return c, mujeres

    def vinculacion(mun):
        c = Counter()
        for r in leer(carpeta, "vinculacion", mun):
            q = entero(r["SEDEDOC_CANTIDAD_HOMBRE"]) + entero(r["SEDEDOC_CANTIDAD_MUJER"])
            nombre = (r["VINCULA_NOMBRE"] or "")
            c["Planta" if nombre.startswith("Docentes de planta") else "Contrato"] += q
        return c

    def cualificacion(mun):
        c = Counter()
        for r in leer(carpeta, "nivel_docente", mun):
            q = entero(r["JORDOC_CANTIDAD_HOMBRE"]) + entero(r["JORDOC_CANTIDAD_MUJER"])
            c[(r["NIVELEDUCDOC_NOMBRE"] or "").strip()] += q
        return c

    def internados(mun):
        sedes, con_interna = set(), set()
        for r in leer(carpeta, "poblacion", mun):
            sedes.add(r["SEDE_CODIGO"])
            if (r["POBLACION_NOMBRE"] or "").strip().lower().startswith("interna"):
                con_interna.add(r["SEDE_CODIGO"])
        return len(con_interna), len(sedes)

    per_mun, muj_mun = personal(municipio)
    per_nal, _ = personal(None)
    vin_mun, vin_nal = vinculacion(municipio), vinculacion(None)
    cual_mun, cual_nal = cualificacion(municipio), cualificacion(None)
    int_mun = internados(municipio)
    int_nal = internados(None)

    def pct(x, y):
        return round(100 * x / y, 1) if y else ""

    tabla_personal = []
    for cat, v in per_mun.most_common():
        tabla_personal.append({
            "categoria": cat, "personas": v,
            "mujeres": muj_mun[cat], "pct_mujeres": pct(muj_mun[cat], v),
            "pct_del_personal_municipio": pct(v, sum(per_mun.values())),
            "pct_del_personal_nacional": pct(per_nal.get(cat, 0), sum(per_nal.values())),
        })

    base_m, base_n = sum(cual_mun.values()), sum(cual_nal.values())
    tabla_cual = []
    for nivel, v in cual_mun.most_common():
        tabla_cual.append({
            "maximo_nivel_docente": nivel, "docentes_municipio": v,
            "pct_municipio": pct(v, base_m),
            "pct_nacional": pct(cual_nal.get(nivel, 0), base_n),
            "brecha_pp": (round(pct(v, base_m) - pct(cual_nal.get(nivel, 0), base_n), 1)
                          if base_m and base_n else ""),
        })

    resumen = {
        "docentes_aula": per_mun.get("Docentes de aula", 0),
        "docentes_aula_nal": per_nal.get("Docentes de aula", 0),
        "pct_mujeres_aula": pct(muj_mun.get("Docentes de aula", 0),
                                per_mun.get("Docentes de aula", 1)),
        "personal_total": sum(per_mun.values()),
        "pct_contrato": pct(vin_mun["Contrato"], sum(vin_mun.values())),
        "pct_contrato_nal": pct(vin_nal["Contrato"], sum(vin_nal.values())),
        "pct_posgrado": pct(sum(v for k, v in cual_mun.items() if k.startswith("Posgrado")), base_m),
        "pct_posgrado_nal": pct(sum(v for k, v in cual_nal.items() if k.startswith("Posgrado")), base_n),
        "pct_normalista": pct(cual_mun.get("Normalista superior", 0), base_m),
        "pct_normalista_nal": pct(cual_nal.get("Normalista superior", 0), base_n),
        "sedes_con_internado": int_mun[0], "sedes_con_registro_poblacion": int_mun[1],
        "pct_sedes_internado": pct(*int_mun),
        "pct_sedes_internado_nal": pct(*int_nal),
    }
    return tabla_personal, tabla_cual, resumen


def indicadores_titulares(etnica, sedes_etnicas, por_nivel, por_tipo,
                          eficiencia, global_ef, tic, n_sedes_mun, docentes=None):
    narp = sum(r["total"] for r in etnica if r["grupo"] == "NARP")
    total_mat = sum(por_nivel.values())
    base = global_ef["Aprobados"] + global_ef["Reprobados"] + global_ef["Desertores"]
    sec = next((r for r in eficiencia if r["nivel_educativo"] == "Básica secundaria"), None)
    internet = next((r for r in tic if r["bien_o_servicio"] == "Internet"), None)
    luz = next((r for r in tic if r["bien_o_servicio"] == "Electricidad"), None)

    def pct(x, y):
        return round(100 * x / y, 1) if y else None

    extra = []
    if docentes:
        alumnos_docente = (round(total_mat / docentes["docentes_aula"], 1)
                           if docentes["docentes_aula"] else None)
        extra = [
            {"indicador": "Alumnos por docente de aula",
             "valor": alumnos_docente,
             "universo": f"{total_mat} alumnos y {docentes['docentes_aula']} docentes de aula",
             "medicion": "censal (sedes educativas)", "fuente": FUENTE,
             "metodo": "matrícula total / docentes de aula reportados por las sedes"},
            {"indicador": "Docentes con posgrado (%)",
             "valor": docentes["pct_posgrado"],
             "universo": "docentes con asignación académica en el municipio",
             "medicion": "censal (sedes educativas)", "fuente": FUENTE,
             "metodo": f"posgrado pedagógico o no pedagógico / total; nacional "
                       f"{docentes['pct_posgrado_nal']} %"},
            {"indicador": "Docentes cuyo máximo nivel es normalista superior (%)",
             "valor": docentes["pct_normalista"],
             "universo": "docentes con asignación académica en el municipio",
             "medicion": "censal (sedes educativas)", "fuente": FUENTE,
             "metodo": f"normalistas superiores / total; nacional "
                       f"{docentes['pct_normalista_nal']} %"},
            {"indicador": "Sedes educativas que atienden población interna (%)",
             "valor": docentes["pct_sedes_internado"],
             "universo": f"{docentes['sedes_con_registro_poblacion']} sedes con registro de "
                         f"población escolar atendida",
             "medicion": "censal (sedes educativas)", "fuente": FUENTE,
             "metodo": f"sedes con alumnado interno / total de sedes; nacional "
                       f"{docentes['pct_sedes_internado_nal']} %"},
        ]

    return extra + [
        {"indicador": "Matrícula perteneciente a grupos NARP (alumnos)",
         "valor": narp,
         "universo": f"{len(sedes_etnicas)} de {n_sedes_mun} sedes reportaron matrícula étnica",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "suma de GRUPOETN_ID 3, 4 y 5 (negra/mulata/afrodescendiente, raizal, palenquera)"},
        {"indicador": "Participación NARP en la matrícula total (%)",
         "valor": pct(narp, total_mat),
         "universo": f"{total_mat} alumnos matriculados en el municipio",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "matrícula NARP / matrícula total; es un piso, porque no todas las sedes "
                   "diligencian el módulo VI de poblaciones especiales"},
        {"indicador": "Tasa de deserción escolar, todos los niveles (%)",
         "valor": pct(global_ef["Desertores"], base),
         "universo": f"{base} alumnos con situación académica reportada al cierre de 2022",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "desertores / (aprobados + reprobados + desertores)"},
        {"indicador": "Tasa de deserción escolar en básica secundaria (%)",
         "valor": sec["tasa_desercion_pct"] if sec else None,
         "universo": f"{sec['base'] if sec else 0} alumnos de básica secundaria",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "desertores / (aprobados + reprobados + desertores) en el nivel"},
        {"indicador": "Tasa de reprobación escolar, todos los niveles (%)",
         "valor": pct(global_ef["Reprobados"], base),
         "universo": f"{base} alumnos con situación académica reportada al cierre de 2022",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "reprobados / (aprobados + reprobados + desertores)"},
        {"indicador": "Sedes educativas con acceso a internet (%)",
         "valor": internet["pct_municipio"] if internet else None,
         "universo": f"{n_sedes_mun} sedes educativas del municipio",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "sedes que declaran tener internet / total de sedes"},
        {"indicador": "Sedes educativas con servicio de electricidad (%)",
         "valor": luz["pct_municipio"] if luz else None,
         "universo": f"{n_sedes_mun} sedes educativas del municipio",
         "medicion": "censal (sedes educativas)", "fuente": FUENTE,
         "metodo": "sedes que declaran tener electricidad / total de sedes"},
    ]


# =============================================================================
def escribir_csv(ruta, filas):
    if not filas:
        return
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"  escrito {ruta}  ({len(filas)} filas)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--microdatos", required=True,
                    help="carpeta con los CSV de microdato de la EDUC 2023")
    ap.add_argument("--municipio", default="76109")
    ap.add_argument("--salida", default="data")
    args = ap.parse_args()

    print(f"ETL Educación Formal (EDUC) 2023 · versión {VERSION}")
    print(f"Municipio {args.municipio}")

    print("\n[1/4] Matrícula por grupo étnico")
    etnica, sedes_etnicas = matricula_etnica(args.microdatos, args.municipio)
    narp = sum(r["total"] for r in etnica if r["grupo"] == "NARP")
    print(f"  matrícula NARP: {narp:,}".replace(",", ".")
          + f"  ({len(sedes_etnicas)} sedes con reporte étnico)")

    print("\n[2/4] Matrícula total y tipo de prestación")
    por_nivel, por_tipo = matricula_total(args.microdatos, args.municipio)
    print(f"  matrícula total: {sum(por_nivel.values()):,}".replace(",", ".")
          + f"  {dict(por_tipo)}")

    print("\n[3/4] Eficiencia interna al cierre de 2022")
    eficiencia, global_ef = eficiencia_interna(args.microdatos, args.municipio)
    for r in eficiencia:
        print(f"  {r['nivel_educativo'][:20]:22s} deserción={r['tasa_desercion_pct']:5.1f} %"
              f"  reprobación={r['tasa_reprobacion_pct']:5.1f} %")

    print("\n[4/4] Dotación TIC de las sedes (municipio frente a total nacional)")
    try:
        tic, n_mun, n_nal = dotacion_tic(args.microdatos, args.municipio)
    except (KeyError, SystemExit) as e:
        # El cuadro de dotación cambia de estructura entre ediciones. Su ausencia
        # no invalida los tres indicadores anteriores, así que se registra el
        # motivo y el proceso continúa en lugar de perder todo el cálculo.
        print(f"  aviso: no se pudo calcular la dotación TIC ({e}); se omite "
              f"este bloque y los demás resultados se escriben igual.")
        tic, n_mun, n_nal = [], 0, 0
    for r in tic[:3]:
        print(f"  {r['bien_o_servicio']:20s} {r['pct_municipio']:5.1f} %"
              f"  nacional {r['pct_nacional']:5.1f} %  brecha {r['brecha_pp']:+.1f} p.p.")

    docentes = None
    if all(disponible(args.microdatos, k) for k in
           ("personal", "vinculacion", "nivel_docente", "poblacion")):
        print("\n[5/5] Planta docente y población escolar atendida")
        tabla_personal, tabla_cual, docentes = planta_docente(args.microdatos, args.municipio)
        print(f"  docentes de aula: {docentes['docentes_aula']:,}".replace(",", ".")
              + f"  ({docentes['pct_mujeres_aula']} % mujeres)")
        print(f"  con posgrado: {docentes['pct_posgrado']} %"
              f"  (nacional {docentes['pct_posgrado_nal']} %)")
        print(f"  normalistas superiores: {docentes['pct_normalista']} %"
              f"  (nacional {docentes['pct_normalista_nal']} %)")
        print(f"  sedes con internado: {docentes['pct_sedes_internado']} %"
              f"  (nacional {docentes['pct_sedes_internado_nal']} %)")
        escribir_csv(os.path.join(args.salida, "educ_personal_sede.csv"), tabla_personal)
        escribir_csv(os.path.join(args.salida, "educ_cualificacion_docente.csv"), tabla_cual)
    else:
        print("\n[5/5] Planta docente: archivos no disponibles, bloque omitido")

    titulares = indicadores_titulares(etnica, sedes_etnicas, por_nivel, por_tipo,
                                      eficiencia, global_ef, tic, n_mun, docentes)

    print("\nEscribiendo salidas")
    escribir_csv(os.path.join(args.salida, "educ_matricula_etnica.csv"), etnica)
    escribir_csv(os.path.join(args.salida, "educ_eficiencia_interna.csv"), eficiencia)
    escribir_csv(os.path.join(args.salida, "educ_tic_sedes.csv"), tic)
    escribir_csv(os.path.join(args.salida, "educacion_indicadores_educ.csv"), titulares)

    manifiesto = {
        "script": os.path.basename(__file__), "version": VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": FUENTE, "municipio": args.municipio,
        "archivos": list(ARCHIVOS.values()),
        "sedes_del_municipio": n_mun, "sedes_nacional": n_nal,
        "sedes_con_reporte_etnico": len(sedes_etnicas),
        "planta_docente": docentes,
        "advertencias": [
            "La unidad de observación es la sede educativa, no la persona: estas cifras "
            "no son comparables sin mediación con las del CNPV 2018.",
            "El módulo VI (poblaciones especiales) solo lo diligencian las sedes que "
            "declaran tener alumnos de grupos étnicos; la matrícula NARP debe leerse "
            "como un piso y no como un conteo completo.",
            "Publicar matrícula NARP por sede en un municipio con presencia de actores "
            "armados plantea un riesgo de reidentificación institucional: agregar al "
            "menos por comuna o corregimiento antes de difundir.",
        ],
    }
    os.makedirs(args.salida, exist_ok=True)
    ruta = os.path.join(args.salida, "educ_manifiesto.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"  escrito {ruta}")
    print("\nListo. Ahora ejecuta:  python seed_education.py --datos", args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
