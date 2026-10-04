#!/usr/bin/env python3
# =============================================================================
# convertir_dta_a_csv.py — De los .DTA del DANE al CSV que leen los ETL
# -----------------------------------------------------------------------------
# El Archivo Nacional de Datos entrega varias operaciones en formato Stata (.DTA)
# además de en CSV. El archivo de personas del CNPV 2018 del Valle, por ejemplo,
# pesa alrededor de 1,5 GB en .DTA. Los ETL de este proyecto leen CSV con el
# módulo estándar de Python, sin pandas, para no exigir dependencias pesadas en
# el servidor donde corre la plataforma; este conversor es el único punto del
# pipeline que necesita pandas, y se ejecuta una sola vez por archivo.
#
# Qué hace:
#   · lee el .DTA por bloques, de modo que un archivo de 1,5 GB no tiene que
#     caber en memoria;
#   · se queda solo con las columnas que el ETL usa —el resto se descarta antes
#     de escribir, lo que reduce el CSV resultante en un orden de magnitud—;
#   · conserva los códigos originales como texto, sin convertirlos a número:
#     «05» es un departamento y no el número cinco, y perder el cero inicial
#     rompe el filtro por municipio;
#   · escribe el hash y el conteo de filas para que la conversión quede
#     registrada y no haya que confiar en la memoria de quien la hizo.
#
# Uso:
#   python convertir_dta_a_csv.py --entrada CNPV2018_5PER_A2_76.DTA \
#       --salida microdatos/CNPV2018_5PER_A2_76.CSV --perfil cnpv-personas
#   python convertir_dta_a_csv.py --entrada archivo.DTA --salida salida.CSV \
#       --columnas TODAS          # conversión completa, más lenta y más pesada
#   python convertir_dta_a_csv.py --entrada archivo.DTA --listar-columnas
# =============================================================================

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

VERSION = "1.0"

# Columnas que necesita cada ETL. Mantener esta tabla junto al conversor evita
# que alguien convierta un archivo de 1,5 GB para descubrir después que le falta
# una variable.
PERFILES = {
    "cnpv-personas": [
        "U_DPTO", "U_MPIO", "UA_CLASE", "P_SEXO", "P_EDADR", "P_PARENTESCOR",
        "PA1_GRP_ETNIC", "P_ALFABETA", "PA_ASISTENCIA", "P_NIVEL_ANOSR",
    ],
    "cnpv-viviendas": [
        "U_DPTO", "U_MPIO", "UA_CLASE", "V_TOT_HOG", "VA1_ESTRATO",
        "V_MAT_PARED", "V_MAT_PISO",
    ],
    "geih-personas": [
        "DIRECTORIO", "SECUENCIA_P", "ORDEN", "MES", "DPTO", "CLASE", "AREA",
        "P6020", "P6040", "P6080", "P6160", "P6170", "P6210", "P6210S1",
        "FEX_C18", "FEX_C_2011",
    ],
}


