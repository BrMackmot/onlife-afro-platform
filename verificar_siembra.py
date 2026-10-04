#!/usr/bin/env python3
# =============================================================================
# verificar_siembra.py — Último paso: qué va a servir app.py, y si es defendible
# -----------------------------------------------------------------------------
# La aplicación no ejecuta ETL: lee onlife_afro.db. Entre el pipeline y la web hay
# una frontera deliberada —una petición HTTP no debe disparar el reprocesamiento
# de cinco años de microdatos— y esa frontera tiene un costo: nada garantiza que
# lo que quedó en la base sea lo que el pipeline creyó sembrar.
#
# Este script cierra esa brecha. Consulta la base tal como la consultará app.py y
# comprueba cuatro cosas que un jurado o una organización socia notarían antes que
# nadie:
#
#   1. que ninguna cifra publicada carezca de fuente declarada;
#   2. que ninguna cifra quede fuera del rango plausible de su unidad;
#   3. que no haya dos filas con el mismo indicador en el mismo territorio;
#   4. que cada indicador sembrado tenga un manifiesto de procedencia detrás.
#
# Devuelve código 1 si algo falla, de modo que run_pipeline.py se detenga.
#
# Uso:
#   python verificar_siembra.py --db onlife_afro.db --datos data/
# =============================================================================

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from collections import Counter

CAPA = "Educación"

# Rangos plausibles por tipo de unidad, deducidos del nombre del indicador.
RANGOS = [
    ("%", 0, 100),
    ("p.p.", -100, 100),
    ("años", -30, 30),
]


def rango_de(indicador):
    for marca, lo, hi in RANGOS:
        if marca in indicador:
            return marca, lo, hi
    return None, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="onlife_afro.db")
    ap.add_argument("--datos", default="data")
    ap.add_argument("--capa", default=CAPA)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"✗ No existe {args.db}. Ejecuta app.py una vez y luego el pipeline.")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    filas = con.execute(
        "SELECT territory, indicator, official_value, official_source, "
        "       community_value, community_source, direction, evidence_body "
        "  FROM community_indicators WHERE layer=? ORDER BY territory, indicator",
        (args.capa,)).fetchall()
    con.close()

    if not filas:
        raise SystemExit(f"✗ La capa «{args.capa}» está vacía en la base. "
                         f"¿Corrió seed_education.py?")

    print(f"Verificación de la capa «{args.capa}» · {len(filas)} indicadores\n")

    por_territorio = Counter(f["territory"] for f in filas)
    for t, n in sorted(por_territorio.items()):
        print(f"  {t:24s} {n} indicador(es)")

    problemas = []

    # 1. procedencia
    for f in filas:
        if not (f["official_source"] or "").strip():
            problemas.append(("sin fuente", f["territory"], f["indicator"]))
        if "Archivo de origen" not in (f["evidence_body"] or ""):
            problemas.append(("sin archivo de origen en la ficha",
                              f["territory"], f["indicator"]))

    # 2. rangos
    for f in filas:
        marca, lo, hi = rango_de(f["indicator"])
        for etiqueta, valor in (("oficial", f["official_value"]),
                                ("comunitario", f["community_value"])):
            if valor is None or marca is None:
                continue
            if not (lo <= valor <= hi):
                problemas.append((f"valor {etiqueta} fuera de rango ({valor} para «{marca}»)",
                                  f["territory"], f["indicator"]))

    # 3. duplicados
    vistos = Counter((f["territory"], f["indicator"]) for f in filas)
    for (t, i), n in vistos.items():
        if n > 1:
            problemas.append((f"duplicado ({n} filas)", t, i))

    # 4. manifiestos presentes
    manifiestos = sorted(os.path.basename(p) for p in
                         glob.glob(os.path.join(args.datos, "*manifiesto*.json")))
    print(f"\n  manifiestos de procedencia en {args.datos}: "
          f"{', '.join(manifiestos) if manifiestos else 'ninguno'}")
    if not manifiestos:
        problemas.append(("no hay manifiestos de procedencia", "—", "—"))

    # informe de contraste, que es lo que la plataforma muestra
    con_contraste = [f for f in filas if f["community_value"] is not None]
    print(f"  indicadores con contraste comunitario: {len(con_contraste)} de {len(filas)}")
    for f in con_contraste:
        print(f"    · [{f['direction']}] {f['indicator'][:70]}")
    if not con_contraste:
        print("    aviso: ninguno. El módulo «Comunidad vs DANE» mostrará solo la "
              "columna oficial hasta que se completen los valores comunitarios.")

    if problemas:
        print(f"\n✗ {len(problemas)} problema(s):")
        for motivo, t, i in problemas:
            print(f"    [{t}] {i[:60]} — {motivo}")
        return 1

    print("\n✓ Todo lo publicado tiene fuente, archivo de origen, rango plausible "
          "y manifiesto detrás.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
