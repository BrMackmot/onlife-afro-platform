#!/usr/bin/env python3
# =============================================================================
# etl_educacion_geih.py — Serie 2020-2024 de la capa de educación de OnLife Afro
#                          desde los microdatos anonimizados de la GEIH (DANE)
# -----------------------------------------------------------------------------
# QUÉ HACE Y POR QUÉ EXISTE
#
# El CNPV 2018 da una fotografía municipal (etl_educacion_cnpv.py) y la EDUC 2023
# da la oferta escolar por sede (etl_educacion_educ.py). Ninguno de los dos da
# una SERIE. La GEIH sí: encuesta continua, con módulo de autorreconocimiento
# étnico-racial y factores de expansión, disponible mes a mes.
#
# Este ETL recorre los archivos mensuales del módulo «Características generales,
# seguridad social en salud y educación» de los años pedidos, acumula en memoria
# solo agregados —nunca el microdato completo— y escribe:
#
#   · educacion_geih_serie_anual.csv     serie larga anio × dominio × indicador
#   · educacion_geih_nivel.csv           distribución por nivel educativo
#   · educacion_geih_asistencia.csv      asistencia por grupo de edad y sexo
#   · educacion_geih_muestra.csv         tamaño muestral por año y dominio
#   · educacion_indicadores_geih.csv     titulares para «Comunidad vs DANE»
#   · geih_manifiesto.json               procedencia, filtros y advertencias
#
# El nombre educacion_indicadores_geih.csv no es casual: seed_education.py busca
# educacion_indicadores*.csv, de modo que esta salida entra en la plataforma sin
# tocar el sembrador.
#
# ADVERTENCIA DE REPRESENTATIVIDAD — LÉASE ANTES DE USAR
#
# La GEIH NO es representativa a nivel municipal salvo en las 23 ciudades y áreas
# metropolitanas del diseño muestral. Buenaventura no está entre ellas. Por eso
# este script no acepta --municipio: sus dominios son el departamento y el total
# nacional. La cifra municipal de Buenaventura sale del censo, no de la encuesta.
# Publicar una estimación GEIH como si fuera municipal sería exactamente el tipo
# de dato sin universo declarado que esta plataforma denuncia.
#
# ESTRUCTURA DE CARPETAS QUE ESPERA
#
# Ninguna. El DANE cambia la organización de la entrega cada pocos años y este
# script recorre el árbol completo, así que sirven todas las que hay en la
# práctica:
#
#   geih/GEIH 2020/1. Enero/...                      (mes con número y punto)
#   geih/geih 2021/Abril.csv/Abril.csv/...           (carpeta duplicada)
#   geih/geih 2022/GEIH_Abril_2022_Marco_2018_Act/GEIH_Abril_2022_Marco_2018/CSV/
#   geih/geih 2023/Abril/Abril/CSV/CVS/              (con la errata «CVS»)
#   geih/geih 2024/Abril 2024/CSV/CSV/
#
# El año se toma del primer segmento de la ruta que lo declare —de «geih 2022» y
# no de «Marco_2018», que es el marco muestral y no el año de recolección— y el
# mes, del nombre de la carpeta o del archivo.
#
# EL SPLIT ÁREA / CABECERA / RESTO
#
# Hasta 2021 la entrega parte el módulo de personas en tres archivos: «Área -
# Características generales», «Cabecera - …» y «Resto - …». Los tres NO se suman:
# Área es el subconjunto de las 23 ciudades y áreas metropolitanas, contenido en
# Cabecera. Sumar los tres duplicaría a toda la población urbana de esas ciudades
# e inflaría cualquier estimación nacional. Por defecto el script usa Cabecera +
# Resto —que sí particionan la muestra— y descarta Área, dejando constancia en el
# manifiesto de cuántos archivos de cada clase encontró y cuáles usó. Desde 2022
# el módulo viene en un archivo único y la regla no aplica.
#
# Uso:
#   python etl_educacion_geih.py --raiz microdatos/GEIH --anios 2020 2021 2022 2023 2024 \
#       --dpto 76 --salida data/
#   python etl_educacion_geih.py --raiz microdatos/GEIH --anios 2020 --meses 1 4 7 10 \
#       --dpto 76 --salida data/     # submuestra trimestral declarada
#   python etl_educacion_geih.py --raiz microdatos/GEIH --anios 2023 --dpto 76 \
#       --salida data/ --max-filas 50000        # prueba rápida
#
# Los valores comunitarios NO se calculan aquí: viven en valores_comunitarios.csv,
# que edita la organización y no el código (principio OCAP® de control).
# =============================================================================

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import io
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

VERSION = "1.0"
FUENTE_BASE = ("DANE — Gran Encuesta Integrada de Hogares (GEIH), microdatos "
               "anonimizados, módulo de características generales, seguridad "
               "social en salud y educación")

# Umbral de supresión de celdas pequeñas, idéntico al del ETL censal: se aplica
# en el código y no como revisión posterior.
MIN_OBSERVACIONES = 50
SUPRIMIDA = "SUPRIMIDA"

# --- Columnas ----------------------------------------------------------------
# La GEIH cambia mayúsculas y sufijos entre entregas; se resuelven por nombre
# normalizado y se aceptan alias. Las obligatorias detienen el proceso.
ALIAS = {
    "etnia":      ["P6080"],
    "edad":       ["P6040"],
    "sexo":       ["P6020", "P3271"],
    # El rediseño de la GEIH renombró variables: las entregas con marco 2018
    # usan códigos distintos para el nivel educativo y el grado aprobado. Se
    # aceptan ambos y el manifiesto registra cuál se encontró en cada archivo.
    "nivel":      ["P6210", "P3042"],
    "grado":      ["P6210S1", "P3042S1"],
    "asiste":     ["P6170", "P3041"],
    "lee":        ["P6160", "P3040"],
    "esc":        ["ESC"],
    "dpto":       ["DPTO", "DPTOS"],
    "clase":      ["CLASE", "AREA_URBANO_RURAL"],
    "area":       ["AREA"],
    "factor":     ["FEX_C18", "FEX_C_2011", "FEX_C", "FEX_DPTO_2011"],
    "mes":        ["MES"],
}
# Solo tres columnas son imprescindibles: sin edad, territorio o ponderador no
# hay estimación posible. Las demás se comprueban archivo por archivo y su
# ausencia desactiva el indicador correspondiente en lugar de detener el proceso:
# algunas entregas por dominio de ciudad no incluyen la pregunta de
# autorreconocimiento étnico, y conviene que eso se vea en la salida y en el
# manifiesto, no que el archivo desaparezca sin explicación.
OBLIGATORIAS = ["edad", "dpto", "factor"]
OPCIONALES_CLAVE = ["etnia", "nivel", "asiste", "lee", "grado", "esc"]

# P6080 — autorreconocimiento étnico. La categoría analítica NARP agrupa
# raizales, palenqueros y población negra/mulata/afrodescendiente, igual que
# los cuadros del DANE y que el ETL del censo.
GRUPO_ETNICO = {
    "1": "Indígena",
    "2": "Gitano(a) o Rrom",
    "3": "Raizal del Archipiélago",
    "4": "Palenquero(a) de San Basilio",
    "5": "Negro(a), mulato(a), afrodescendiente",
    "6": "Ningún grupo étnico",
    "9": "No informa",
}
CODIGOS_NARP = {"3", "4", "5"}

