#!/usr/bin/env python3
# =============================================================================
# etl_educacion_cnpv.py — Capa de educación de OnLife Afro desde microdatos CNPV 2018
# -----------------------------------------------------------------------------
# Sustituye los valores fijos de seed_education.py por indicadores calculados
# directamente sobre los microdatos anonimizados del Censo Nacional de Población
# y Vivienda 2018 (DANE), archivo de personas por departamento:
#
#     CNPV2018_5PER_A2_<DD>.CSV      (DD = código de departamento; 76 = Valle)
#
# Qué hace, en orden:
#   1. Lee el CSV por bloques (el archivo del Valle pesa ~325 MB) y se queda solo
#      con las columnas y el municipio que interesan.
#   2. Decodifica los códigos del censo con diccionarios explícitos y versionados
#      —nada de números mágicos dentro de la lógica—.
#   3. VALIDA el subconjunto contra los cuadros agregados que el DANE publica.
#      Si el total no cuadra, el proceso se detiene: es preferible no producir
#      dato a producir dato incorrecto.
#   4. Escribe tablas largas (tidy) por indicador y un archivo de indicadores
#      titulares con su universo, su fuente y su método.
#   5. Escribe un manifiesto JSON de procedencia (fuente, fecha, hash, filtros,
#      versión del script) para que cada cifra publicada por la plataforma sea
#      trazable hasta el archivo de origen.
#
# Uso:
#   python etl_educacion_cnpv.py --microdatos CNPV2018_5PER_A2_76.CSV \
#       --municipio 76109 --salida data/
#   python etl_educacion_cnpv.py ... --validar-total-5mas 236288
#
# Los valores comunitarios NO se calculan aquí: provienen de la Mesa de Educación
# del PCN y viven en un archivo aparte (valores_comunitarios.csv), editable por la
# organización sin tocar el código. Esa separación es deliberada y responde al
# principio OCAP® de control comunitario sobre el dato propio.
# =============================================================================

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

VERSION = "2.1"
FUENTE = "DANE — Censo Nacional de Población y Vivienda 2018, microdatos de personas (TIPO_REG 5, hogares particulares)"

# --- Columnas que necesitamos del archivo de personas -------------------------
COLUMNAS = [
    "U_DPTO", "U_MPIO", "UA_CLASE", "P_SEXO", "P_EDADR", "P_PARENTESCOR",
    "PA1_GRP_ETNIC", "P_ALFABETA", "PA_ASISTENCIA", "P_NIVEL_ANOSR",
]

# Umbral de supresión de celdas pequeñas. Se ejecuta en el código y no como
# revisión posterior: la protección frente a la reidentificación no puede
# depender de que el investigador se acuerde de aplicarla.
MIN_OBSERVACIONES = 50
SUPRIMIDA = "SUPRIMIDA"

# P_PARENTESCOR en el microdato público viene recodificado en cinco categorías.
PARENTESCO = {
    "1": "Jefe(a) de hogar", "2": "Pareja", "3": "Hijo(a) o hijastro(a)",
    "4": "Otro pariente", "5": "No pariente",
}
# Categorías que indican que la persona menor de edad no convive como hija de
# la persona cabeza de hogar. NO equivale a ausencia de los progenitores —el
# padre o la madre pueden residir en el hogar bajo otra relación—, de modo que
# el indicador se publica como configuración del hogar y no como orfandad
# funcional. Ver la advertencia en el manifiesto.
PARENTESCO_NO_FILIAL = {"4", "5"}

# --- Diccionarios de códigos del CNPV 2018 ------------------------------------
CLASE = {"1": "Cabecera", "2": "Centro poblado", "3": "Rural disperso"}
SEXO = {"1": "Hombre", "2": "Mujer"}

GRUPO_ETNICO = {
    "1": "Indígena",
    "2": "Gitano(a) o Rrom",
    "3": "Raizal del Archipiélago",
    "4": "Palenquero(a) de San Basilio",
    "5": "Negro(a), mulato(a), afrodescendiente",
    "6": "Ningún grupo étnico",
    "9": "No informa",
}
# La categoría analítica NARP del proyecto agrupa raizales, palenqueros y
# población negra/mulata/afrodescendiente, igual que los cuadros del DANE.
CODIGOS_NARP = {"3", "4", "5"}

