#!/usr/bin/env python3
# =============================================================================
# ingesta_dane.py — Paso 0 del pipeline: de la descarga del DANE a microdatos/
# -----------------------------------------------------------------------------
# QUÉ AUTOMATIZA Y QUÉ NO
#
# El portal de microdatos del DANE (microdatos.dane.gov.co) es un catálogo NADA:
# exige registro y sesión para descargar, y sus enlaces de archivo no son URL
# estables que un script pueda pedir sin autenticarse. No existe, a la fecha, una
# API pública que entregue los microdatos de la GEIH, del CNPV o de la EDUC.
#
# En consecuencia, este script automatiza todo el camino MENOS el clic:
#
#   ✗  NO descarga por sí solo del catálogo con sesión. Esa parte la hace la
#      persona, una vez, y pega los enlaces resultantes en fuentes.json.
#   ✓  SÍ descarga desde cualquier URL directa que se le declare (incluidos los
#      enlaces temporales del catálogo y los archivos de datos.gov.co).
#   ✓  SÍ verifica la integridad de lo descargado por hash SHA-256.
#   ✓  SÍ descomprime y normaliza la estructura de carpetas, que el DANE entrega
#      distinta según el año y la operación.
#   ✓  SÍ inventaría lo que quedó en disco y escribe ingesta_manifiesto.json.
#   ✓  SÍ verifica, en corridas posteriores, que nada cambió bajo los pies del
#      pipeline: si un archivo fuente se modificó, avisa antes de recalcular.
#
# Esa frontera es deliberada y conviene defenderla: un pipeline que finge
# descargar de una fuente autenticada termina descargando otra cosa —una página
# de error guardada como CSV es el caso clásico— y publica cifras falsas con
# apariencia de frescura. Aquí, si el archivo no está, el proceso se detiene y
# dice exactamente qué falta y dónde conseguirlo.
#
# Uso:
#   python ingesta_dane.py --catalogo fuentes.json --raiz microdatos/
#   python ingesta_dane.py --catalogo fuentes.json --raiz microdatos/ --solo geih
#   python ingesta_dane.py --catalogo fuentes.json --raiz microdatos/ --verificar
#   python ingesta_dane.py --crear-catalogo fuentes.json
# =============================================================================

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

VERSION = "1.0"
AGENTE = "OnLifeAfro-ingesta/1.0 (proyecto académico; contacto en el repositorio)"

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}

CATALOGO_PLANTILLA = {
    "_lectura": (
        "Cada entrada describe una fuente oficial. 'url' es opcional: si está "
        "vacía, el script no descarga y solo procesa lo que ya esté en 'local'. "
        "Los enlaces del catálogo del DANE caducan; cuando eso pase, vuelve a "
        "copiarlos desde el portal. 'sha256' es opcional pero recomendable: si "
        "está, la descarga se verifica contra él."
    ),
    "fuentes": [
        {
            "clave": "cnpv",
            "nombre": "CNPV 2018 — microdatos de personas, Valle del Cauca",
            "portal": "https://microdatos.dane.gov.co/index.php/catalog/643",
            "url": "",
            "local": "descargas/CNPV2018_5PER_A2_76.zip",
            "sha256": "",
            "destino": "CNPV2018",
            "estructura": "plana",
            "patron_archivo": "5PER"
        },
        {
            "clave": "educ",
            "nombre": "Educación Formal EDUC 2023",
            "portal": "https://microdatos.dane.gov.co/index.php/catalog/799",
            "url": "",
            "local": "descargas/EDUC_2023.zip",
            "sha256": "",
            "destino": "EDUC2023",
            "estructura": "plana",
            "patron_archivo": ""
        },
        {
            "clave": "geih",
            "nombre": "GEIH 2020-2024 — microdatos mensuales",
            "portal": "https://microdatos.dane.gov.co/index.php/catalog/MERCLAB-Microdatos",
            "url": "",
            "local": "descargas/GEIH",
            "sha256": "",
            "destino": "GEIH",
            "estructura": "anio_mes",
            "patron_archivo": "Caracteristicas generales"
        }
    ]
}


# =============================================================================
# Utilidades
# =============================================================================
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def sha256(ruta, bloque=1 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def humano(n):
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidad}"
        n /= 1024
    return f"{n:.1f} TB"