# El rediseño de la GEIH no renombró la pregunta de nivel educativo: la
# reemplazó. P6210 (marco 2005) tiene seis categorías; P3042 (marco 2018) tiene
# trece, y los códigos que comparten número no significan lo mismo —el 5 es
# «Media» en una y «Media académica» en la otra, y del 7 al 13 no existen en la
# primera—. Leer P3042 con la tabla de P6210 trunca la secundaria, aplasta la
# media y descarta a toda la población con estudios superiores, que es lo que
# produjo una escolaridad NARP de 3,44 años y una caída de 5,51 años en la
# serie. Cada marco tiene por eso su propia tabla, y el marco se decide por la
# columna encontrada en cada archivo.
NIVEL_2005 = {
    "1": "Ninguno",
    "2": "Preescolar",
    "3": "Básica primaria",
    "4": "Básica secundaria",
    "5": "Media",
    "6": "Superior o universitaria",
    "9": "No sabe, no informa",
}
NIVEL_2018 = {
    "1": "Ninguno",
    "2": "Preescolar",
    "3": "Básica primaria",
    "4": "Básica secundaria",
    "5": "Media académica",
    "6": "Media técnica",
    "7": "Normalista",
    "8": "Técnica profesional",
    "9": "Tecnológica",
    "10": "Universitaria",
    "11": "Especialización",
    "12": "Maestría",
    "13": "Doctorado",
    "99": "No sabe, no informa",
}
ORDEN_NIVEL = ["Ninguno", "Preescolar", "Básica primaria", "Básica secundaria",
               "Media", "Superior o universitaria", "No sabe, no informa"]

# Las trece categorías de 2018 se pliegan sobre las seis de 2005 para que la
# distribución por nivel sea comparable a lo largo de los cinco años. Sin este
# pliegue la figura cambiaría de categorías en 2022 y la ruptura del instrumento
# parecería un cambio en la población.
GRUPO_COMPARABLE = {
    "Media académica": "Media",
    "Media técnica": "Media",
    "Normalista": "Superior o universitaria",
    "Técnica profesional": "Superior o universitaria",
    "Tecnológica": "Superior o universitaria",
    "Universitaria": "Superior o universitaria",
    "Especialización": "Superior o universitaria",
    "Maestría": "Superior o universitaria",
    "Doctorado": "Superior o universitaria",
}

# Años acumulados al COMPLETAR cada nivel. Se usan como piso del nivel para
# convertir «último grado aprobado» en años de escolaridad.
PISO_2005 = {"1": 0, "2": 0, "3": 0, "4": 5, "5": 9, "6": 11}
PISO_2018 = {"1": 0, "2": 0, "3": 0, "4": 5, "5": 9, "6": 9,
             "7": 11, "8": 11, "9": 11, "10": 11,
             "11": 16, "12": 17, "13": 19}
# La pregunta del marco 2018 es una sola —«el último grado o semestre
# aprobado»— y a partir de la normalista la respuesta viene en semestres. Diez
# semestres de universitaria son cinco años, no diez: sumarlos como años sitúa a
# esa población en 21 años de escolaridad y desplaza la media nacional en algo
# más de un año. En el marco 2005 la pregunta pedía el último año aprobado y no
# el semestre, y por eso la conversión no se aplica allí: la comprobación es que
# 2020 derivado reproduce la columna ESC del DANE.
NIVELES_EN_SEMESTRES_2018 = {"7", "8", "9", "10", "11", "12", "13"}
# Grado máximo plausible dentro de cada nivel, en convención relativa.
TOPE_RELATIVO = {"3": 5, "4": 4, "5": 2, "6": 8}
# Grado máximo plausible en convención absoluta. Fuera de ese rango el valor no
# es un grado: es un código de «no informa» que llegó como número. Basta uno
# para invertir la decisión de convención y desplazar la serie entera.
TOPE_ABSOLUTO = {"3": 5, "4": 9, "5": 11, "6": 25}

DEPARTAMENTOS = {
    "05": "Antioquia", "08": "Atlántico", "11": "Bogotá D.C.", "13": "Bolívar",
    "15": "Boyacá", "17": "Caldas", "18": "Caquetá", "19": "Cauca",
    "20": "Cesar", "23": "Córdoba", "25": "Cundinamarca", "27": "Chocó",
    "41": "Huila", "44": "La Guajira", "47": "Magdalena", "50": "Meta",
    "52": "Nariño", "54": "Norte de Santander", "63": "Quindío",
    "66": "Risaralda", "68": "Santander", "70": "Sucre", "73": "Tolima",
    "76": "Valle del Cauca", "81": "Arauca", "85": "Casanare", "86": "Putumayo",
    "88": "Archipiélago de San Andrés", "91": "Amazonas", "94": "Guainía",
    "95": "Guaviare", "97": "Vaupés", "99": "Vichada",
}

GRUPOS_EDAD = [(5, 9, "5-9"), (10, 14, "10-14"), (15, 19, "15-19"),
               (20, 24, "20-24"), (25, 200, "25 y más")]
ORDEN_EDAD = ["5-9", "10-14", "15-19", "20-24", "25 y más"]