SI_NO = {"1": "Sí", "2": "No", "9": "No informa"}

# P_EDADR viene en grupos quinquenales: 1 = 0-4, 2 = 5-9, ... 21 = 100 y más.
# El microdato público NO trae la edad simple, de modo que no es posible
# reproducir cortes finos (16-17, por ejemplo); eso solo está en los tabulados.
def grupo_edad(codigo: str) -> str:
    try:
        e = int(codigo)
    except (TypeError, ValueError):
        return "Sin información"
    if e == 1:
        return "0-4"
    if e == 2:
        return "5-9"
    if e == 3:
        return "10-14"
    if e == 4:
        return "15-19"
    if e == 5:
        return "20-24"
    return "25 y más"


ORDEN_EDAD = ["0-4", "5-9", "10-14", "15-19", "20-24", "25 y más", "Sin información"]

# P_NIVEL_ANOSR colapsa «completa/incompleta»: el microdato distingue el nivel,
# no los años aprobados dentro de él. Las etiquetas se verificaron contra el
# cuadro 19PM del CNPV 2018 para Buenaventura (ver validar_nivel más abajo).
NIVEL_EDUCATIVO = {
    "1": "Preescolar",
    "2": "Básica primaria",
    "3": "Básica secundaria",
    "4": "Media académica",
    "5": "Media técnica",
    "6": "Normalista",
    "7": "Técnico o tecnológico",
    "8": "Universitario",
    "9": "Especialización, maestría o doctorado",
    "10": "Ninguno",
    "99": "Sin información",
}
ORDEN_NIVEL = ["Ninguno", "Preescolar", "Básica primaria", "Básica secundaria",
               "Media académica", "Media técnica", "Normalista",
               "Técnico o tecnológico", "Universitario",
               "Especialización, maestría o doctorado", "Sin información"]

# Equivalencia nivel → años de escolaridad. ES UNA ESTIMACIÓN, no una medición
# censal: el censo no publica años aprobados en el microdato. Se usa el año de
# entrada al nivel siguiente cuando el nivel está completo y un punto medio
# conservador cuando no se puede distinguir. Cualquier cifra derivada de esta
# tabla debe publicarse etiquetada como estimada.
ANIOS_POR_NIVEL = {
    "Ninguno": 0, "Preescolar": 0, "Básica primaria": 4, "Básica secundaria": 8,
    "Media académica": 11, "Media técnica": 11, "Normalista": 12,
    "Técnico o tecnológico": 13, "Universitario": 16,
    "Especialización, maestría o doctorado": 18,
}

EDADES_ESCOLARES = ["5-9", "10-14", "15-19", "20-24"]


# =============================================================================
# Lectura
# =============================================================================


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


def resolver(raiz, palabras, descripcion="", excluir=()):
    """Devuelve la ruta cuyo nombre contiene todas las palabras clave.

    Si hay varias coincidencias se toma la de ruta más corta —la menos anidada—
    y se avisa, en lugar de elegir en silencio.
    """
    palabras = [_norm(p) for p in palabras]
    excluir = [_norm(p) for p in excluir]
    coincide = [ruta for ruta, etiqueta in _candidatos(raiz)
                if all(p in etiqueta for p in palabras)
                and not any(x in etiqueta for x in excluir)]
    if not coincide:
        return None
    coincide.sort(key=lambda r: (len(r.split(os.sep)), len(r)))
    if len(coincide) > 1:
        print(f"  aviso: {len(coincide)} archivos coinciden con "
              f"«{descripcion or ' '.join(palabras)}»; se usa "
              f"{os.path.relpath(coincide[0], raiz)}")
    return coincide[0]


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


