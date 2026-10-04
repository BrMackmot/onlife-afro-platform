#!/usr/bin/env python3
# =============================================================================
# run_pipeline.py — Orquestador del pipeline de datos de OnLife Afro
# -----------------------------------------------------------------------------
# Ejecuta, en el orden correcto y con una sola instrucción, los pasos que van del
# microdato oficial a la capa de educación publicada en la plataforma:
#
#   0. ingesta  ingesta_dane.py           descarga declarada, descompresión y
#                                         normalización de las carpetas del DANE
#   1. cnpv     etl_educacion_cnpv.py     CNPV 2018, municipal (Buenaventura)
#   2. educ     etl_educacion_educ.py     EDUC 2023, sedes educativas
#   3. geih     etl_educacion_geih.py     GEIH 2020-2024, departamental y nacional
#   4. seed     seed_education.py         siembra en onlife_afro.db
#   5. figuras_geih generar_figuras_geih.py figuras estadísticas de la serie
#   6. figuras  generar_figuras*.py       figuras conceptuales del documento
#   7. verificar verificar_siembra.py     comprueba lo que app.py va a servir
#
# Cada paso se ejecuta como un subproceso independiente: si uno falla, el
# pipeline se detiene y ninguno de los siguientes toca la base de datos. Al
# terminar escribe data/pipeline_log.json con el comando exacto, el código de
# salida, la duración y el hash de cada archivo producido. Ese registro es lo que
# convierte «la cifra salió del script» en una afirmación verificable: es el
# soporte operativo del Anexo F del documento de tesis.
#
# Uso:
#   python run_pipeline.py --config pipeline.json
#   python run_pipeline.py --config pipeline.json --solo geih seed
#   python run_pipeline.py --config pipeline.json --dry-run
#
# Si no existe el archivo de configuración, --crear-config escribe una plantilla
# con las rutas que hay que completar.
# =============================================================================

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0"

PLANTILLA = {
    "python": sys.executable,
    "ingesta": {
        "_nota": ("Ponlo en false si ya descargaste y descomprimiste los "
                  "microdatos a mano: la ingesta solo sirve para descargar, "
                  "descomprimir y ordenar."),
        "activo": False,
        "catalogo": "fuentes.json",
        "raiz_microdatos": "microdatos",
        "solo": [],
    },
    "salida_datos": "data",
    "db": "onlife_afro.db",
    "valores_comunitarios": "valores_comunitarios.csv",
    "cnpv": {
        "activo": True,
        "microdatos": "../resources/76_ValleDelCauca",
        "municipio": "76109",
        "validar_total_5mas": None,
    },
    "educ": {
        "activo": True,
        "microdatos": "../resources",
        "municipio": "76109",
    },
    "geih": {
        "activo": True,
        "raiz": "../geih",
        "anios": [2020, 2021, 2022, 2023, 2024],
        "dpto": "76",
        "patron": "Caracteristicas generales",
        "meses": [],
        "dominios_archivo": "auto",
    },
    "seed": {
        "activo": True,
        "reemplazar_heredados": True,
    },
    "figuras_geih": {
        "activo": True,
        "salida_figuras": "figuras",
        "anio": None,
    },
    "verificar": {
        "activo": True,
    },
    "figuras": {
        "activo": False,
        "scripts": ["generar_figuras.py", "generar_figuras_marco.py",
                    "generar_figuras_ods_modelo.py"],
    },
}

PASOS = ["ingesta", "cnpv", "educ", "geih", "seed", "figuras_geih", "figuras",
         "verificar"]


def ruta(base, p):
    return p if os.path.isabs(p) else os.path.join(base, p)


