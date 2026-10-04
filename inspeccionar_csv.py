#!/usr/bin/env python3
# =============================================================================
# inspeccionar_csv.py — Qué trae un archivo antes de meterlo al pipeline
# -----------------------------------------------------------------------------
# Sirve para responder, sin abrir un archivo de cientos de megas en Excel, las
# preguntas que deciden si una fuente puede usarse y cómo:
#
#   · ¿qué codificación y qué delimitador tiene?
#   · ¿cómo se llaman sus columnas?
#   · ¿trae factor de expansión? ¿de cuál marco?
#   · ¿qué departamentos, municipios, meses o años contiene?
#   · ¿cuántas filas son?
#
# Lee por bloques y nunca carga el archivo entero en memoria.
#
# Uso:
#   python inspeccionar_csv.py --archivo "ruta/al/archivo.CSV"
#   python inspeccionar_csv.py --archivo "ruta/al/archivo.CSV" --valores DPTO MES
#   python inspeccionar_csv.py --carpeta "ruta/a/resources/Buenaventura"
# =============================================================================

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import Counter

VERSION = "1.0"

# Columnas cuyo contenido casi siempre hace falta conocer para decidir el
# universo de una fuente: territorio, período y ponderador.
INTERES = ["DPTO", "DPTOS", "AREA", "CLASE", "MPIO", "MUNICIPIO", "MES", "ANIO",
           "ANO", "PERIODO", "PERIODO_ANIO", "TRIMESTRE"]
FACTORES = ["FEX_C18", "FEX_C_2011", "FEX_C", "FEX_DPTO_2011", "FEX"]
MAX_CATEGORIAS = 15

# Variables de autorreconocimiento étnico en las distintas operaciones. Su
# presencia o ausencia decide si una fuente puede desagregarse por pertenencia
# NARP, que es la pregunta que este proyecto le hace a cada archivo.
ETNICAS = {"P6080": "GEIH — autorreconocimiento étnico",
           "PA1_GRP_ETNIC": "CNPV 2018 — pertenencia étnica",
           "GRUPOETN_ID": "EDUC — grupo étnico de la matrícula",
           "GRUPOETN_NOMBRE": "EDUC — grupo étnico (nombre)"}


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


MUESTRA_BYTES = 8 << 20   # 8 MB bastan para decidir la codificación


def detectar(ruta):
    """Codificación y delimitador, decididos sobre una muestra amplia.

    No basta con mirar la primera línea: las cabeceras del DANE son ASCII puro,
    de modo que cualquier archivo parece UTF-8 hasta que aparece la primera Ñ
    codificada en latin-1, miles de filas más abajo. Tampoco conviene leer
    entero un archivo de trescientos megabytes solo para decidir, así que se
    examina una muestra de ocho megabytes; si aun así apareciera un byte
    inválido más adelante, la lectura lo detecta y reintenta en latin-1.
    """
    with open(ruta_larga(ruta), "rb") as fb:
        muestra = fb.read(MUESTRA_BYTES)
    recorte = muestra[:-4] if len(muestra) == MUESTRA_BYTES else muestra
    encoding = "latin-1"
    try:
        recorte.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        pass
    primera = recorte.split(b"\n", 1)[0].decode(encoding, errors="replace")
    delim = ";" if primera.count(";") > primera.count(",") else ","
    return encoding, delim


def abrir(ruta, encoding=None):
    detectado, delim = detectar(ruta)
    encoding = encoding or detectado
    f = open(ruta_larga(ruta), newline="", encoding=encoding)
    return csv.DictReader(f, delimiter=delim), f, encoding, delim


def inspeccionar(ruta, columnas_extra=(), max_filas=None):
    print(f"\n── {os.path.basename(ruta)}")
    print(f"   {os.path.getsize(ruta) / 1e6:,.1f} MB")
    lector, f, encoding, delim = abrir(ruta)
    campos = lector.fieldnames or []
    print(f"   codificación {encoding} · delimitador «{delim}» · {len(campos)} columnas")

    factores = [c for c in campos if c.upper() in FACTORES]
    print(f"   factor de expansión: {', '.join(factores) if factores else 'NO HAY'}")

    etnicas = [c for c in campos if c.upper() in ETNICAS]
    if etnicas:
        print(f"   variable étnica: {', '.join(etnicas)} "
              f"({ETNICAS[etnicas[0].upper()]})")
    else:
        print("   variable étnica: NO HAY — este archivo no permite desagregar "
              "por pertenencia NARP")

    # Las columnas se imprimen ANTES de recorrer el archivo. Si la lectura
    # falla a mitad de camino, la pregunta que casi siempre importa —«¿está o
    # no está esa variable?»— ya quedó respondida.
    print("   columnas:")
    for i in range(0, len(campos), 8):
        print("      " + ", ".join(campos[i:i + 8]))

    seguir = [c for c in campos
              if c.upper() in INTERES or c.upper() in ETNICAS
              or c.upper() in [x.upper() for x in columnas_extra]]

    def recorrer(lector, f):
        conteos = {c: Counter() for c in seguir}
        filas = 0
        for fila in lector:
            filas += 1
            for c in seguir:
                conteos[c][(fila.get(c) or "").strip()] += 1
            if max_filas and filas >= max_filas:
                break
        f.close()
        return conteos, filas

    try:
        conteos, filas = recorrer(lector, f)
    except UnicodeDecodeError:
        f.close()
        print("   aviso: byte no válido en UTF-8 más allá de la muestra; "
              "se relee el archivo en latin-1")
        lector, f, encoding, delim = abrir(ruta, encoding="latin-1")
        next(iter([]), None)
        conteos, filas = recorrer(lector, f)

    print(f"   filas: {filas:,}".replace(",", "."))
    for c in seguir:
        valores = conteos[c].most_common(MAX_CATEGORIAS)
        distintos = len(conteos[c])
        muestra = ", ".join(f"{v or '(vacío)'}={n:,}".replace(",", ".") for v, n in valores)
        print(f"   {c}: {distintos} valor(es) distintos → {muestra}"
              + (" …" if distintos > MAX_CATEGORIAS else ""))
    return {"archivo": ruta, "filas": filas, "columnas": campos, "factores": factores}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", default=None)
    ap.add_argument("--carpeta", default=None,
                    help="inspecciona todos los CSV que haya debajo")
    ap.add_argument("--valores", nargs="+", default=(),
                    help="columnas adicionales cuyos valores quieres ver")
    ap.add_argument("--max-filas", type=int, default=None,
                    help="lee solo las primeras N filas (más rápido en archivos grandes)")
    args = ap.parse_args()

    if not args.archivo and not args.carpeta:
        raise SystemExit("✗ Indica --archivo o --carpeta.")

    print(f"Inspección de archivos · versión {VERSION}")
    rutas = []
    if args.archivo:
        rutas.append(args.archivo)
    if args.carpeta:
        rutas += sorted(glob.glob(os.path.join(args.carpeta, "**", "*.CSV"), recursive=True)
                        + glob.glob(os.path.join(args.carpeta, "**", "*.csv"), recursive=True))
        rutas = list(dict.fromkeys(os.path.abspath(r) for r in rutas))

    for ruta in rutas:
        if not os.path.exists(ruta):
            print(f"✗ No existe {ruta}")
            continue
        inspeccionar(ruta, args.valores, args.max_filas)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