def inferir_anio_mes(texto):
    """Deduce año y mes del nombre de archivo o de carpeta que usa el DANE."""
    t = norm(texto)
    anio = None
    m = re.search(r"(20[12]\d)", t)
    if m:
        anio = m.group(1)
    mes = None
    for nombre, num in MESES.items():
        if norm(nombre) in t:
            mes = num
            break
    if mes is None:
        m = re.search(r"(?:^|[^0-9])(0[1-9]|1[0-2])(?:[^0-9]|$)", t.replace(anio or "", ""))
        if m:
            mes = m.group(1)
    return anio, mes


# =============================================================================
# Descarga
# =============================================================================
def descargar(url, destino, esperado=None, forzar=False):
    """Descarga con verificación. Nunca deja un archivo a medias en su sitio."""
    if os.path.exists(destino) and not forzar:
        if esperado:
            actual = sha256(destino)
            if actual == esperado:
                print(f"    ya estaba y el hash coincide: {os.path.basename(destino)}")
                return destino, "existente"
            print(f"    ✗ {os.path.basename(destino)} existe pero su hash no coincide.")
            print(f"      esperado {esperado[:16]}…  encontrado {actual[:16]}…")
            print(f"      usa --forzar-descarga si quieres reemplazarlo.")
            return None, "hash_no_coincide"
        print(f"    ya estaba: {os.path.basename(destino)} (sin hash declarado)")
        return destino, "existente"

    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    parcial = destino + ".part"
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(peticion, timeout=120) as r, open(parcial, "wb") as f:
            tipo = (r.headers.get("Content-Type") or "").lower()
            if "text/html" in tipo:
                raise SystemExit(
                    f"\n✗ {url}\n  devolvió una página HTML, no un archivo de datos.\n"
                    f"  Es lo que ocurre cuando el enlace del catálogo del DANE caducó o\n"
                    f"  exige sesión. Vuelve al portal, descarga a mano y apunta 'local'.\n")
            copiado = 0
            while True:
                trozo = r.read(1 << 20)
                if not trozo:
                    break
                f.write(trozo)
                copiado += len(trozo)
                print(f"\r    descargando… {humano(copiado)}", end="", file=sys.stderr)
    except urllib.error.URLError as e:
        if os.path.exists(parcial):
            os.remove(parcial)
        print(f"\n    ✗ no se pudo descargar {url}: {e}")
        return None, "error_red"
    print()

    if esperado:
        obtenido = sha256(parcial)
        if obtenido != esperado:
            os.remove(parcial)
            print(f"    ✗ el hash de la descarga no coincide con el declarado; se descarta.")
            return None, "hash_no_coincide"
    shutil.move(parcial, destino)
    print(f"    descargado {os.path.basename(destino)} ({humano(os.path.getsize(destino))})")
    return destino, "descargado"


# =============================================================================
# Descompresión y normalización
# =============================================================================
def extraer_zip(ruta_zip, carpeta_tmp):
    with zipfile.ZipFile(ruta_zip) as z:
        nombres = [n for n in z.namelist() if not n.endswith("/")]
        z.extractall(carpeta_tmp)
    return [os.path.join(carpeta_tmp, n) for n in nombres]


def recolectar(origen):
    """Devuelve todos los archivos bajo una ruta, sea archivo, ZIP o carpeta."""
    if os.path.isfile(origen) and origen.lower().endswith(".zip"):
        tmp = origen + ".extraido"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp, exist_ok=True)
        return extraer_zip(origen, tmp), tmp
    if os.path.isfile(origen):
        return [origen], None
    archivos = []
    for raiz, _, nombres in os.walk(origen):
        for n in nombres:
            archivos.append(os.path.join(raiz, n))
    # los ZIP internos también se abren: la GEIH viene como un ZIP por mes
    salida, temporales = [], []
    for a in archivos:
        if a.lower().endswith(".zip"):
            tmp = a + ".extraido"
            if os.path.isdir(tmp):
                shutil.rmtree(tmp)
            os.makedirs(tmp, exist_ok=True)
            salida.extend(extraer_zip(a, tmp))
            temporales.append(tmp)
        else:
            salida.append(a)
    return salida, temporales