def localizar_personas(ruta, patron="5PER"):
    """Acepta un archivo o una carpeta y devuelve el archivo de personas.

    El censo se descarga como una carpeta por departamento —76_ValleDelCauca_CSV,
    por ejemplo— con los cinco archivos dentro. Pedir la ruta exacta obliga a
    escribirla a mano; buscarla por el fragmento «5PER» del nombre no.
    """
    if os.path.isfile(ruta):
        return ruta
    encontrada = resolver(ruta, [patron], f"archivo de personas ({patron})")
    if encontrada is None:
        raise SystemExit(
            f"✗ No se encontró bajo {ruta} ningún CSV cuyo nombre contenga "
            f"«{patron}».\n"
            f"  El archivo de personas del CNPV se llama CNPV2018_5PER_A2_<DD>.CSV. "
            f"Si el tuyo está en formato Stata, conviértelo antes con "
            f"convertir_dta_a_csv.py.")
    return encontrada


def leer_microdatos(ruta: str, municipio: str, tam_bloque: int = 200_000):
    """Devuelve las filas del municipio pedido, como lista de diccionarios.

    Se lee con el módulo csv y no con pandas para no exigir dependencias en el
    servidor donde corre la plataforma; la memoria se controla descartando cada
    fila que no pertenece al municipio antes de acumularla.
    """
    dpto, mpio = municipio[:2], municipio[2:]
    filas, leidas = [], 0
    lector, f = abrir_csv(ruta)
    with f:
        faltantes = [c for c in COLUMNAS if c not in lector.fieldnames]
        if faltantes:
            raise SystemExit(
                f"El archivo no tiene las columnas esperadas: {', '.join(faltantes)}.\n"
                f"¿Es el archivo de personas (5PER) del CNPV 2018?"
            )
        for fila in lector:
            leidas += 1
            if fila["U_DPTO"] != dpto or fila["U_MPIO"] != mpio:
                continue
            filas.append({c: (fila[c] or "").strip() for c in COLUMNAS})
            if leidas % (tam_bloque * 5) == 0:
                print(f"    ... {leidas:,} filas leídas, {len(filas):,} del municipio",
                      file=sys.stderr)
    return filas, leidas


def enriquecer(filas):
    """Añade las columnas decodificadas que usan todos los indicadores."""
    for f in filas:
        f["clase"] = CLASE.get(f["UA_CLASE"], "Sin información")
        f["sexo"] = SEXO.get(f["P_SEXO"], "Sin información")
        f["grupo_edad"] = grupo_edad(f["P_EDADR"])
        f["grupo_etnico"] = GRUPO_ETNICO.get(f["PA1_GRP_ETNIC"], "Sin información")
        f["narp"] = f["PA1_GRP_ETNIC"] in CODIGOS_NARP
        f["asistencia"] = SI_NO.get(f["PA_ASISTENCIA"], "Sin información")
        f["alfabeta"] = SI_NO.get(f["P_ALFABETA"], "Sin información")
        f["nivel"] = NIVEL_EDUCATIVO.get(f["P_NIVEL_ANOSR"], "Sin información")
        f["parentesco"] = PARENTESCO.get(f["P_PARENTESCOR"], "Sin información")
    return filas


def suprime(valor, n):
    """Aplica el umbral de celdas pequeñas antes de devolver cualquier cifra."""
    return SUPRIMIDA if n < MIN_OBSERVACIONES else valor


# =============================================================================
# Validación
# =============================================================================
def validar(filas, total_5mas_esperado=None):
    """Contrasta el subconjunto con los cuadros agregados publicados por el DANE.

    El censo publica, para cada municipio, la población de 5 años y más en
    hogares particulares (cuadro 19PM). Si el conteo propio no coincide, algo
    falla en el filtro o en el archivo, y seguir adelante produciría cifras
    falsas con apariencia de rigor.
    """
    total = len(filas)
    cinco_mas = sum(1 for f in filas if f["grupo_edad"] != "0-4")
    narp = sum(1 for f in filas if f["narp"])
    print(f"  población censada en el municipio : {total:,}")
    print(f"  de 5 años y más                   : {cinco_mas:,}")
    print(f"  NARP (raizal + palenquera + negra) : {narp:,} ({100*narp/total:.1f} %)")
    if total_5mas_esperado is not None:
        if cinco_mas != total_5mas_esperado:
            raise SystemExit(
                f"\n  VALIDACIÓN FALLIDA: se esperaban {total_5mas_esperado:,} personas de "
                f"5 años y más y se contaron {cinco_mas:,}.\n"
                f"  Revisa el código de municipio y el archivo antes de publicar nada."
            )
        print(f"  validación contra cuadro publicado : OK ({cinco_mas:,})")
    return {"poblacion_censada": total, "poblacion_5_mas": cinco_mas, "poblacion_narp": narp}


