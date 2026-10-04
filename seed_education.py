#!/usr/bin/env python3
# =============================================================================
# seed_education.py — v3 · Capa de educación de OnLife Afro
# -----------------------------------------------------------------------------
# QUÉ CAMBIA FRENTE A LA VERSIÓN ANTERIOR
#
# La v1 insertaba en community_indicators tres filas con valores oficiales
# escritos a mano (7.4 años de escolaridad, 82.0 % de asistencia, 8.1 % de
# deserción) atribuidos a «DANE-GEIH 2020-2024», «DANE-GEIH 2024» y «DANE 2023».
# Ninguna de esas tres cifras era trazable a una publicación concreta: la de
# escolaridad venía del diccionario BASELINE de load_geih_data.py, que es un
# marcador de posición, no un dato. Publicar una cifra sin procedencia en la
# columna «oficial» es exactamente el problema que esta plataforma denuncia.
#
# La v2 no contiene ninguna cifra oficial. Lee:
# QUÉ CAMBIA EN LA v3
#
# Nada en la lógica de siembra: lo que cambia es que ahora entra una tercera
# fuente. Además de los indicadores del CNPV 2018 (censo, municipal) y de la
# EDUC 2023 (sedes educativas), el sembrador recoge educacion_indicadores_geih.csv,
# la serie 2020-2024 producida por etl_educacion_geih.py con dominios departamental
# y nacional. Tres fuentes con tres unidades de observación distintas: el script
# nunca las mezcla ni las promedia, conserva el nombre completo de cada indicador
# —que incluye su fuente y su año— y deja constancia del archivo de origen en la
# ficha de procedencia que la plataforma muestra junto a cada cifra.
#
# También detiene el proceso si dos ETL producen el mismo nombre de indicador con
# valores distintos: dos cifras con el mismo rótulo en la misma capa es el error
# que más rápido destruye la confianza en un tablero de datos.
#
#   · data/educacion_indicadores.csv  → producido por etl_educacion_cnpv.py a
#     partir de los microdatos del CNPV 2018, validado contra los cuadros
#     publicados, con universo y método por indicador.
#   · data/educacion_manifiesto.json  → procedencia (archivo, hash, filtros).
#   · valores_comunitarios.csv        → cifras de la Mesa de Educación del PCN.
#     Este archivo lo edita la organización, no el código: es el punto donde el
#     principio OCAP® de control comunitario se hace operativo.
#
# Es idempotente y además ACTUALIZA: si el ETL vuelve a correr con otra fuente,
# la fila existente se actualiza en lugar de duplicarse.
#
# Uso:
#     python etl_educacion_cnpv.py --microdatos CNPV2018_5PER_A2_76.CSV \
#         --municipio 76109 --salida data/ --validar-total-5mas 236288
#     python app.py                      # crea onlife_afro.db si no existe
#     python seed_education.py --datos data/
# =============================================================================

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Territorio por defecto para los indicadores que no declaran el suyo (censo y
# EDUC, que son municipales). La GEIH escribe su propia columna «territorio»
# porque sus dominios son departamentales y nacionales: sembrar una estimación
# departamental bajo la etiqueta de un municipio sería falsear su universo.
TERRITORIO_POR_DEFECTO = "buenaventura"
CAPA = "Educación"

# Indicadores heredados de la v1, sin fuente verificable. Se eliminan con
# --reemplazar-heredados para no dejar dos versiones del mismo dato en la base.
INDICADORES_HEREDADOS = [
    "Años de escolaridad promedio (NARP)",
    "Tasa de asistencia escolar 5-24 años (%)",
    "Deserción escolar secundaria (%)",
]

CAMPOS_COMUNITARIOS = ["indicador", "valor_comunitario", "fuente_comunitaria", "evidencia"]


def leer_csv(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cargar_entradas(carpeta_datos, ruta_comunitarios):
    # Se aceptan varias fuentes: educacion_indicadores.csv (censo de población,
    # etl_educacion_cnpv.py) y educacion_indicadores_educ.csv (censo de sedes
    # educativas, etl_educacion_educ.py). Cada indicador conserva su fuente y su
    # unidad de observación; el script nunca los mezcla ni los promedia.
    patron = os.path.join(carpeta_datos, "educacion_indicadores*.csv")
    rutas = sorted(glob.glob(patron))
    if not rutas:
        raise SystemExit(
            f"✗ No se encontró ningún archivo que coincida con {patron}.\n"
            f"  Ejecuta primero etl_educacion_cnpv.py o etl_educacion_educ.py."
        )
    oficiales = []
    por_nombre = {}
    for ruta in rutas:
        filas = leer_csv(ruta)
        print(f"  leídos {len(filas)} indicadores de {os.path.basename(ruta)}")
        for fila in filas:
            nombre = (fila.get("indicador") or "").strip()
            fila["_archivo"] = os.path.basename(ruta)
            clave = ((fila.get("territorio") or TERRITORIO_POR_DEFECTO).strip(), nombre)
            anterior = por_nombre.get(clave)
            if anterior and anterior.get("valor") != fila.get("valor"):
                raise SystemExit(
                    f"✗ El indicador «{nombre}» aparece con valores distintos en "
                    f"{anterior['_archivo']} ({anterior.get('valor')}) y en "
                    f"{fila['_archivo']} ({fila.get('valor')}).\n"
                    f"  Dos cifras con el mismo rótulo no pueden convivir en la misma "
                    f"capa: renombra el indicador en el ETL que lo produce, incluyendo "
                    f"su fuente y su año, y vuelve a ejecutarlo."
                )
            por_nombre[clave] = fila
            oficiales.append(fila)

    # Los manifiestos se recogen por patrón: cada ETL escribe el suyo y el número
    # de fuentes puede crecer sin tocar este código.
    manifiesto = {}
    for ruta_man in sorted(glob.glob(os.path.join(carpeta_datos, "*manifiesto*.json"))):
        with open(ruta_man, encoding="utf-8") as f:
            manifiesto[os.path.basename(ruta_man)] = json.load(f)
    if manifiesto:
        print(f"  procedencia leída de: {', '.join(sorted(manifiesto))}")
    else:
        print("  aviso: no se encontró ningún manifiesto de procedencia en la carpeta.")

    comunitarios = {}
    if os.path.exists(ruta_comunitarios):
        for fila in leer_csv(ruta_comunitarios):
            faltan = [c for c in CAMPOS_COMUNITARIOS if c not in fila]
            if faltan:
                raise SystemExit(
                    f"✗ {ruta_comunitarios} debe tener las columnas: "
                    f"{', '.join(CAMPOS_COMUNITARIOS)}"
                )
            comunitarios[fila["indicador"].strip()] = fila
    else:
        print(f"  aviso: no se encontró {ruta_comunitarios};"
              f" se sembrarán solo las cifras oficiales.")
    return oficiales, comunitarios, manifiesto


def a_float(valor):
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def construir_filas(oficiales, comunitarios, manifiesto):
    """Arma las filas de community_indicators con procedencia completa."""
    # Cada indicador trae su propia fuente desde el ETL que lo produjo.
    fuente_por_defecto = "DANE — operación estadística no identificada"
    filas = []
    for o in oficiales:
        nombre = o["indicador"].strip()
        territorio = (o.get("territorio") or TERRITORIO_POR_DEFECTO).strip()
        val_of = a_float(o.get("valor"))
        if val_of is None:
            print(f"  aviso: «{nombre}» sin valor calculado; se omite.")
            continue

        com = comunitarios.get(nombre)
        val_com = a_float(com["valor_comunitario"]) if com else None
        fuente_com = com["fuente_comunitaria"].strip() if com else ""
        evidencia_com = com["evidencia"].strip() if com else ""

        diferencia = round(val_com - val_of, 2) if val_com is not None else None
        # Convención de app.py: «undercount» = la comunidad describe una
        # realidad peor que la que reporta la cifra oficial.
        if diferencia is None:
            direccion = "sin_contraste"
        elif abs(diferencia) < 0.05:
            direccion = "coincide"
        elif "analfabetismo" in nombre.lower() or "deserción" in nombre.lower():
            direccion = "undercount" if diferencia > 0 else "overcount"
        else:
            direccion = "undercount" if diferencia < 0 else "overcount"

        fuente_base = (o.get("fuente") or "").strip() or fuente_por_defecto
        ficha = (
            f"Medición: {o.get('medicion','')}. "
            f"Universo: {o.get('universo','')}. "
            f"Método: {o.get('metodo','')}. "
            f"Fuente oficial: {fuente_base}. "
            f"Archivo de origen: {o.get('_archivo','(sin registrar)')}."
        )
        cuerpo = (evidencia_com + "\n\n" + ficha) if evidencia_com else ficha

        fuente_oficial = fuente_base
        if o.get("medicion") == "estimada":
            fuente_oficial += " — valor estimado, no publicado como tal por el DANE"

        filas.append((
            territorio, nombre, CAPA,
            val_of, fuente_oficial,
            val_com, fuente_com,
            diferencia, direccion,
            cuerpo, 0,
        ))
    return filas


def sembrar(db_path, filas, reemplazar_heredados):
    if not os.path.exists(db_path):
        print(f"✗ No existe {db_path}.")
        print("  Ejecuta primero  python app.py  para crear la base de datos.")
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if not cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='community_indicators'"
    ).fetchone():
        print("✗ La tabla community_indicators no existe. Inicia app.py una vez y reintenta.")
        con.close()
        return 1

    eliminados = 0
    if reemplazar_heredados:
        for viejo in INDICADORES_HEREDADOS:
            cur.execute(
                "DELETE FROM community_indicators WHERE territory=? AND indicator=?",
                (TERRITORIO_POR_DEFECTO, viejo))
            eliminados += cur.rowcount

    insertados = actualizados = 0
    for f in filas:
        existente = cur.execute(
            "SELECT id FROM community_indicators WHERE territory=? AND indicator=?",
            (f[0], f[1])).fetchone()
        if existente:
            cur.execute("""
                UPDATE community_indicators
                   SET layer=?, official_value=?, official_source=?,
                       community_value=?, community_source=?, difference=?,
                       direction=?, evidence_body=?
                 WHERE id=?
            """, (f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], existente["id"]))
            actualizados += 1
        else:
            cur.execute("""
                INSERT INTO community_indicators
                    (territory, indicator, layer, official_value, official_source,
                     community_value, community_source, difference, direction,
                     evidence_body, validated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, f)
            insertados += 1

    con.commit()
    por_territorio = cur.execute(
        "SELECT territory, COUNT(*) FROM community_indicators WHERE layer=? "
        "GROUP BY territory ORDER BY territory", (CAPA,)).fetchall()
    con.close()

    print(f"\n✓ Capa de educación sembrada desde microdatos.")
    print(f"  insertados: {insertados}   actualizados: {actualizados}"
          + (f"   heredados eliminados: {eliminados}" if reemplazar_heredados else ""))
    for fila in por_territorio:
        print(f"  total {fila[0]}/{CAPA} en la base: {fila[1]}")
    print("\n  Verifica con app.py corriendo:")
    print("    /api/indicators?territory=buenaventura&layer=Educación")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", default=os.path.join(BASE_DIR, "data"),
                    help="carpeta con la salida de etl_educacion_cnpv.py")
    ap.add_argument("--comunitarios",
                    default=os.path.join(BASE_DIR, "valores_comunitarios.csv"),
                    help="CSV con las cifras de la Mesa de Educación del PCN")
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "onlife_afro.db"))
    ap.add_argument("--reemplazar-heredados", action="store_true",
                    help="elimina las tres filas de la v1 con valores oficiales sin fuente")
    ap.add_argument("--dry-run", action="store_true",
                    help="muestra lo que se sembraría sin tocar la base de datos")
    args = ap.parse_args()

    oficiales, comunitarios, manifiesto = cargar_entradas(args.datos, args.comunitarios)
    filas = construir_filas(oficiales, comunitarios, manifiesto)

    print("Indicadores preparados:")
    for f in filas:
        com = "—" if f[5] is None else f[5]
        print(f"  · [{f[0]}] {f[1]}\n      oficial={f[3]}  comunitario={com}  "
              f"diferencia={f[7]}  ({f[8]})")

    if args.dry_run:
        print("\n(dry-run: no se escribió nada en la base de datos)")
        return 0
    return sembrar(args.db, filas, args.reemplazar_heredados)


if __name__ == "__main__":
    sys.exit(main())