def normalizar(fuente, archivos, raiz_destino):
    """Coloca cada archivo donde el ETL correspondiente sabe buscarlo.

    · estructura «plana»    → <raiz>/<destino>/<archivo>
    · estructura «anio_mes» → <raiz>/<destino>/<AAAA>/<MM>/<archivo>

    La segunda es la que necesita el ETL de la GEIH, que infiere el año de la
    ruta. El DANE entrega esos archivos con nombres de carpeta que cambian entre
    entregas —«Enero», «2023_01», «GEIH enero 2023»—, de modo que el año y el mes
    se deducen del nombre y no de una convención supuesta.
    """
    patron = norm(fuente.get("patron_archivo", ""))
    destino_base = os.path.join(raiz_destino, fuente["destino"])
    colocados, sin_ubicar = [], []
    for a in archivos:
        nombre = os.path.basename(a)
        if nombre.startswith("."):
            continue
        if patron and patron not in norm(nombre) and patron not in norm(a):
            continue
        if fuente.get("estructura") == "anio_mes":
            anio, mes = inferir_anio_mes(a)
            if not anio:
                sin_ubicar.append(a)
                continue
            destino = os.path.join(destino_base, anio, mes or "00", nombre)
        else:
            destino = os.path.join(destino_base, nombre)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if os.path.abspath(a) != os.path.abspath(destino):
            shutil.copy2(a, destino)
        colocados.append(destino)
    return colocados, sin_ubicar


# =============================================================================
# Inventario
# =============================================================================
def inventariar(rutas, con_hash=True):
    filas = []
    for r in sorted(set(rutas)):
        if not os.path.isfile(r):
            continue
        filas.append({
            "archivo": os.path.relpath(r),
            "bytes": os.path.getsize(r),
            "modificado": datetime.fromtimestamp(
                os.path.getmtime(r), timezone.utc).isoformat(timespec="seconds"),
            "sha256": sha256(r) if con_hash else None,
        })
    return filas


def verificar(manifiesto):
    """Compara el disco con el último inventario. Detecta cambios silenciosos."""
    problemas = []
    for fuente in manifiesto.get("fuentes", []):
        for f in fuente.get("archivos", []):
            ruta = f["archivo"]
            if not os.path.exists(ruta):
                problemas.append((fuente["clave"], ruta, "falta"))
                continue
            if f.get("sha256") and sha256(ruta) != f["sha256"]:
                problemas.append((fuente["clave"], ruta, "cambió desde la última ingesta"))
    return problemas