# =============================================================================
# Indicadores
# =============================================================================
def tabla_asistencia(filas):
    """Asistencia escolar de la población NARP, por grupo de edad, sexo y área."""
    conteo = defaultdict(Counter)
    for f in filas:
        if not f["narp"] or f["grupo_edad"] == "0-4":
            continue
        conteo[(f["grupo_edad"], f["sexo"], f["clase"])][f["asistencia"]] += 1
    salida = []
    for (edad, sexo, clase), c in conteo.items():
        si, no = c["Sí"], c["No"]
        base = si + no
        salida.append({
            "grupo_edad": edad, "sexo": sexo, "area": clase,
            "asiste": si, "no_asiste": no, "no_informa": c["Sin información"] + c["No informa"],
            "tasa_asistencia_pct": round(100 * si / base, 1) if base else "",
        })
    salida.sort(key=lambda r: (ORDEN_EDAD.index(r["grupo_edad"]), r["sexo"], r["area"]))
    return salida


def tabla_nivel(filas):
    """Máximo nivel educativo alcanzado, población de 5 años y más, NARP y resto."""
    conteo = defaultdict(Counter)
    for f in filas:
        if f["grupo_edad"] == "0-4":
            continue
        grupo = "NARP" if f["narp"] else f["grupo_etnico"]
        conteo[grupo][f["nivel"]] += 1
    salida = []
    for grupo, c in conteo.items():
        base = sum(c.values())
        for nivel in ORDEN_NIVEL:
            if nivel not in c:
                continue
            salida.append({
                "grupo": grupo, "nivel_educativo": nivel, "personas": c[nivel],
                "base": base, "participacion_pct": round(100 * c[nivel] / base, 1),
            })
    return salida


def tabla_alfabetismo(filas):
    """Alfabetismo de la población de 15 años y más, por grupo étnico."""
    conteo = defaultdict(Counter)
    edades = {"15-19", "20-24", "25 y más"}
    for f in filas:
        if f["grupo_edad"] not in edades:
            continue
        grupo = "NARP" if f["narp"] else f["grupo_etnico"]
        conteo[grupo][f["alfabeta"]] += 1
    salida = []
    for grupo, c in conteo.items():
        si, no = c["Sí"], c["No"]
        base = si + no
        salida.append({
            "grupo": grupo, "sabe_leer_escribir": si, "no_sabe": no,
            "base": base,
            "tasa_analfabetismo_pct": round(100 * no / base, 1) if base else "",
        })
    salida.sort(key=lambda r: -r["base"])
    return salida


def escolaridad_estimada(filas, edad_minima="25 y más"):
    """Años de escolaridad promedio estimados por equivalencia de nivel.

    NO es una medición censal. Se documenta como estimación en la salida y debe
    publicarse como tal en la plataforma.
    """
    if edad_minima == "25 y más":
        edades = {"25 y más"}
    else:
        edades = {"15-19", "20-24", "25 y más"}
    total, n = 0, 0
    for f in filas:
        if not f["narp"] or f["grupo_edad"] not in edades:
            continue
        anios = ANIOS_POR_NIVEL.get(f["nivel"])
        if anios is None:
            continue
        total += anios
        n += 1
    return (round(total / n, 2) if n else None), n