def sha256(p, bloque=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def construir_comandos(cfg, pasos):
    py = cfg.get("python", sys.executable)
    salida = ruta(BASE_DIR, cfg.get("salida_datos", "data"))
    cmds = []
    # Si la ingesta corre en esta misma ejecución, es ella quien deja los
    # microdatos en su sitio: exigirlos antes de empezar sería pedir el
    # resultado de un paso como condición del siguiente.
    ingesta_activa = "ingesta" in pasos and cfg.get("ingesta", {}).get("activo")

    def entradas(rutas):
        return [] if ingesta_activa else rutas

    if "ingesta" in pasos and cfg.get("ingesta", {}).get("activo"):
        c = [py, ruta(BASE_DIR, "ingesta_dane.py"),
             "--catalogo", ruta(BASE_DIR, cfg["ingesta"].get("catalogo", "fuentes.json")),
             "--raiz", ruta(BASE_DIR, cfg["ingesta"].get("raiz_microdatos", "microdatos"))]
        if cfg["ingesta"].get("solo"):
            c += ["--solo"] + [str(x) for x in cfg["ingesta"]["solo"]]
        cmds.append(("ingesta", c,
                     [ruta(BASE_DIR, cfg["ingesta"].get("catalogo", "fuentes.json"))]))

    if "cnpv" in pasos and cfg["cnpv"].get("activo"):
        c = [py, ruta(BASE_DIR, "etl_educacion_cnpv.py"),
             "--microdatos", ruta(BASE_DIR, cfg["cnpv"]["microdatos"]),
             "--municipio", str(cfg["cnpv"]["municipio"]),
             "--salida", salida]
        if cfg["cnpv"].get("validar_total_5mas"):
            c += ["--validar-total-5mas", str(cfg["cnpv"]["validar_total_5mas"])]
        cmds.append(("cnpv", c, entradas([ruta(BASE_DIR, cfg["cnpv"]["microdatos"])])))

    if "educ" in pasos and cfg["educ"].get("activo"):
        c = [py, ruta(BASE_DIR, "etl_educacion_educ.py"),
             "--microdatos", ruta(BASE_DIR, cfg["educ"]["microdatos"]),
             "--municipio", str(cfg["educ"]["municipio"]),
             "--salida", salida]
        cmds.append(("educ", c, entradas([ruta(BASE_DIR, cfg["educ"]["microdatos"])])))

    if "geih" in pasos and cfg["geih"].get("activo"):
        c = [py, ruta(BASE_DIR, "etl_educacion_geih.py"),
             "--raiz", ruta(BASE_DIR, cfg["geih"]["raiz"]),
             "--anios"] + [str(a) for a in cfg["geih"]["anios"]] + [
             "--dpto", str(cfg["geih"]["dpto"]),
             "--patron", cfg["geih"].get("patron", "Caracteristicas generales"),
             "--dominios-archivo", str(cfg["geih"].get("dominios_archivo", "auto")),
             "--salida", salida]
        if cfg["geih"].get("meses"):
            c += ["--meses"] + [str(m) for m in cfg["geih"]["meses"]]
        cmds.append(("geih", c, entradas([ruta(BASE_DIR, cfg["geih"]["raiz"])])))

    if "seed" in pasos and cfg["seed"].get("activo"):
        c = [py, ruta(BASE_DIR, "seed_education.py"),
             "--datos", salida,
             "--comunitarios", ruta(BASE_DIR, cfg.get("valores_comunitarios",
                                                      "valores_comunitarios.csv")),
             "--db", ruta(BASE_DIR, cfg.get("db", "onlife_afro.db"))]
        if cfg["seed"].get("reemplazar_heredados"):
            c.append("--reemplazar-heredados")
        cmds.append(("seed", c, [salida]))

    if "figuras_geih" in pasos and cfg.get("figuras_geih", {}).get("activo"):
        c = [py, ruta(BASE_DIR, "generar_figuras_geih.py"),
             "--datos", salida,
             "--salida", ruta(BASE_DIR, cfg["figuras_geih"].get("salida_figuras", "figuras"))]
        if cfg["figuras_geih"].get("anio"):
            c += ["--anio", str(cfg["figuras_geih"]["anio"])]
        cmds.append(("figuras_geih", c, []))

    if "verificar" in pasos and cfg.get("verificar", {}).get("activo"):
        c = [py, ruta(BASE_DIR, "verificar_siembra.py"),
             "--db", ruta(BASE_DIR, cfg.get("db", "onlife_afro.db")),
             "--datos", salida]
        cmds.append(("verificar", c, []))

    if "figuras" in pasos and cfg["figuras"].get("activo"):
        for script in cfg["figuras"]["scripts"]:
            cmds.append((f"figuras:{script}", [py, ruta(BASE_DIR, script)], []))

    return cmds


def verificar_entradas(cmds):
    """Comprueba que cada insumo existe antes de ejecutar nada."""
    faltan = []
    for nombre, _, entradas in cmds:
        for e in entradas:
            if not os.path.exists(e):
                faltan.append((nombre, e))
    return faltan


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(BASE_DIR, "pipeline.json"))
    ap.add_argument("--crear-config", action="store_true",
                    help="escribe una plantilla de configuración y termina")
    ap.add_argument("--solo", nargs="+", choices=PASOS, default=PASOS,
                    help="ejecuta solo los pasos indicados, respetando el orden")
    ap.add_argument("--dry-run", action="store_true",
                    help="imprime los comandos sin ejecutarlos")
    ap.add_argument("--continuar-si-falla", action="store_true",
                    help="no se detiene ante un paso fallido (no recomendado)")
    args = ap.parse_args()

    if args.crear_config:
        with open(args.config, "w", encoding="utf-8") as f:
            json.dump(PLANTILLA, f, ensure_ascii=False, indent=2)
        print(f"Plantilla escrita en {args.config}. Completa las rutas de microdatos y vuelve a ejecutar.")
        return 0

    if not os.path.exists(args.config):
        raise SystemExit(
            f"✗ No existe {args.config}.\n"
            f"  Ejecuta primero:  python run_pipeline.py --crear-config")

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    pasos = [p for p in PASOS if p in args.solo]
    cmds = construir_comandos(cfg, pasos)
    if not cmds:
        raise SystemExit("✗ Ningún paso activo para ejecutar.")

    print(f"Pipeline OnLife Afro · versión {VERSION}")
    print(f"Pasos: {', '.join(n for n, _, _ in cmds)}\n")

    faltan = verificar_entradas(cmds)
    if faltan and not args.dry_run:
        print("✗ Faltan insumos antes de empezar:")
        for nombre, e in faltan:
            print(f"    [{nombre}] {e}")
        print("\n  Descarga los microdatos o corrige las rutas en el archivo de configuración.")
        return 1

    salida = ruta(BASE_DIR, cfg.get("salida_datos", "data"))
    os.makedirs(salida, exist_ok=True)
    registro, fallo = [], False

    for nombre, cmd, _ in cmds:
        print(f"── {nombre} " + "─" * (66 - len(nombre)))
        print("   " + " ".join(cmd))
        if args.dry_run:
            registro.append({"paso": nombre, "comando": cmd, "estado": "dry-run"})
            continue
        t0 = time.time()
        res = subprocess.run(cmd, cwd=BASE_DIR)
        dur = round(time.time() - t0, 1)
        registro.append({"paso": nombre, "comando": cmd,
                         "codigo_salida": res.returncode, "segundos": dur})
        if res.returncode != 0:
            print(f"\n✗ El paso «{nombre}» terminó con código {res.returncode}.")
            fallo = True
            if not args.continuar_si_falla:
                break
        else:
            print(f"   ✓ {nombre} en {dur} s\n")

    if args.dry_run:
        print("\n(dry-run: no se ejecutó nada)")
        return 0

    salidas = []
    for p in sorted(glob.glob(os.path.join(salida, "*.csv")) +
                    glob.glob(os.path.join(salida, "*.json"))):
        if os.path.basename(p) == "pipeline_log.json":
            continue
        salidas.append({"archivo": os.path.basename(p),
                        "bytes": os.path.getsize(p),
                        "sha256": sha256(p)})

    log = {
        "orquestador": os.path.basename(__file__),
        "version": VERSION,
        "ejecutado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "configuracion": cfg,
        "pasos": registro,
        "salidas": salidas,
        "resultado": "con errores" if fallo else "completo",
    }
    ruta_log = os.path.join(salida, "pipeline_log.json")
    with open(ruta_log, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"Registro escrito en {ruta_log}")
    print("Resultado:", log["resultado"])
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