# =============================================================================
# Programa
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogo", default="fuentes.json")
    ap.add_argument("--raiz", default="microdatos",
                    help="carpeta donde quedan los microdatos listos para los ETL")
    ap.add_argument("--solo", nargs="+", default=None,
                    help="claves de fuente a procesar (cnpv, educ, geih)")
    ap.add_argument("--crear-catalogo", metavar="RUTA", default=None,
                    help="escribe una plantilla de fuentes.json y termina")
    ap.add_argument("--verificar", action="store_true",
                    help="no ingiere: comprueba que lo ya ingerido sigue intacto")
    ap.add_argument("--forzar-descarga", action="store_true")
    ap.add_argument("--sin-hash", action="store_true",
                    help="omite el hash del inventario (más rápido, menos trazable)")
    args = ap.parse_args()

    if args.crear_catalogo:
        with open(args.crear_catalogo, "w", encoding="utf-8") as f:
            json.dump(CATALOGO_PLANTILLA, f, ensure_ascii=False, indent=2)
        print(f"Plantilla escrita en {args.crear_catalogo}.")
        print("Descarga los archivos del portal del DANE y completa 'local' o 'url'.")
        return 0

    ruta_manifiesto = os.path.join(args.raiz, "ingesta_manifiesto.json")

    if args.verificar:
        if not os.path.exists(ruta_manifiesto):
            raise SystemExit(f"✗ No existe {ruta_manifiesto}; no hay nada que verificar.")
        with open(ruta_manifiesto, encoding="utf-8") as f:
            manifiesto = json.load(f)
        problemas = verificar(manifiesto)
        if not problemas:
            print(f"✓ Los {sum(len(x['archivos']) for x in manifiesto['fuentes'])} archivos "
                  f"del último inventario siguen intactos.")
            return 0
        print("✗ Diferencias frente al último inventario:")
        for clave, ruta, motivo in problemas:
            print(f"    [{clave}] {ruta} — {motivo}")
        print("\n  Vuelve a ejecutar la ingesta y después el pipeline: las cifras "
              "publicadas ya no corresponden a estos archivos.")
        return 1

    if not os.path.exists(args.catalogo):
        raise SystemExit(
            f"✗ No existe {args.catalogo}.\n"
            f"  Ejecuta:  python ingesta_dane.py --crear-catalogo {args.catalogo}")

    with open(args.catalogo, encoding="utf-8") as f:
        catalogo = json.load(f)

    fuentes = [x for x in catalogo["fuentes"]
               if not args.solo or x["clave"] in args.solo]
    if not fuentes:
        raise SystemExit("✗ Ninguna fuente coincide con --solo.")

    print(f"Ingesta de fuentes oficiales · versión {VERSION}")
    print(f"Destino: {os.path.abspath(args.raiz)}\n")

    resumen, faltantes = [], []
    for fuente in fuentes:
        print(f"── {fuente['clave']} · {fuente['nombre']}")
        origen = fuente.get("local", "")
        estado = "local"

        if fuente.get("url"):
            destino_descarga = origen or os.path.join(
                "descargas", os.path.basename(fuente["url"].split("?")[0]))
            ruta, estado = descargar(fuente["url"], destino_descarga,
                                     fuente.get("sha256") or None,
                                     args.forzar_descarga)
            if ruta is None:
                faltantes.append((fuente["clave"], destino_descarga, estado))
                print()
                continue
            origen = ruta

        if not origen or not os.path.exists(origen):
            print(f"    ✗ no está en disco: {origen or '(sin ruta declarada)'}")
            print(f"      descárgalo del portal:  {fuente.get('portal','(sin portal)')}")
            faltantes.append((fuente["clave"], origen, "ausente"))
            print()
            continue

        archivos, temporales = recolectar(origen)
        print(f"    {len(archivos)} archivo(s) encontrados en el origen")
        colocados, sin_ubicar = normalizar(fuente, archivos, args.raiz)
        print(f"    {len(colocados)} colocado(s) en {os.path.join(args.raiz, fuente['destino'])}")
        if sin_ubicar:
            print(f"    aviso: {len(sin_ubicar)} archivo(s) sin año identificable; "
                  f"se dejaron fuera para no inventar una fecha.")
        inventario = inventariar(colocados, con_hash=not args.sin_hash)
        resumen.append({
            "clave": fuente["clave"], "nombre": fuente["nombre"],
            "portal": fuente.get("portal", ""), "origen": os.path.abspath(origen),
            "estado_descarga": estado, "archivos": inventario,
            "sin_ubicar": [os.path.basename(a) for a in sin_ubicar],
        })

        if isinstance(temporales, list):
            for t in temporales:
                shutil.rmtree(t, ignore_errors=True)
        elif temporales:
            shutil.rmtree(temporales, ignore_errors=True)
        print()

    os.makedirs(args.raiz, exist_ok=True)
    manifiesto = {
        "script": os.path.basename(__file__),
        "version": VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raiz": os.path.abspath(args.raiz),
        "fuentes": resumen,
        "faltantes": [{"clave": c, "ruta": r, "motivo": m} for c, r, m in faltantes],
        "nota": ("El portal de microdatos del DANE exige sesión para descargar: los "
                 "archivos sin URL directa se obtienen a mano y se declaran en "
                 "'local'. Este manifiesto registra qué había en disco y con qué hash "
                 "en el momento de la ingesta."),
    }
    with open(ruta_manifiesto, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"Inventario escrito en {ruta_manifiesto}")

    total = sum(len(r["archivos"]) for r in resumen)
    print(f"Fuentes ingeridas: {len(resumen)}   archivos disponibles: {total}")
    if faltantes:
        print("\nFaltan por conseguir:")
        for c, r, m in faltantes:
            print(f"    [{c}] {r or '(sin ruta)'} — {m}")
        return 1
    print("\nListo. Ahora ejecuta:  python run_pipeline.py --config pipeline.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