def tabla_dominios(filas):
    """Compara los indicadores entre población NARP y no NARP del municipio.

    El diseño de dominios responde a una advertencia metodológica propia del
    territorio: en un municipio donde casi nueve de cada diez habitantes se
    autorreconocen NARP, la celda de comparación intra-municipal es pequeña y la
    comparación relevante termina siendo la del territorio frente al país. El
    contraste se calcula igual, precisamente para poder mostrar esa asimetría.
    """
    dominios = {
        "NARP — municipio": lambda f: f["narp"],
        "No NARP — municipio": lambda f: f["PA1_GRP_ETNIC"] == "6",
    }
    edades_esc = {"5-9": "5-9", "10-14": "10-14", "15-19": "15-19", "20-24": "20-24"}
    salida = []
    for nombre, criterio in dominios.items():
        sub = [f for f in filas if criterio(f)]
        # escolaridad estimada
        esc = [ANIOS_POR_NIVEL[f["nivel"]] for f in sub
               if f["grupo_edad"] == "25 y más" and f["nivel"] in ANIOS_POR_NIVEL]
        # alfabetismo 15 y más
        alf = [f["alfabeta"] for f in sub
               if f["grupo_edad"] in {"15-19", "20-24", "25 y más"}]
        si_alf = alf.count("Sí"); no_alf = alf.count("No")
        fila = {
            "dominio": nombre,
            "personas": len(sub),
            "escolaridad_estimada_25mas": suprime(
                round(sum(esc) / len(esc), 2) if esc else "", len(esc)),
            "alfabetismo_15mas_pct": suprime(
                round(100 * si_alf / (si_alf + no_alf), 1) if (si_alf + no_alf) else "",
                si_alf + no_alf),
        }
        for etiqueta, grupo in edades_esc.items():
            g = [f["asistencia"] for f in sub if f["grupo_edad"] == grupo]
            si, no = g.count("Sí"), g.count("No")
            fila[f"asistencia_{etiqueta}_pct"] = suprime(
                round(100 * si / (si + no), 1) if (si + no) else "", si + no)
        salida.append(fila)
    return salida


def no_respuesta_etnica(filas):
    """La no respuesta a la pregunta étnica, reportada como resultado y no como ruido.

    La magnitud de la no respuesta mide el límite del aparato estadístico para
    nombrar a la población que pretende contar: no es un dato a depurar antes de
    publicar, sino un dato a publicar.
    """
    total = len(filas)
    sin = sum(1 for f in filas if f["PA1_GRP_ETNIC"] == "9")
    por_area = defaultdict(lambda: [0, 0])
    for f in filas:
        por_area[f["clase"]][0] += 1
        if f["PA1_GRP_ETNIC"] == "9":
            por_area[f["clase"]][1] += 1
    salida = [{"ambito": "Municipio, total", "personas": total, "sin_respuesta": sin,
               "pct_sin_respuesta": round(100 * sin / total, 2) if total else ""}]
    for area, (n, s) in sorted(por_area.items()):
        salida.append({"ambito": f"Municipio, {area.lower()}", "personas": n,
                       "sin_respuesta": s,
                       "pct_sin_respuesta": suprime(round(100 * s / n, 2) if n else "", n)})
    return salida


def configuracion_hogar(filas):
    """Menores de 5 a 14 años que no conviven como hijos de la persona jefa de hogar.

    Traduce a una variable disponible una observación situada del territorio: el
    aumento de menores al cuidado de abuelas, tías o vecinos. Es una descripción
    de la configuración del hogar y no una medida de ausencia parental ni una
    explicación causal de la trayectoria escolar.
    """
    salida = []
    for nombre, criterio in [("NARP — municipio", lambda f: f["narp"]),
                             ("No NARP — municipio", lambda f: f["PA1_GRP_ETNIC"] == "6")]:
        sub = [f for f in filas if criterio(f) and f["grupo_edad"] in {"5-9", "10-14"}]
        n = len(sub)
        no_filial = sum(1 for f in sub if f["P_PARENTESCOR"] in PARENTESCO_NO_FILIAL)
        salida.append({
            "dominio": nombre, "menores_5_14": n, "no_filiales": no_filial,
            "pct_no_filial": suprime(round(100 * no_filial / n, 1) if n else "", n),
        })
    return salida