# =============================================================================
# Utilidades
# =============================================================================
def norm(s: str) -> str:
    """Normaliza para comparar nombres de archivo y de columna sin tildes."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def slug(texto):
    """Convierte «Valle del Cauca» en «valle_del_cauca» para la columna territory."""
    base = norm(texto).lower().replace(".", "")
    return "_".join(base.split())


def grupo_edad(edad):
    for lo, hi, etiqueta in GRUPOS_EDAD:
        if lo <= edad <= hi:
            return etiqueta
    return None


def a_float(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def a_int(v):
    f = a_float(v)
    return int(f) if f is not None else None


def suprime(valor, n):
    return SUPRIMIDA if n < MIN_OBSERVACIONES else valor


def sha256(ruta, bloque=1 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


# =============================================================================
# Descubrimiento de archivos
# =============================================================================
CLASES_DOMINIO = ("AREA", "CABECERA", "RESTO")

MESES_NOMBRE = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


def inferir_mes(ruta):
    """Mes de recolección, leído del nombre de la carpeta o del archivo.

    Cubre las formas que usan las entregas: «1. Enero», «2.Febrero», «Abril»,
    «Abril 2024», «GEIH_Abril_2022_Marco_2018». Se busca el nombre del mes y no
    un número, porque «2018» y «12» aparecen en las rutas por otras razones.
    """
    t = norm(ruta.replace("\\", "/"))
    for nombre, num in MESES_NOMBRE.items():
        if nombre in t:
            return num
    return None


def clase_dominio(ruta):
    """Área, Cabecera, Resto o Único, según el prefijo del nombre de archivo."""
    base = norm(nombre_visible(ruta))
    for c in CLASES_DOMINIO:
        if base.startswith(c):
            return c
    return "UNICO"


def descubrir(raiz, anios, patron, meses=None, clases=None, anio_defecto=None):
    """Encuentra los CSV mensuales del módulo pedido bajo la raíz dada.

    No se asume una estructura de carpetas concreta: el DANE distribuye la GEIH
    con nombres distintos según el año y la entrega. Se recorre el árbol, se
    filtra por nombre normalizado y se infiere el año de la ruta.
    """
    patron_norm = norm(patron)
    encontrados, descartados = [], defaultdict(list)
    vistos_csv = []
    for ruta in candidatos_csv(raiz):
        # El título del módulo puede estar en el nombre del archivo o en el de
        # su carpeta: al descomprimir los ZIP del catálogo, el archivo interior a
        # veces se llama simplemente «datos.CSV».
        etiqueta = norm(carpeta_visible(ruta) + " " + nombre_visible(ruta))
        vistos_csv.append(ruta)
        if patron_norm not in etiqueta:
            continue
        anio = inferir_anio(ruta, raiz) or anio_defecto
        if anio is None:
            # No se adivina: un archivo sin año en la ruta se reporta, para que
            # nadie descubra al final que una carpeta entera quedó fuera.
            descartados["sin año identificable en la ruta"].append(ruta)
            continue
        if anios and anio not in anios:
            continue
        mes = inferir_mes(os.path.relpath(ruta, raiz))
        if meses and (mes is None or mes not in meses):
            descartados["mes fuera de la submuestra"].append(ruta)
            continue
        clase = clase_dominio(ruta)
        if clases and clase not in clases:
            descartados[f"dominio {clase} excluido para no duplicar"].append(ruta)
            continue
        encontrados.append((anio, ruta))
    # deduplica rutas que aparecen por la doble búsqueda de extensión
    vistos, salida = set(), []
    for anio, ruta in sorted(set(encontrados)):
        clave = os.path.abspath(ruta)
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append((anio, ruta))
    return salida, dict(descartados), vistos_csv


def candidatos_csv(raiz):
    """Todos los CSV bajo la raíz, estén sueltos o dentro de un ZIP."""
    rutas = []
    for patron in ("*.CSV", "*.csv"):
        rutas += glob.glob(os.path.join(raiz, "**", patron), recursive=True)
    for patron in ("*.ZIP", "*.zip"):
        for archivo_zip in glob.glob(os.path.join(raiz, "**", patron), recursive=True):
            try:
                with zipfile.ZipFile(ruta_larga(archivo_zip)) as z:
                    for interno in z.namelist():
                        if interno.lower().endswith(".csv"):
                            rutas.append(archivo_zip + SEP_ZIP + interno)
            except (zipfile.BadZipFile, OSError) as e:
                print(f"  aviso: no se pudo abrir {os.path.basename(archivo_zip)}: {e}")
    vistos, salida = set(), []
    for r in rutas:
        clave = r if SEP_ZIP in r else os.path.abspath(r)
        if clave not in vistos:
            vistos.add(clave)
            salida.append(r)
    return salida


def inferir_anio(ruta, raiz=None):
    """Año de recolección, leído de izquierda a derecha desde la raíz.

    Se lee el PRIMER año que aparece en la ruta relativa, no el último: las
    entregas de 2022 en adelante llevan «Marco_2018» en el nombre de la carpeta
    —el marco muestral, no el año— y tomar el último daría 2018 para todos los
    meses de 2022. Además se ignora cualquier año precedido de «marco».
    """
    p = os.path.relpath(ruta, raiz) if raiz else ruta
    p = p.replace("\\", "/")
    for m in re.finditer(r"(20[12]\d)", p):
        anterior = norm(p[max(0, m.start() - 8):m.start()])
        if "MARCO" in anterior:
            continue
        return int(m.group(1))
    return None


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


# Separador interno para referirse a un archivo dentro de un ZIP:
# "…/GEIH_Abril_2022.zip!/CSV/Características generales….CSV"
SEP_ZIP = "!/"


def partes_zip(ruta):
    """Devuelve (contenedor, miembro). El miembro es None si no hay ZIP."""
    if SEP_ZIP in ruta:
        contenedor, miembro = ruta.split(SEP_ZIP, 1)
        return contenedor, miembro
    return ruta, None


def nombre_visible(ruta):
    contenedor, miembro = partes_zip(ruta)
    return os.path.basename(miembro or contenedor)


def carpeta_visible(ruta):
    contenedor, miembro = partes_zip(ruta)
    if miembro:
        interna = os.path.dirname(miembro.replace("\\", "/"))
        return os.path.basename(interna) if interna else os.path.basename(contenedor)
    return os.path.basename(os.path.dirname(contenedor))


def elegir_delimitador(primera):
    """Delimitador del encabezado, entre los cuatro que usan las entregas.

    Una entrega de 2021 llega separada por espacios. El espacio se prueba en
    último lugar porque también aparece dentro de los campos de texto: si hay
    un separador propiamente dicho, ese manda. Sin esta regla el encabezado no
    se parte, ninguna columna se reconoce y el archivo se descarta por «faltan
    edad, dpto, factor», que describe el síntoma y no la causa.
    """
    for c in (";", ",", "\t"):
        if primera.count(c):
            return c
    return " " if primera.count(" ") else ";"


def abrir_lector(ruta):
    """Abre el CSV resolviendo delimitador y codificación, que varían por año.

    Acepta tanto un archivo suelto como uno contenido en un ZIP. Las entregas
    del catálogo llegan comprimidas y el explorador de Windows las muestra como
    si fueran carpetas, de modo que es fácil creer que ya están descomprimidas
    cuando no lo están. Leerlas directamente evita duplicar en disco decenas de
    gigabytes solo para poder contarlos.
    """
    contenedor, miembro = partes_zip(ruta)
    if miembro:
        with zipfile.ZipFile(ruta_larga(contenedor)) as z:
            crudo = z.read(miembro)
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                texto = crudo.decode(encoding)
            except UnicodeDecodeError:
                continue
            primera = texto.split("\n", 1)[0]
            delim = elegir_delimitador(primera)
            f = io.StringIO(texto)
            return (csv.DictReader(f, delimiter=delim, skipinitialspace=True),
                    f, encoding, delim)
        raise SystemExit(f"✗ No se pudo leer {ruta} en utf-8 ni en latin-1.")
    # Se decide la codificación sobre el archivo completo y no sobre su primera
    # línea. Las cabeceras de la GEIH son ASCII puro, de modo que sniffar solo el
    # encabezado daba «utf-8» por bueno y el proceso reventaba miles de filas más
    # abajo, al llegar a la primera Ñ codificada en latin-1. Un mes de la encuesta
    # ocupa unos pocos megabytes, así que leerlo entero para decidir es barato y
    # elimina la clase de error por completo.
    with open(ruta_larga(ruta), "rb") as fb:
        crudo = fb.read()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            texto = crudo.decode(encoding)
        except UnicodeDecodeError:
            continue
        primera = texto.split("\n", 1)[0]
        delim = elegir_delimitador(primera)
        f = io.StringIO(texto)
        return (csv.DictReader(f, delimiter=delim, skipinitialspace=True),
                f, encoding, delim)
    raise SystemExit(f"✗ No se pudo leer {ruta} en utf-8 ni en latin-1.")


def marco_de(mapa):
    """«2018» si la entrega trae P3042, «2005» si trae P6210.

    El marco es propiedad del archivo y no del año: 2021 llegó en ambos
    formatos. Decidirlo por la columna encontrada, y no por la fecha, evita
    mantener una tabla de qué año usa qué y sobrevive a entregas reindexadas.
    """
    return "2018" if norm(mapa.get("nivel", "")) == "P3042" else "2005"


def mapear_columnas(fieldnames):
    """Devuelve {concepto: nombre real de la columna} resolviendo alias."""
    disponibles = {norm(c): c for c in (fieldnames or [])}
    mapa = {}
    for concepto, opciones in ALIAS.items():
        for alias in opciones:
            if norm(alias) in disponibles:
                mapa[concepto] = disponibles[norm(alias)]
                break
    return mapa


# =============================================================================
# Convención del grado aprobado
# =============================================================================
class DetectorGrado:
    """Decide si P6210S1 viene en convención absoluta o relativa.

    En unas entregas de la GEIH el «último grado aprobado» de básica secundaria
    se codifica 6, 7, 8, 9 —convención absoluta, el grado del sistema escolar— y
    en otras 1, 2, 3, 4 —convención relativa al nivel—. Convertir años de
    escolaridad con la convención equivocada desplaza toda la serie, de modo que
    la convención se detecta con la distribución observada y se deja registrada
    en el manifiesto en lugar de suponerse.
    """

    def __init__(self, forzada="auto"):
        self.forzada = forzada
        self.max_por_nivel = defaultdict(int)
        self.descartados = defaultdict(int)
        self.decidida = None

    def observar(self, marco, nivel, grado):
        # Solo se observa el marco 2005: P3042S1 es siempre relativo al nivel y
        # no necesita detección. Y solo dentro del rango plausible, para que un
        # código de «no informa» no decida la convención de toda la serie.
        if marco != "2005" or grado is None or nivel not in TOPE_ABSOLUTO:
            return
        if not 0 <= grado <= TOPE_ABSOLUTO[nivel]:
            self.descartados[nivel] += 1
            return
        self.max_por_nivel[nivel] = max(self.max_por_nivel[nivel], grado)

    def decidir(self):
        if self.forzada in ("absoluta", "relativa"):
            self.decidida = self.forzada
            return self.decidida
        # Si en secundaria o media se observan grados por encima del tope
        # relativo, la codificación es absoluta.
        absoluta = (self.max_por_nivel.get("4", 0) > TOPE_RELATIVO["4"]
                    or self.max_por_nivel.get("5", 0) > TOPE_RELATIVO["5"])
        self.decidida = "absoluta" if absoluta else "relativa"
        return self.decidida

    def anios(self, marco, nivel, grado):
        """Años de escolaridad acumulados. Devuelve None si no es calculable."""
        tabla = PISO_2018 if marco == "2018" else PISO_2005
        if nivel in ("1", "2"):
            return 0
        if nivel not in tabla or grado is None:
            return None
        if self.decidida is None:
            self.decidir()
        piso = tabla[nivel]
        # P3042S1 es siempre relativo al nivel. P6210S1 varía entre entregas y
        # por eso conserva el detector: la convención es propiedad del marco y
        # no de la serie, y aplicar una sola decisión a los dos desplazaría la
        # mitad de los años sin que nada en la salida lo delatara.
        if marco == "2005" and self.decidida == "absoluta" and nivel in ("3", "4", "5"):
            valor = grado
        elif marco == "2018" and nivel in NIVELES_EN_SEMESTRES_2018:
            # División entera: un semestre suelto no completa un año.
            valor = piso + grado // 2
        else:
            valor = piso + grado
        return max(0, min(valor, 25))


# =============================================================================
# Acumulador
# =============================================================================
class Acumulador:
    """Suma agregados por año y dominio sin retener el microdato.

    Cada celda guarda el conteo muestral (n) y la suma de factores de expansión
    (w). El n decide la supresión; el w, la estimación.
    """

    def __init__(self):
        self.celdas = defaultdict(lambda: [0, 0.0])          # clave -> [n, w]
        self.escolaridad = defaultdict(lambda: [0, 0.0, 0.0])  # -> [n, w, w*años]
        self.distribucion = defaultdict(lambda: [0, 0.0])       # (anio,dom,años) -> [n, w]

    def sumar(self, clave, peso):
        c = self.celdas[clave]
        c[0] += 1
        c[1] += peso

    def sumar_escolaridad(self, clave, peso, anios):
        c = self.escolaridad[clave]
        c[0] += 1
        c[1] += peso
        c[2] += peso * anios

    def n(self, clave):
        return self.celdas[clave][0] if clave in self.celdas else 0

    def w(self, clave):
        return self.celdas[clave][1] if clave in self.celdas else 0.0

    def proporcion(self, num, den, escala=100.0, decimales=1):
        n_den, w_den = self.celdas.get(den, [0, 0.0])
        if not w_den:
            return "", n_den
        valor = round(escala * self.w(num) / w_den, decimales)
        return suprime(valor, n_den), n_den

    def sumar_distribucion(self, clave, peso):
        c = self.distribucion[clave]
        c[0] += 1
        c[1] += peso

    def media_escolaridad(self, clave):
        n, w, wa = self.escolaridad.get(clave, [0, 0.0, 0.0])
        if not w:
            return "", n
        return suprime(round(wa / w, 2), n), n


def percentil_ponderado(pares, q):
    """Percentil sobre una distribución ponderada. pares = [(valor, peso), ...]."""
    if not pares:
        return None
    ordenados = sorted(pares)
    total = sum(w for _, w in ordenados)
    if total <= 0:
        return None
    objetivo, acumulado = q * total, 0.0
    for valor, w in ordenados:
        acumulado += w
        if acumulado >= objetivo:
            return valor
    return ordenados[-1][0]


def estadisticos(acc, anio, dominio, decimales=2):
    """Media, desviación, mediana, cuartiles y coeficiente de variación.

    Todo ponderado por el factor de expansión. La desviación estándar es la de
    la POBLACIÓN estimada, no el error estándar de la media: describe cuánto
    varían los años de escolaridad entre personas, no la precisión con que se
    estima el promedio. Esa distinción importa —el error estándar exigiría las
    variables de diseño muestral, que el microdato público no trae— y por eso el
    tamaño muestral viaja junto a cada cifra.
    """
    pares = [(anios, w) for (a, d, anios), (n, w) in acc.distribucion.items()
             if a == anio and d == dominio]
    n_muestral = sum(n for (a, d, _), (n, w) in acc.distribucion.items()
                     if a == anio and d == dominio)
    if not pares or n_muestral < MIN_OBSERVACIONES:
        return {"media": SUPRIMIDA if pares else "", "desviacion_estandar": "",
                "mediana": "", "p25": "", "p75": "", "coef_variacion_pct": "",
                "n_muestral": n_muestral, "poblacion_expandida": round(sum(w for _, w in pares))}
    total_w = sum(w for _, w in pares)
    media = sum(v * w for v, w in pares) / total_w
    var = sum(w * (v - media) ** 2 for v, w in pares) / total_w
    sd = var ** 0.5
    return {
        "media": round(media, decimales),
        "desviacion_estandar": round(sd, decimales),
        "mediana": percentil_ponderado(pares, 0.50),
        "p25": percentil_ponderado(pares, 0.25),
        "p75": percentil_ponderado(pares, 0.75),
        "coef_variacion_pct": round(100 * sd / media, 1) if media else "",
        "n_muestral": n_muestral,
        "poblacion_expandida": round(total_w),
    }


def tabla_distribucion(acc, anios, dominios):
    """Histograma ponderado de los años de escolaridad: insumo de la Figura."""
    filas = []
    for (anio, d, valor), (n, w) in sorted(acc.distribucion.items()):
        if anio not in anios or d not in dominios:
            continue
        filas.append({"anio": anio, "dominio": d, "anios_escolaridad": valor,
                      "n_muestral": n, "poblacion_expandida": round(w)})
    # participación dentro de cada (anio, dominio)
    totales = defaultdict(float)
    for f in filas:
        totales[(f["anio"], f["dominio"])] += f["poblacion_expandida"]
    for f in filas:
        base = totales[(f["anio"], f["dominio"])]
        f["participacion_pct"] = round(100 * f["poblacion_expandida"] / base, 2) if base else ""
    return filas


def dominios_de(fila_dpto, dpto_objetivo, es_narp, con_etnia=True):
    """Dominios a los que pertenece cada persona.

    Si el archivo no trae la pregunta de autorreconocimiento étnico, los dominios
    NARP y no NARP no se producen: una estimación étnica sin variable étnica no
    es una estimación con más ruido, es una cifra inventada.
    """
    etiqueta_dpto = DEPARTAMENTOS.get(dpto_objetivo, f"Departamento {dpto_objetivo}")
    doms = ["Total nacional"]
    if con_etnia:
        doms.append("NARP — nacional" if es_narp else "No NARP — nacional")
    if fila_dpto == dpto_objetivo:
        doms.append(f"Total {etiqueta_dpto}")
        if con_etnia:
            doms.append(f"{'NARP' if es_narp else 'No NARP'} — {etiqueta_dpto}")
    return doms


# =============================================================================
# Procesamiento
# =============================================================================
def procesar(archivos, dpto, detector, max_filas=None, preferencia_esc="esc"):
    acc = Acumulador()
    nivel_acc = defaultdict(lambda: [0, 0.0])
    asistencia_acc = defaultdict(lambda: [0, 0.0])
    registro = []
    factores_usados = set()
    columnas_faltantes = defaultdict(list)
    sin_columna = defaultdict(set)     # concepto -> archivos que no lo traen
    usa_esc = set()

    for anio, ruta in archivos:
        lector, fh, encoding, delim = abrir_lector(ruta)
        mapa = mapear_columnas(lector.fieldnames)
        marco = marco_de(mapa)
        faltan = [c for c in OBLIGATORIAS if c not in mapa]
        if faltan:
            fh.close()
            columnas_faltantes[ruta] = faltan
            print(f"  ✗ {nombre_visible(ruta)}: faltan {', '.join(faltan)}; se omite.")
            continue
        factores_usados.add(mapa["factor"])
        for concepto in OPCIONALES_CLAVE:
            if concepto not in mapa:
                sin_columna[concepto].add(nombre_visible(ruta))
        if "esc" in mapa:
            usa_esc.add(nombre_visible(ruta))
        con_etnia = "etnia" in mapa
        leidas = 0
        for fila in lector:
            leidas += 1
            if max_filas and leidas > max_filas:
                break
            peso = a_float(fila.get(mapa["factor"]))
            edad = a_int(fila.get(mapa["edad"]))
            if peso is None or peso <= 0 or edad is None:
                continue
            ge = grupo_edad(edad)
            if ge is None:
                continue
            etnia = (fila.get(mapa["etnia"]) or "").strip() if con_etnia else ""
            es_narp = etnia in CODIGOS_NARP
            fdpto = (fila.get(mapa["dpto"]) or "").strip().zfill(2)
            doms = dominios_de(fdpto, dpto, es_narp, con_etnia)

            nivel = (fila.get(mapa["nivel"]) or "").strip() if "nivel" in mapa else ""
            grado = a_int(fila.get(mapa.get("grado", ""), "")) if "grado" in mapa else None
            detector.observar(marco, nivel, grado)
            asiste = (fila.get(mapa["asiste"]) or "").strip() if "asiste" in mapa else ""
            lee = (fila.get(mapa.get("lee", ""), "") or "").strip() if "lee" in mapa else ""
            sexo = (fila.get(mapa.get("sexo", ""), "") or "").strip() if "sexo" in mapa else ""

            for d in doms:
                # --- asistencia escolar 5-24 -------------------------------
                if ge in ("5-9", "10-14", "15-19", "20-24") and asiste in ("1", "2"):
                    acc.sumar((anio, d, "asistencia_base"), peso)
                    asistencia_acc[(anio, d, ge, sexo)][0] += 1
                    asistencia_acc[(anio, d, ge, sexo)][1] += peso
                    if asiste == "1":
                        acc.sumar((anio, d, "asistencia_si"), peso)
                        asistencia_acc[(anio, d, ge, sexo, "si")][0] += 1
                        asistencia_acc[(anio, d, ge, sexo, "si")][1] += peso
                # --- alfabetismo 15 y más ----------------------------------
                if edad >= 15 and lee in ("1", "2"):
                    acc.sumar((anio, d, "lee_base"), peso)
                    if lee == "2":
                        acc.sumar((anio, d, "no_lee"), peso)
                # --- nivel educativo 25 y más ------------------------------
                if edad >= 25:
                    acc.sumar((anio, d, "pob_25mas"), peso)
                    # Si el archivo no trae la columna de nivel, no se clasifica:
                    # contar esas filas como «No sabe, no informa» convertiría la
                    # ausencia de una variable en un resultado —una distribución
                    # del 100 % en la categoría de no respuesta— que parecería un
                    # hallazgo y sería un artefacto.
                    if "nivel" in mapa:
                        tabla = NIVEL_2018 if marco == "2018" else NIVEL_2005
                        etiqueta = tabla.get(nivel, "No sabe, no informa")
                        etiqueta = GRUPO_COMPARABLE.get(etiqueta, etiqueta)
                        nivel_acc[(anio, d, etiqueta)][0] += 1
                        nivel_acc[(anio, d, etiqueta)][1] += peso
                        if etiqueta in ("Media", "Superior o universitaria"):
                            acc.sumar((anio, d, "media_o_mas"), peso)
                # --- no respuesta étnica -----------------------------------
                if d in ("Total nacional",) or d.startswith("Total "):
                    acc.sumar((anio, d, "poblacion"), peso)
                    if etnia == "9" or etnia == "":
                        acc.sumar((anio, d, "etnia_sin_dato"), peso)
        fh.close()
        mes_detectado = inferir_mes(ruta)
        contenedor, miembro = partes_zip(ruta)
        registro.append({"anio": anio, "mes": mes_detectado,
                         "clase_dominio": clase_dominio(ruta),
                         "archivo": nombre_visible(ruta),
                         "dentro_de_zip": os.path.basename(contenedor) if miembro else None,
                         "ruta": os.path.abspath(contenedor) + (SEP_ZIP + miembro if miembro else ""),
                         "filas_leidas": leidas,
                         "encoding": encoding, "delimitador": delim,
                         "factor": mapa["factor"]})
        print(f"  · {anio}-{(mes_detectado or 0):02d} [{clase_dominio(ruta)[:4]:4s}] "
              f"{nombre_visible(ruta)[:46]:46s} {leidas:>9,} filas")

    detector.decidir()

    # Segunda pasada solo para escolaridad: la conversión grado→años depende de
    # la convención, que no se conoce con certeza hasta haber visto los datos.
    print(f"\n  convención de grado detectada: {detector.decidida}")
    print("  segunda pasada para años de escolaridad")
    for anio, ruta in archivos:
        if ruta in columnas_faltantes:
            continue
        lector, fh, _, _ = abrir_lector(ruta)
        mapa = mapear_columnas(lector.fieldnames)
        marco = marco_de(mapa)
        # Preferencia por ESC: cuando la entrega ya trae los años de escolaridad
        # calculados por el DANE, usarlos evita imponer una equivalencia propia.
        # Qué produce los años de escolaridad. «esc» prefiere la columna que
        # calcula el DANE donde la entrega la trae; «derivada» usa siempre la
        # equivalencia nivel-grado. La segunda existe para poder comparar ambas
        # sobre los mismos años: si la derivación reproduce el valor oficial en
        # 2020, la serie puede construirse entera con una sola definición en
        # lugar de cambiar de método a mitad de camino.
        if preferencia_esc == "derivada":
            fuente_esc = "derivada" if "grado" in mapa else ("esc" if "esc" in mapa else None)
        else:
            fuente_esc = "esc" if "esc" in mapa else ("derivada" if "grado" in mapa else None)
        if fuente_esc is None:
            fh.close()
            continue
        con_etnia = "etnia" in mapa
        leidas = 0
        for fila in lector:
            leidas += 1
            if max_filas and leidas > max_filas:
                break
            peso = a_float(fila.get(mapa["factor"]))
            edad = a_int(fila.get(mapa["edad"]))
            if peso is None or peso <= 0 or edad is None or edad < 25:
                continue
            if fuente_esc == "esc":
                anios = a_int(fila.get(mapa["esc"]))
                if anios is not None:
                    anios = max(0, min(anios, 25))
            else:
                nivel = (fila.get(mapa["nivel"]) or "").strip() if "nivel" in mapa else ""
                grado = a_int(fila.get(mapa["grado"]))
                anios = detector.anios(marco, nivel, grado)
            if anios is None:
                continue
            etnia = (fila.get(mapa["etnia"]) or "").strip() if con_etnia else ""
            fdpto = (fila.get(mapa["dpto"]) or "").strip().zfill(2)
            for d in dominios_de(fdpto, DPTO_ACTUAL, etnia in CODIGOS_NARP, con_etnia):
                acc.sumar_escolaridad((anio, d), peso, anios)
                acc.sumar_distribucion((anio, d, anios), peso)
        fh.close()

    if sin_columna:
        print("\n  columnas ausentes en algunos archivos:")
        for concepto, archivos_sin in sorted(sin_columna.items()):
            print(f"    {concepto}: {len(archivos_sin)} archivo(s)")
        if "etnia" in sin_columna:
            print("    ⚠ sin la pregunta de autorreconocimiento étnico no se producen "
                  "los dominios NARP y no NARP de esos archivos: solo los totales.")
    if usa_esc:
        print(f"  años de escolaridad tomados de la columna ESC en {len(usa_esc)} archivo(s)")
    return (acc, nivel_acc, asistencia_acc, registro, sorted(factores_usados),
            columnas_faltantes, dict(sin_columna), sorted(usa_esc))


# =============================================================================
# Salidas
# =============================================================================
def serie_anual(acc, anios, dominios):
    filas = []
    for anio in anios:
        for d in dominios:
            asis, n_asis = acc.proporcion((anio, d, "asistencia_si"),
                                          (anio, d, "asistencia_base"))
            analf, n_alf = acc.proporcion((anio, d, "no_lee"), (anio, d, "lee_base"))
            media, n_med = acc.proporcion((anio, d, "media_o_mas"), (anio, d, "pob_25mas"))
            esc, n_esc = acc.media_escolaridad((anio, d))
            est = estadisticos(acc, anio, d)
            if not any([n_asis, n_alf, n_med, n_esc]):
                continue
            filas.append({
                "anio": anio, "dominio": d,
                "escolaridad_promedio_25mas": esc, "n_escolaridad": n_esc,
                "escolaridad_desviacion": est["desviacion_estandar"],
                "escolaridad_mediana": est["mediana"],
                "escolaridad_p25": est["p25"], "escolaridad_p75": est["p75"],
                "escolaridad_coef_variacion_pct": est["coef_variacion_pct"],
                "asistencia_5_24_pct": asis, "n_asistencia": n_asis,
                "analfabetismo_15mas_pct": analf, "n_alfabetismo": n_alf,
                "media_o_superior_25mas_pct": media, "n_nivel": n_med,
                "poblacion_expandida_25mas": round(acc.w((anio, d, "pob_25mas"))),
            })
    return filas


def tabla_nivel(nivel_acc, anios, dominios):
    filas = []
    bases = defaultdict(float)
    for (anio, d, etiqueta), (n, w) in nivel_acc.items():
        bases[(anio, d)] += w
    for (anio, d, etiqueta), (n, w) in sorted(
            nivel_acc.items(), key=lambda kv: (kv[0][0], kv[0][1],
                                               ORDEN_NIVEL.index(kv[0][2]))):
        if anio not in anios or d not in dominios:
            continue
        base = bases[(anio, d)]
        filas.append({
            "anio": anio, "dominio": d, "nivel_educativo": etiqueta,
            "n_muestral": n, "poblacion_expandida": round(w),
            "participacion_pct": suprime(round(100 * w / base, 1) if base else "", n),
        })
    return filas


def tabla_asistencia(asistencia_acc, anios, dominios):
    filas = []
    claves = {k[:4] for k in asistencia_acc if len(k) == 4}
    for (anio, d, ge, sexo) in sorted(claves, key=lambda k: (k[0], k[1],
                                                             ORDEN_EDAD.index(k[2]), k[3])):
        if anio not in anios or d not in dominios:
            continue
        n_base, w_base = asistencia_acc[(anio, d, ge, sexo)]
        n_si, w_si = asistencia_acc.get((anio, d, ge, sexo, "si"), [0, 0.0])
        filas.append({
            "anio": anio, "dominio": d, "grupo_edad": ge,
            "sexo": {"1": "Hombre", "2": "Mujer"}.get(sexo, "Total"),
            "n_muestral": n_base, "poblacion_expandida": round(w_base),
            "tasa_asistencia_pct": suprime(
                round(100 * w_si / w_base, 1) if w_base else "", n_base),
        })
    return filas


def tabla_muestra(acc, anios, dominios):
    filas = []
    for anio in anios:
        for d in dominios:
            n = acc.n((anio, d, "pob_25mas"))
            if not n:
                continue
            filas.append({
                "anio": anio, "dominio": d,
                "n_muestral_25mas": n,
                "poblacion_expandida_25mas": round(acc.w((anio, d, "pob_25mas"))),
                "suficiente_para_publicar": "sí" if n >= MIN_OBSERVACIONES else "no",
            })
    return filas


def indicadores_titulares(acc, anios, dpto, detector, factores):
    """Las cifras que la plataforma muestra, con universo y método declarados."""
    etiqueta_dpto = DEPARTAMENTOS.get(dpto, f"Departamento {dpto}")
    ultimo = max(anios)
    d_narp = f"NARP — {etiqueta_dpto}"
    d_dpto = f"Total {etiqueta_dpto}"
    fuente = f"{FUENTE_BASE} {min(anios)}–{ultimo} (factor de expansión {', '.join(factores)})"

    territorio = slug(etiqueta_dpto)
    esc_narp, n_esc = acc.media_escolaridad((ultimo, d_narp))
    esc_nac, _ = acc.media_escolaridad((ultimo, "Total nacional"))
    asis_narp, n_asis = acc.proporcion((ultimo, d_narp, "asistencia_si"),
                                       (ultimo, d_narp, "asistencia_base"))
    analf_narp, n_alf = acc.proporcion((ultimo, d_narp, "no_lee"),
                                       (ultimo, d_narp, "lee_base"))
    analf_nac, _ = acc.proporcion((ultimo, "Total nacional", "no_lee"),
                                  (ultimo, "Total nacional", "lee_base"))
    esc_inicial, _ = acc.media_escolaridad((min(anios), d_narp))

    def brecha(a, b, dec=1):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(a - b, dec)
        return None

    universo_esc = f"{n_esc:,} personas NARP de 25 años y más encuestadas en {ultimo}".replace(",", ".")
    metodo_esc = (f"media ponderada por factor de expansión de los años de escolaridad "
                  f"derivados del nivel educativo y el último grado aprobado "
                  f"(P6210/P6210S1 en el marco 2005, P3042/P3042S1 en el marco 2018); "
                  f"convención de grado del marco 2005 «{detector.decidida}», "
                  f"detectada sobre los datos")

    def entrada(indicador, valor, universo, medicion, metodo):
        # El territorio se declara explícitamente: estas cifras son
        # departamentales y no describen ningún municipio.
        return {"territorio": territorio, "indicador": indicador, "valor": valor,
                "universo": universo, "medicion": medicion, "fuente": fuente,
                "metodo": metodo}

    return [
        {
            "territorio": territorio,
            "indicador": f"Años de escolaridad promedio, población NARP de 25 años y más — {etiqueta_dpto} (GEIH {ultimo})",
            "valor": esc_narp,
            "universo": universo_esc,
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": metodo_esc,
        },
        {
            "territorio": territorio,
            "indicador": f"Brecha de escolaridad NARP frente al total nacional — {etiqueta_dpto} (GEIH {ultimo}, años)",
            "valor": brecha(esc_narp, esc_nac, 2),
            "universo": "población de 25 años y más",
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": "diferencia entre la media NARP departamental y la media nacional",
        },
        {
            "territorio": territorio,
            "indicador": f"Variación de la escolaridad NARP entre {min(anios)} y {ultimo} — {etiqueta_dpto} (años)",
            "valor": brecha(esc_narp, esc_inicial, 2),
            "universo": "población NARP de 25 años y más",
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": ("diferencia entre el primer y el último año de la serie; no es una "
                       "prueba de tendencia y no controla el rediseño metodológico de la GEIH"),
        },
        {
            "territorio": territorio,
            "indicador": f"Tasa de asistencia escolar 5-24 años, población NARP — {etiqueta_dpto} (GEIH {ultimo}, %)",
            "valor": asis_narp,
            "universo": f"{n_asis:,} personas NARP de 5 a 24 años encuestadas en {ultimo}".replace(",", "."),
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": "asiste / (asiste + no asiste), ponderado; la no respuesta se excluye del denominador",
        },
        {
            "territorio": territorio,
            "indicador": f"Tasa de analfabetismo 15 años y más, población NARP — {etiqueta_dpto} (GEIH {ultimo}, %)",
            "valor": analf_narp,
            "universo": f"{n_alf:,} personas NARP de 15 años y más encuestadas en {ultimo}".replace(",", "."),
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": "no sabe leer ni escribir / (sabe + no sabe), ponderado",
        },
        {
            "territorio": territorio,
            "indicador": f"Brecha de analfabetismo NARP frente al total nacional — {etiqueta_dpto} (GEIH {ultimo}, p.p.)",
            "valor": brecha(analf_narp, analf_nac),
            "universo": "población de 15 años y más",
            "medicion": "estimada",
            "fuente": fuente,
            "metodo": "diferencia en puntos porcentuales entre ambas tasas",
        },
    ]


def escribir_csv(ruta, filas):
    if not filas:
        print(f"  aviso: sin filas para {ruta}; no se escribe.")
        return
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"  escrito {ruta}  ({len(filas)} filas)")


# =============================================================================
# Programa
# =============================================================================
DPTO_ACTUAL = "76"  # lo fija main(); lo usa la segunda pasada de escolaridad


def main():
    global DPTO_ACTUAL
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", required=True,
                    help="carpeta raíz con los microdatos GEIH descomprimidos")
    ap.add_argument("--anios", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024],
                    help="años a procesar (por defecto 2020 2021 2022 2023 2024)")
    ap.add_argument("--dpto", default="76",
                    help="código DANE de departamento para el dominio territorial "
                         "(por defecto 76, Valle del Cauca)")
    ap.add_argument("--anio-por-defecto", type=int, default=None,
                    help="año a asignar a los archivos cuya ruta no lo declara "
                         "(por ejemplo, una carpeta suelta por municipio). Sin "
                         "esta opción esos archivos se reportan y se omiten.")
    ap.add_argument("--meses", nargs="+", type=int, default=None,
                    help="submuestra de meses (1-12). Omitido = todos los disponibles. "
                         "La elección queda declarada en el manifiesto.")
    ap.add_argument("--dominios-archivo", choices=["auto", "todos", "area"],
                    default="auto",
                    help="qué archivos usar cuando la entrega parte personas en "
                         "Área/Cabecera/Resto: «auto» usa Cabecera+Resto (que "
                         "particionan la muestra), «todos» los suma —duplica las "
                         "áreas metropolitanas y no se recomienda— y «area» usa "
                         "solo el subconjunto de las 23 ciudades")
    ap.add_argument("--patron", default="Caracteristicas generales",
                    help="fragmento del nombre del archivo del módulo a leer")
    ap.add_argument("--salida", default="data")
    ap.add_argument("--fuente-escolaridad", choices=["esc", "derivada"], default="esc",
                    help="«esc» usa la columna ESC del DANE donde exista y deriva "
                         "en el resto; «derivada» deriva los cinco años a partir "
                         "del nivel y el grado, para comparar ambos métodos.")
    ap.add_argument("--convencion-grado", choices=["auto", "absoluta", "relativa"],
                    default="auto",
                    help="codificación de P6210S1; «auto» la detecta sobre los datos")
    ap.add_argument("--max-filas", type=int, default=None,
                    help="límite de filas por archivo, para pruebas rápidas")
    ap.add_argument("--minimo-archivos-anio", type=int, default=12,
                    help="archivos mensuales esperados por año; si hay menos, se advierte")
    ap.add_argument("--sin-hash", action="store_true",
                    help="omite el hash de los archivos fuente")
    ap.add_argument("--municipio", default=None,
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.municipio:
        raise SystemExit(
            "\n✗ La GEIH no es representativa a nivel municipal fuera de las 23 ciudades\n"
            "  y áreas metropolitanas del diseño muestral, y Buenaventura no está entre\n"
            "  ellas. Este ETL trabaja con dominios departamental y nacional. Para la\n"
            "  cifra municipal usa etl_educacion_cnpv.py (censo) o etl_educacion_educ.py.\n")

    DPTO_ACTUAL = args.dpto.zfill(2)
    anios = sorted(set(args.anios))
    etiqueta_dpto = DEPARTAMENTOS.get(DPTO_ACTUAL, f"Departamento {DPTO_ACTUAL}")

    print(f"ETL educación GEIH · versión {VERSION}")
    print(f"Años {anios[0]}–{anios[-1]} · dominio territorial {etiqueta_dpto} ({DPTO_ACTUAL})")

    clases = {"auto": {"CABECERA", "RESTO", "UNICO"},
              "todos": {"AREA", "CABECERA", "RESTO", "UNICO"},
              "area": {"AREA", "UNICO"}}[args.dominios_archivo]
    meses = set(args.meses) if args.meses else None

    print("\n[1/5] Descubriendo archivos")
    archivos, descartados, vistos_csv = descubrir(
        args.raiz, set(anios), args.patron, meses, clases, args.anio_por_defecto)
    if not archivos:
        detalle = ""
        if descartados:
            detalle = "\n  Sí se encontraron archivos, pero quedaron fuera:\n" + "\n".join(
                f"    · {len(v)} por «{k}»" + (
                    "\n" + "\n".join(f"        {os.path.relpath(r, args.raiz)}" for r in v[:5])
                    if "sin año" in k else "")
                for k, v in descartados.items())
            detalle += ("\n  Si esa carpeta corresponde a un año concreto, pásalo con "
                        "--anio-por-defecto.")
        if not vistos_csv:
            raise SystemExit(
                f"✗ Bajo {os.path.abspath(args.raiz)} no se encontró NINGÚN archivo "
                f".CSV, ni suelto ni dentro de un .ZIP.\n"
                f"  No es un problema del patrón: es la ruta.\n"
                f"  Comprueba que la carpeta existe y que dentro hay CSV ya "
                f"descomprimidos, y recuerda que en Windows la ruta debe ir entre "
                f"comillas si tiene espacios o tildes.")
        muestra = "\n".join(f"        {os.path.relpath(r, args.raiz)}"
                             for r in vistos_csv[:10])
        raise SystemExit(
            f"✗ Se encontraron {len(vistos_csv)} archivos .CSV bajo {args.raiz}, pero "
            f"ninguno quedó utilizable con el patrón «{args.patron}».{detalle}\n"
            f"  Los primeros que hay ahí son:\n{muestra}\n"
            f"  Si el módulo de personas se llama de otra forma, pásala con --patron "
            f"(basta un fragmento, sin tildes ni mayúsculas).")
    por_anio = defaultdict(int)
    por_clase = defaultdict(int)
    for anio, ruta in archivos:
        por_anio[anio] += 1
        por_clase[clase_dominio(ruta)] += 1
    print(f"  clases de archivo usadas: " +
          ", ".join(f"{c}={n}" for c, n in sorted(por_clase.items())))
    for motivo, rutas in descartados.items():
        print(f"  descartados por «{motivo}»: {len(rutas)}")
        if "sin año" in motivo:
            for r in rutas[:5]:
                print(f"      {os.path.relpath(r, args.raiz)}")
            if len(rutas) > 5:
                print(f"      … y {len(rutas) - 5} más")
    if por_clase.get("AREA") and por_clase.get("CABECERA") and args.dominios_archivo == "todos":
        print("  ⚠ estás sumando Área y Cabecera: las áreas metropolitanas quedarán "
              "contadas dos veces.")
    for anio in anios:
        n = por_anio.get(anio, 0)
        esperados = args.minimo_archivos_anio * (
            len(clases & {"AREA", "CABECERA", "RESTO"}) or 1) if por_clase.get("CABECERA") else args.minimo_archivos_anio
        marca = "OK" if n >= min(esperados, args.minimo_archivos_anio) else f"INCOMPLETO ({n})"
        print(f"  {anio}: {n} archivo(s)  [{marca}]")
    print(f"  total: {len(archivos)} archivos")

    print("\n[2/5] Leyendo y acumulando")
    detector = DetectorGrado(args.convencion_grado)
    (acc, nivel_acc, asistencia_acc, registro, factores, faltantes,
     sin_columna, usa_esc) = procesar(archivos, DPTO_ACTUAL, detector, args.max_filas,
                                      args.fuente_escolaridad)

    dominios = ["Total nacional", "NARP — nacional", "No NARP — nacional",
                f"Total {etiqueta_dpto}", f"NARP — {etiqueta_dpto}",
                f"No NARP — {etiqueta_dpto}"]

    print("\n[3/5] Verificando cobertura muestral")
    muestra = tabla_muestra(acc, anios, dominios)
    insuficientes = [m for m in muestra if m["suficiente_para_publicar"] == "no"]
    for m in muestra:
        print(f"  {m['anio']} · {m['dominio']:34s} n={m['n_muestral_25mas']:>7,} "
              f"expandido={m['poblacion_expandida_25mas']:>12,}")
    if insuficientes:
        print(f"  aviso: {len(insuficientes)} celda(s) por debajo de {MIN_OBSERVACIONES} "
              f"observaciones; se publican como {SUPRIMIDA}.")

    sin_escolaridad = sorted({a for a in anios
                              if not any(k[0] == a for k in acc.distribucion)})
    if sin_escolaridad:
        print(f"\n  ⚠ sin datos de escolaridad en {', '.join(str(a) for a in sin_escolaridad)}: "
              f"los archivos de esos años no traen la variable de nivel educativo "
              f"bajo ninguno de los alias conocidos. Inspecciona uno de esos archivos "
              f"y añade el nombre real al diccionario ALIAS antes de publicar la serie.")

    print("\n[4/5] Calculando indicadores")
    serie = serie_anual(acc, anios, dominios)
    distribucion = tabla_distribucion(acc, anios, dominios)
    niveles = tabla_nivel(nivel_acc, anios, dominios)
    asistencia = tabla_asistencia(asistencia_acc, anios, dominios)
    titulares = indicadores_titulares(acc, anios, DPTO_ACTUAL, detector, factores)
    for t in titulares:
        print(f"  {t['indicador'][:78]:78s} {t['valor']}")

    print("\n[5/5] Escribiendo salidas")
    escribir_csv(os.path.join(args.salida, "educacion_geih_serie_anual.csv"), serie)
    escribir_csv(os.path.join(args.salida, "educacion_geih_nivel.csv"), niveles)
    escribir_csv(os.path.join(args.salida, "educacion_geih_asistencia.csv"), asistencia)
    escribir_csv(os.path.join(args.salida, "educacion_geih_muestra.csv"), muestra)
    escribir_csv(os.path.join(args.salida,
                              "educacion_geih_distribucion_escolaridad.csv"), distribucion)
    escribir_csv(os.path.join(args.salida, "educacion_indicadores_geih.csv"), titulares)

    manifiesto = {
        "script": os.path.basename(__file__),
        "version": VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": FUENTE_BASE,
        "anios": anios,
        "dominio_territorial": {"codigo": DPTO_ACTUAL, "nombre": etiqueta_dpto},
        "archivos": [
            {**r, "sha256": None if (args.sin_hash or r.get("dentro_de_zip"))
                              else sha256(r["ruta"])}
            for r in registro
        ],
        "archivos_por_anio": dict(sorted(por_anio.items())),
        "archivos_por_clase_dominio": dict(sorted(por_clase.items())),
        "regla_dominio_archivo": {
            "modo": args.dominios_archivo,
            "clases_usadas": sorted(clases),
            "explicacion": ("Hasta 2021 la entrega parte el módulo de personas en "
                            "Área, Cabecera y Resto. Área está contenida en Cabecera; "
                            "sumar las tres duplicaría las 23 ciudades y áreas "
                            "metropolitanas. El modo «auto» usa Cabecera + Resto, que "
                            "particionan la muestra sin solaparse."),
        },
        "meses_solicitados": sorted(meses) if meses else "todos los disponibles",
        "archivos_descartados": {k: len(v) for k, v in descartados.items()},
        "factores_de_expansion": factores,
        "convencion_grado_detectada": detector.decidida,
        "columnas_ausentes_por_concepto": {k: sorted(v) for k, v in sin_columna.items()},
        "archivos_con_columna_esc": usa_esc,
        "fuente_de_los_anios_de_escolaridad": (
            "columna ESC del propio microdato donde está disponible; equivalencia "
            "nivel-grado en el resto"
            if args.fuente_escolaridad == "esc" else
            "equivalencia nivel-grado en los cinco años; la columna ESC no se usa"),
        "preferencia_de_escolaridad_solicitada": args.fuente_escolaridad,
        "maximo_grado_observado_por_nivel_marco_2005": {
            NIVEL_2005.get(k, k): v for k, v in sorted(detector.max_por_nivel.items())
        },
        "grados_descartados_por_fuera_de_rango_marco_2005": {
            NIVEL_2005.get(k, k): v for k, v in sorted(detector.descartados.items())
        },
        "tablas_de_nivel_por_marco": {
            "2005": "P6210 · 6 categorías · convención de grado detectada",
            "2018": "P3042 · 13 categorías · grado siempre relativo al nivel",
        },
        "filtros": {
            "categoria_narp": [GRUPO_ETNICO[c] for c in sorted(CODIGOS_NARP)],
            "variable_etnica": "P6080 (autorreconocimiento)",
            "poblacion_escolaridad": "25 años y más",
            "poblacion_asistencia": "5 a 24 años",
            "poblacion_alfabetismo": "15 años y más",
        },
        "archivos_omitidos": {k: v for k, v in faltantes.items()},
        "umbral_supresion": MIN_OBSERVACIONES,
        "advertencias": [
            "La GEIH no es representativa a nivel municipal fuera de las 23 ciudades y "
            "áreas metropolitanas del diseño muestral. Estas cifras son departamentales "
            "y nacionales; no describen a Buenaventura ni a ningún otro municipio.",
            "La serie 2020–2024 atraviesa la actualización metodológica de la GEIH y el "
            "período de recolección afectado por la pandemia: las comparaciones "
            "interanuales deben leerse como orden de magnitud y no como tendencia medida.",
            "Los años de escolaridad se derivan de P6210 y P6210S1; la convención de "
            "codificación del grado se detecta sobre los datos y queda registrada en este "
            "manifiesto. Cualquier cifra derivada se publica como estimada.",
            "No se calculan errores estándar ni coeficientes de variación: el microdato "
            "público no trae las variables de diseño muestral necesarias. El tamaño "
            "muestral por celda se publica junto a cada estimación para que el lector "
            "juzgue su precisión.",
            "El autorreconocimiento étnico está afectado por subregistro sistemático; los "
            "denominadores NARP deben leerse como un piso.",
            f"Toda celda con menos de {MIN_OBSERVACIONES} observaciones muestrales se "
            f"publica como {SUPRIMIDA}.",
            "La desviación estándar publicada describe la dispersión de los años de "
            "escolaridad entre personas, no la precisión con que se estima el promedio: "
            "no es un error estándar y no debe leerse como intervalo de confianza.",
        ],
    }
    os.makedirs(args.salida, exist_ok=True)
    ruta_man = os.path.join(args.salida, "geih_manifiesto.json")
    with open(ruta_man, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"  escrito {ruta_man}")
    print("\nListo. Ahora ejecuta:  python seed_education.py --datos", args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