def sha256(ruta, bloque=1 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def normalizar(valor):
    """Devuelve el código tal como estaba, sin perder ceros a la izquierda."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        # Stata guarda los códigos como float cuando la columna es numérica;
        # 5.0 debe volver a ser «5», no «5.0», y NaN debe ser vacío.
        if valor != valor:  # NaN
            return ""
        if valor.is_integer():
            return str(int(valor))
        return repr(valor)
    return str(valor).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", required=True, help="archivo .DTA de origen")
    ap.add_argument("--salida", default=None, help="archivo .CSV de destino")
    ap.add_argument("--perfil", choices=sorted(PERFILES), default=None,
                    help="conjunto de columnas que necesita el ETL de destino")
    ap.add_argument("--columnas", nargs="+", default=None,
                    help="lista explícita de columnas, o TODAS para no filtrar")
    ap.add_argument("--listar-columnas", action="store_true",
                    help="muestra las columnas del .DTA y termina")
    ap.add_argument("--bloque", type=int, default=200_000,
                    help="filas por bloque de lectura (baja este número si falta memoria)")
    ap.add_argument("--sin-hash", action="store_true")
    args = ap.parse_args()

    try:
        import pandas as pd
    except ImportError:
        raise SystemExit(
            "✗ Este conversor necesita pandas. Instálalo con:\n"
            "    pip install pandas\n"
            "  Es la única parte del pipeline que lo requiere; los ETL no.")

    if not os.path.exists(args.entrada):
        raise SystemExit(f"✗ No existe {args.entrada}.")

    print(f"Conversor .DTA → .CSV · versión {VERSION}")
    print(f"Entrada: {args.entrada} ({os.path.getsize(args.entrada) / 1e6:,.0f} MB)")

    # El nombre del atributo con la lista de variables ha cambiado entre
    # versiones de pandas; se resuelve por lo que exista, y como último recurso
    # se leen las primeras filas para quedarse con los encabezados.
    disponibles = None
    with pd.io.stata.StataReader(args.entrada) as lector:
        for atributo in ("varlist", "_varlist"):
            if hasattr(lector, atributo):
                disponibles = list(getattr(lector, atributo))
                break
        if disponibles is None and hasattr(lector, "variable_labels"):
            disponibles = list(lector.variable_labels().keys())
    if not disponibles:
        disponibles = list(pd.read_stata(args.entrada, convert_categoricals=False,
                                         chunksize=1).read(1).columns)
    if args.listar_columnas:
        print(f"\n{len(disponibles)} columnas:")
        for c in disponibles:
            print("   ", c)
        return 0

    if args.columnas and args.columnas != ["TODAS"]:
        pedidas = args.columnas
    elif args.columnas == ["TODAS"]:
        pedidas = disponibles
    elif args.perfil:
        pedidas = PERFILES[args.perfil]
    else:
        raise SystemExit("✗ Indica --perfil o --columnas (o --columnas TODAS).")

    faltan = [c for c in pedidas if c not in disponibles]
    usadas = [c for c in pedidas if c in disponibles]
    if faltan:
        print(f"  aviso: no están en el archivo y se omiten: {', '.join(faltan)}")
    if not usadas:
        raise SystemExit("✗ Ninguna de las columnas pedidas existe en el archivo.\n"
                         "  Ejecuta con --listar-columnas para ver los nombres reales.")
    print(f"  se convierten {len(usadas)} de {len(disponibles)} columnas")

    salida = args.salida or os.path.splitext(args.entrada)[0] + ".CSV"
    os.makedirs(os.path.dirname(salida) or ".", exist_ok=True)
    parcial = salida + ".part"

    filas = 0
    with open(parcial, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(usadas)
        with pd.read_stata(args.entrada, columns=usadas, chunksize=args.bloque,
                           convert_categoricals=False) as bloques:
            for bloque in bloques:
                for registro in bloque.itertuples(index=False, name=None):
                    escritor.writerow([normalizar(v) for v in registro])
                filas += len(bloque)
                print(f"\r  {filas:,} filas convertidas".replace(",", "."),
                      end="", file=sys.stderr)
    print(file=sys.stderr)
    os.replace(parcial, salida)

    registro = {
        "script": os.path.basename(__file__),
        "version": VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entrada": os.path.abspath(args.entrada),
        "salida": os.path.abspath(salida),
        "perfil": args.perfil,
        "columnas_convertidas": usadas,
        "columnas_omitidas": faltan,
        "filas": filas,
        "sha256_entrada": None if args.sin_hash else sha256(args.entrada),
        "sha256_salida": None if args.sin_hash else sha256(salida),
        "nota": ("Los códigos se conservan como texto para no perder ceros a la "
                 "izquierda; convertirlos a número rompería el filtro por "
                 "departamento y municipio."),
    }
    ruta_reg = os.path.splitext(salida)[0] + "_conversion.json"
    with open(ruta_reg, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {filas:,} filas escritas en {salida}".replace(",", "."))
    print(f"  registro de conversión en {ruta_reg}")
    print(f"  tamaño: {os.path.getsize(salida) / 1e6:,.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