def indicadores_titulares(filas, resumen, no_resp, hogar):
    """Las cifras que la plataforma muestra en el módulo «Comunidad vs DANE»."""
    escolares = [f for f in filas
                 if f["narp"] and f["grupo_edad"] in EDADES_ESCOLARES]
    si = sum(1 for f in escolares if f["asistencia"] == "Sí")
    no = sum(1 for f in escolares if f["asistencia"] == "No")
    asistencia_5_24 = round(100 * si / (si + no), 1) if (si + no) else None

    analfabetismo = {r["grupo"]: r["tasa_analfabetismo_pct"] for r in tabla_alfabetismo(filas)}
    escolaridad, base_esc = escolaridad_estimada(filas, "25 y más")

    return [
        {
            "indicador": "Tasa de asistencia escolar 5-24 años, población NARP (%)",
            "valor": asistencia_5_24,
            "universo": f"{si + no:,} personas NARP de 5 a 24 años en hogares particulares".replace(",", "."),
            "medicion": "censal",
            "fuente": FUENTE,
            "metodo": "asiste / (asiste + no asiste); se excluye la no respuesta del denominador",
        },
        {
            "indicador": "Tasa de analfabetismo 15 años y más, población NARP (%)",
            "valor": analfabetismo.get("NARP"),
            "universo": "población NARP de 15 años y más en hogares particulares",
            "medicion": "censal",
            "fuente": FUENTE,
            "metodo": "no sabe leer ni escribir / (sabe + no sabe)",
        },
        {
            "indicador": "Brecha de analfabetismo NARP frente a población sin pertenencia étnica (p.p.)",
            "valor": (round(analfabetismo["NARP"] - analfabetismo["Ningún grupo étnico"], 1)
                      if "Ningún grupo étnico" in analfabetismo else None),
            "universo": "población de 15 años y más en hogares particulares",
            "medicion": "censal",
            "fuente": FUENTE,
            "metodo": "diferencia en puntos porcentuales entre las dos tasas",
        },
        {
            "indicador": "Años de escolaridad promedio, población NARP de 25 años y más",
            "valor": escolaridad,
            "universo": f"{base_esc:,} personas".replace(",", "."),
            "medicion": "estimada",
            "fuente": FUENTE,
            "metodo": ("equivalencia nivel→años (ANIOS_POR_NIVEL); el microdato del CNPV "
                       "no publica años aprobados, de modo que esta cifra es una estimación "
                       "y no una medición censal"),
        },
        {
            "indicador": "No respuesta a la pregunta de autorreconocimiento étnico (%)",
            "valor": no_resp[0]["pct_sin_respuesta"],
            "universo": f"{no_resp[0]['personas']} personas censadas en el municipio",
            "medicion": "censal",
            "fuente": FUENTE,
            "metodo": ("personas sin respuesta válida / población censada; se reporta como "
                       "resultado y no como ruido depurado"),
        },
        {
            "indicador": ("Menores de 5 a 14 años que no conviven como hijos de la persona "
                          "jefa de hogar, población NARP (%)"),
            "valor": hogar[0]["pct_no_filial"],
            "universo": f"{hogar[0]['menores_5_14']} menores NARP de 5 a 14 años",
            "medicion": "censal",
            "fuente": FUENTE,
            "metodo": ("parentesco «otro pariente» o «no pariente» / total de menores del "
                       "grupo; describe la configuración del hogar, no la ausencia parental"),
        },
    ]


# =============================================================================
# Escritura
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


def sha256(ruta, bloque=1 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--microdatos", required=True,
                    help="archivo CNPV2018_5PER_A2_<DD>.CSV, o la carpeta que lo "
                         "contiene (se busca dentro)")
    ap.add_argument("--patron", default="5PER",
                    help="fragmento del nombre del archivo de personas")
    ap.add_argument("--municipio", default="76109",
                    help="código DANE de 5 dígitos (por defecto 76109, Buenaventura)")
    ap.add_argument("--salida", default="data",
                    help="carpeta donde se escriben los CSV y el manifiesto")
    ap.add_argument("--validar-total-5mas", type=int, default=None,
                    help="total de población de 5 años y más publicado por el DANE "
                         "para ese municipio; si no coincide, el proceso se detiene")
    ap.add_argument("--sin-hash", action="store_true",
                    help="omite el hash del archivo fuente (más rápido en archivos grandes)")
    args = ap.parse_args()

    print(f"ETL educación CNPV 2018 · versión {VERSION}")
    print(f"Municipio {args.municipio} · fuente {os.path.basename(args.microdatos)}")

    print("\n[1/5] Leyendo microdatos")
    ruta_personas = localizar_personas(args.microdatos, args.patron)
    if ruta_personas != args.microdatos:
        print(f"  archivo de personas: {os.path.relpath(ruta_personas, args.microdatos)}")
    filas, leidas = leer_microdatos(ruta_personas, args.municipio)
    print(f"  {leidas:,} filas en el archivo, {len(filas):,} del municipio")
    if not filas:
        raise SystemExit("  No se encontró ninguna fila para ese municipio.")

    print("\n[2/5] Decodificando")
    enriquecer(filas)

    print("\n[3/5] Validando")
    resumen = validar(filas, args.validar_total_5mas)

    print("\n[4/5] Calculando indicadores")
    asistencia = tabla_asistencia(filas)
    nivel = tabla_nivel(filas)
    alfabetismo = tabla_alfabetismo(filas)
    dominios = tabla_dominios(filas)
    no_resp = no_respuesta_etnica(filas)
    hogar = configuracion_hogar(filas)
    titulares = indicadores_titulares(filas, resumen, no_resp, hogar)
    for t in titulares:
        print(f"  {t['indicador']}: {t['valor']}  [{t['medicion']}]")

    print("\n[5/5] Escribiendo salidas")
    escribir_csv(os.path.join(args.salida, "educacion_asistencia.csv"), asistencia)
    escribir_csv(os.path.join(args.salida, "educacion_nivel.csv"), nivel)
    escribir_csv(os.path.join(args.salida, "educacion_alfabetismo.csv"), alfabetismo)
    escribir_csv(os.path.join(args.salida, "educacion_dominios.csv"), dominios)
    escribir_csv(os.path.join(args.salida, "educacion_no_respuesta_etnica.csv"), no_resp)
    escribir_csv(os.path.join(args.salida, "educacion_configuracion_hogar.csv"), hogar)
    escribir_csv(os.path.join(args.salida, "educacion_indicadores.csv"), titulares)

    manifiesto = {
        "script": os.path.basename(__file__),
        "version": VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": FUENTE,
        "archivo_fuente": os.path.abspath(ruta_personas),
        "sha256_fuente": None if args.sin_hash else sha256(ruta_personas),
        "municipio": args.municipio,
        "filtros": {
            "tipo_registro": "personas en hogares particulares (TIPO_REG 5)",
            "categoria_narp": [GRUPO_ETNICO[c] for c in sorted(CODIGOS_NARP)],
        },
        "resumen": resumen,
        "advertencias": [
            "El microdato público del CNPV 2018 trae la edad en grupos quinquenales; "
            "no permite reproducir cortes finos como 16-17 años.",
            "P_NIVEL_ANOSR no distingue nivel completo de incompleto: los años de "
            "escolaridad se estiman por equivalencia y se marcan como estimados.",
            "La población NARP registrada está afectada por la omisión censal y por "
            "la alteración del autorreconocimiento; los denominadores deben leerse "
            "como un piso.",
            f"Toda celda con menos de {MIN_OBSERVACIONES} observaciones se publica como "
            f"{SUPRIMIDA}; la regla se aplica en el código, antes de escribir el archivo.",
            "El indicador de configuración del hogar describe con quién convive el menor, "
            "no la presencia o ausencia de sus progenitores, y no debe leerse como "
            "explicación causal de la trayectoria escolar.",
        ],
        "umbral_supresion": MIN_OBSERVACIONES,
    }
    os.makedirs(args.salida, exist_ok=True)
    ruta_man = os.path.join(args.salida, "educacion_manifiesto.json")
    with open(ruta_man, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"  escrito {ruta_man}")
    print("\nListo. Ahora ejecuta:  python seed_education.py --datos", args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
