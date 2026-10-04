#!/usr/bin/env python3
# =============================================================================
# generar_figuras_geih.py — Figuras estadísticas de la serie GEIH 2020-2024
# -----------------------------------------------------------------------------
# Lee las salidas de etl_educacion_geih.py y produce las figuras del capítulo de
# resultados, en la misma paleta y tipografía que las demás figuras del documento.
# No recalcula nada: cada cifra dibujada viene de un CSV que el ETL ya escribió
# con su universo, su método y su tamaño muestral. Si el ETL no corrió, este
# script no inventa datos: se detiene.
#
# Produce, en PNG (para Word) y SVG (para reimprimir a cualquier tamaño):
#
#   figura_5_5_serie_escolaridad        línea: años de escolaridad 2020-2024 por
#                                       dominio, con banda intercuartílica
#   figura_5_6_brecha_escolaridad       barras divergentes: brecha NARP frente al
#                                       total nacional, año por año
#   figura_5_7_distribucion_escolaridad histograma ponderado con media, mediana y
#                                       cuartiles anotados
#   figura_5_8_asistencia_edad          barras agrupadas: asistencia escolar por
#                                       grupo de edad, NARP y no NARP
#   figura_5_9_nivel_educativo          barras apiladas: máximo nivel alcanzado
#   tabla_estadisticos_geih.csv         media, desviación, mediana, cuartiles,
#                                       coeficiente de variación y n por dominio
#
# Sobre lo que las figuras NO dicen: la banda intercuartílica describe cómo se
# reparten los años de escolaridad entre personas, no la precisión con que se
# estima el promedio. El microdato público de la GEIH no trae las variables de
# diseño muestral necesarias para calcular errores estándar, de modo que ninguna
# figura lleva barras de error ni intervalos de confianza. En su lugar, cada una
# declara el tamaño muestral de la celda que dibuja: es la forma honesta de que
# el lector juzgue si puede confiar en el trazo.
#
# Uso:
#   python generar_figuras_geih.py --datos data/ --salida figuras/
#   python generar_figuras_geih.py --datos data/ --salida figuras/ --anio 2023
# =============================================================================

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

VERSION = "1.0"

# Paleta del documento.
TEAL = "#3F5F6B"
TEAL_CLARO = "#8FA9B2"
BEIGE = "#F2ECE2"
DARK = "#232323"
RED = "#9C3232"
GREY = "#728A92"
VERDE = "#4A6B52"

plt.rcParams.update({
    "font.family": "DejaVu Serif",
    "axes.edgecolor": GREY,
    "axes.labelcolor": DARK,
    "text.color": DARK,
    "xtick.color": DARK,
    "ytick.color": DARK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

SUPRIMIDA = "SUPRIMIDA"


# =============================================================================
# Lectura
# =============================================================================
def leer(ruta):
    if not os.path.exists(ruta):
        return None
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    if v is None or v == "" or v == SUPRIMIDA:
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def entero(v):
    f = num(v)
    return int(f) if f is not None else None


def dominios_disponibles(filas):
    return sorted({f["dominio"] for f in filas})


def elegir_dominios(filas):
    """Identifica el dominio NARP departamental, su contraparte y el nacional."""
    doms = dominios_disponibles(filas)
    narp_dpto = next((d for d in doms if d.startswith("NARP — ")
                      and "nacional" not in d), None)
    no_narp_dpto = next((d for d in doms if d.startswith("No NARP — ")
                         and "nacional" not in d), None)
    nacional = "Total nacional" if "Total nacional" in doms else None
    narp_nacional = "NARP — nacional" if "NARP — nacional" in doms else None
    return narp_dpto, no_narp_dpto, nacional, narp_nacional


def guardar(fig, salida, nombre):
    os.makedirs(salida, exist_ok=True)
    png = os.path.join(salida, nombre + ".png")
    svg = os.path.join(salida, nombre + ".svg")
    fig.savefig(png, dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  escrito {png} y su SVG")


def pie(ax, texto, y=-0.02):
    """Nota al pie de figura: fuente, universo y advertencia de precisión."""
    ax.figure.text(0.01, y, texto, fontsize=8.2, color=GREY, style="italic",
                   ha="left", va="top", wrap=True)


# =============================================================================
# Figura 5.5 — serie de años de escolaridad
# =============================================================================
def figura_serie(serie, salida):
    narp_dpto, no_narp_dpto, nacional, narp_nacional = elegir_dominios(serie)
    anios = sorted({entero(f["anio"]) for f in serie})
    por = {(entero(f["anio"]), f["dominio"]): f for f in serie}

    fig, ax = plt.subplots(figsize=(9.2, 5.2))

    def serie_de(dom):
        xs, ys = [], []
        for a in anios:
            f = por.get((a, dom))
            v = num(f["escolaridad_promedio_25mas"]) if f else None
            if v is not None:
                xs.append(a)
                ys.append(v)
        return xs, ys

    # banda intercuartílica del dominio NARP departamental
    if narp_dpto:
        bx, p25, p75 = [], [], []
        for a in anios:
            f = por.get((a, narp_dpto))
            lo, hi = (num(f["escolaridad_p25"]), num(f["escolaridad_p75"])) if f else (None, None)
            if lo is not None and hi is not None:
                bx.append(a)
                p25.append(lo)
                p75.append(hi)
        if bx:
            ax.fill_between(bx, p25, p75, color=TEAL, alpha=0.13, linewidth=0,
                            label="Rango intercuartílico, NARP")

    usados = []

    def altura_libre(y):
        """Evita que dos etiquetas de fin de línea se pisen."""
        paso = (max(ys_todos) - min(ys_todos) or 1) * 0.06
        candidato = y
        while any(abs(candidato - u) < paso for u in usados):
            candidato += paso
        usados.append(candidato)
        return candidato

    ys_todos = [num(f["escolaridad_promedio_25mas"]) for f in serie
                if num(f["escolaridad_promedio_25mas"]) is not None] or [0, 1]

    estilos = [
        (narp_dpto, TEAL, "o", 2.4, "-"),
        (no_narp_dpto, GREY, "s", 1.6, "--"),
        (nacional, RED, "^", 1.6, "-."),
        (narp_nacional, VERDE, "D", 1.4, ":"),
    ]
    for dom, color, marca, grosor, linea in estilos:
        if not dom:
            continue
        xs, ys = serie_de(dom)
        if not xs:
            continue
        ax.plot(xs, ys, color=color, marker=marca, linewidth=grosor,
                linestyle=linea, markersize=5.5, label=dom)
        ax.annotate(f"{ys[-1]:.1f}", (xs[-1], altura_libre(ys[-1])),
                    textcoords="offset points", xytext=(9, 0), fontsize=9.5,
                    color=color, va="center")

    # marca del cambio metodológico
    if 2022 in anios:
        ax.axvline(2021.5, color=DARK, linewidth=0.8, linestyle=(0, (2, 3)), alpha=0.5)
        ax.text(2021.55, ax.get_ylim()[0], " actualización metodológica\n de la GEIH",
                fontsize=8.4, color=GREY, style="italic", va="bottom")

    ax.set_title("Años de escolaridad promedio de la población de 25 años y más",
                 fontsize=13.5, fontweight="bold", loc="left", pad=14)
    ax.set_xlabel("Año de recolección")
    ax.set_ylabel("Años de escolaridad")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", color=BEIGE, linewidth=1.1)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9.2, loc="lower left", ncol=2)

    ns = [entero(por[(a, narp_dpto)]["n_escolaridad"]) for a in anios
          if narp_dpto and (a, narp_dpto) in por and entero(por[(a, narp_dpto)]["n_escolaridad"])]
    pie(ax, "Fuente: elaboración propia con microdatos de la GEIH (DANE), estimación ponderada por factor de "
            "expansión. La banda describe la dispersión entre personas, no la precisión de la estimación: el "
            "microdato público no permite calcular errores estándar. "
            + (f"Tamaño muestral del dominio NARP: entre {min(ns):,} y {max(ns):,} observaciones por año.".replace(",", ".")
               if ns else ""))
    guardar(fig, salida, "figura_5_5_serie_escolaridad")


# =============================================================================
# Figura 5.6 — brecha frente al total nacional
# =============================================================================
def figura_brecha(serie, salida):
    narp_dpto, _, nacional, _ = elegir_dominios(serie)
    if not (narp_dpto and nacional):
        print("  aviso: faltan dominios para la figura de brecha; se omite.")
        return
    por = {(entero(f["anio"]), f["dominio"]): f for f in serie}
    anios = sorted({entero(f["anio"]) for f in serie})

    xs, ys = [], []
    for a in anios:
        v1 = num(por.get((a, narp_dpto), {}).get("escolaridad_promedio_25mas"))
        v2 = num(por.get((a, nacional), {}).get("escolaridad_promedio_25mas"))
        if v1 is None or v2 is None:
            continue
        xs.append(a)
        ys.append(round(v1 - v2, 2))
    if not xs:
        print("  aviso: sin datos para la figura de brecha; se omite.")
        return

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    colores = [RED if y < 0 else VERDE for y in ys]
    barras = ax.bar([str(x) for x in xs], ys, color=colores, width=0.58)
    for b, y in zip(barras, ys):
        ax.annotate(f"{y:+.2f}", (b.get_x() + b.get_width() / 2, y),
                    textcoords="offset points", xytext=(0, 6 if y >= 0 else -14),
                    ha="center", fontsize=10, color=DARK)
    ax.axhline(0, color=DARK, linewidth=1.1)
    ax.set_title(f"Brecha de escolaridad: {narp_dpto} frente al total nacional",
                 fontsize=13.5, fontweight="bold", loc="left", pad=14)
    ax.set_ylabel("Diferencia en años")
    ax.set_xlabel("Año de recolección")
    ax.grid(axis="y", color=BEIGE, linewidth=1.1)
    ax.set_axisbelow(True)
    margen = max(0.4, max(abs(min(ys)), abs(max(ys))) * 0.45)
    ax.set_ylim(min(ys) - margen, max(ys) + margen)
    pie(ax, "Fuente: elaboración propia con microdatos de la GEIH (DANE). Un valor negativo indica menos años de "
            "escolaridad que el promedio nacional. La diferencia no controla composición por edad ni por área.")
    guardar(fig, salida, "figura_5_6_brecha_escolaridad")


# =============================================================================
# Figura 5.7 — distribución de años de escolaridad
# =============================================================================
def figura_distribucion(dist, serie, salida, anio):
    narp_dpto, _, nacional, _ = elegir_dominios(serie)
    if not narp_dpto:
        print("  aviso: sin dominio NARP para el histograma; se omite.")
        return
    datos = defaultdict(dict)
    for f in dist:
        if entero(f["anio"]) != anio:
            continue
        v = entero(f["anios_escolaridad"])
        p = num(f["participacion_pct"])
        if v is not None and p is not None:
            datos[f["dominio"]][v] = p
    if narp_dpto not in datos:
        print("  aviso: sin distribución para el histograma; se omite.")
        return

    est = next((f for f in serie
                if entero(f["anio"]) == anio and f["dominio"] == narp_dpto), {})
    media = num(est.get("escolaridad_promedio_25mas"))
    mediana = num(est.get("escolaridad_mediana"))
    p25, p75 = num(est.get("escolaridad_p25")), num(est.get("escolaridad_p75"))
    sd = num(est.get("escolaridad_desviacion"))
    cv = num(est.get("escolaridad_coef_variacion_pct"))
    n = entero(est.get("n_escolaridad"))

    valores = sorted(set(list(datos[narp_dpto].keys())
                         + list(datos.get(nacional, {}).keys())))
    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    ax.bar(valores, [datos[narp_dpto].get(v, 0) for v in valores],
           color=TEAL, width=0.78, label=narp_dpto)
    if nacional in datos:
        ax.step([v - 0.5 for v in valores] + [valores[-1] + 0.5],
                [datos[nacional].get(v, 0) for v in valores] + [datos[nacional].get(valores[-1], 0)],
                where="post", color=RED, linewidth=1.6, label=nacional)

    tope = ax.get_ylim()[1]
    if p25 is not None and p75 is not None:
        ax.axvspan(p25, p75, color=TEAL, alpha=0.10, linewidth=0)
        ax.text((p25 + p75) / 2, tope * 0.97, "50 % central",
                ha="center", va="top", fontsize=8.6, color=GREY, style="italic")
    for valor, etiqueta, color, estilo, lado, alto in (
            (media, "media", DARK, "-", "right", 0.86),
            (mediana, "mediana", VERDE, "--", "left", 0.76)):
        if valor is None:
            continue
        ax.axvline(valor, color=color, linewidth=1.5, linestyle=estilo)
        margen = 0.25 if lado == "left" else -0.25
        ax.text(valor + margen, tope * alto, f"{etiqueta} {valor:.1f}",
                fontsize=9.2, color=color, va="top", ha=lado)

    resumen = []
    if media is not None:
        resumen.append(f"media {media:.2f}")
    if sd is not None:
        resumen.append(f"desviación {sd:.2f}")
    if mediana is not None:
        resumen.append(f"mediana {mediana:.0f}")
    if p25 is not None and p75 is not None:
        resumen.append(f"cuartiles {p25:.0f}–{p75:.0f}")
    if cv is not None:
        resumen.append(f"CV {cv:.0f} %")
    if n:
        resumen.append(f"n = {n:,}".replace(",", "."))
    if resumen:
        ax.text(0.985, 0.96, "\n".join(resumen), transform=ax.transAxes,
                ha="right", va="top", fontsize=9.4, color=DARK,
                bbox=dict(boxstyle="round,pad=0.55", facecolor=BEIGE,
                          edgecolor=TEAL, linewidth=0.9))

    ax.set_title(f"Distribución de los años de escolaridad, población de 25 años y más ({anio})",
                 fontsize=13.5, fontweight="bold", loc="left", pad=14)
    ax.set_xlabel("Años de escolaridad acumulados")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel("Participación en la población (%)")
    ax.grid(axis="y", color=BEIGE, linewidth=1.1)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9.2, loc="upper left")
    pie(ax, "Fuente: elaboración propia con microdatos de la GEIH (DANE), ponderado por factor de expansión. Los "
            "años de escolaridad se derivan del nivel alcanzado y del último grado aprobado; son una estimación y "
            "no una medición directa. La desviación describe la dispersión entre personas, no el error de muestreo.")
    guardar(fig, salida, "figura_5_7_distribucion_escolaridad")


# =============================================================================
# Figura 5.8 — asistencia por grupo de edad
# =============================================================================
ORDEN_EDAD = ["5-9", "10-14", "15-19", "20-24"]


def figura_asistencia(asistencia, salida, anio):
    if not asistencia:
        print("  aviso: sin tabla de asistencia; se omite la figura.")
        return
    doms = sorted({f["dominio"] for f in asistencia})
    narp = next((d for d in doms if d.startswith("NARP — ") and "nacional" not in d), None)
    no_narp = next((d for d in doms if d.startswith("No NARP — ") and "nacional" not in d), None)
    if not narp:
        print("  aviso: sin dominio NARP en asistencia; se omite la figura.")
        return

    def agrupar(dom):
        # Se recomponen los totales sumando sexos, con la población expandida
        # como ponderador: promediar porcentajes daría un resultado distinto.
        acumulado = defaultdict(lambda: [0.0, 0.0, 0])
        for f in asistencia:
            if entero(f["anio"]) != anio or f["dominio"] != dom:
                continue
            ge = f["grupo_edad"]
            tasa, w = num(f["tasa_asistencia_pct"]), num(f["poblacion_expandida"])
            n = entero(f["n_muestral"]) or 0
            if tasa is None or w is None:
                continue
            acumulado[ge][0] += tasa * w
            acumulado[ge][1] += w
            acumulado[ge][2] += n
        return {ge: (v[0] / v[1] if v[1] else None, v[2]) for ge, v in acumulado.items()}

    a1, a2 = agrupar(narp), agrupar(no_narp) if no_narp else {}
    edades = [e for e in ORDEN_EDAD if e in a1]
    if not edades:
        print("  aviso: sin grupos de edad para asistencia; se omite.")
        return

    fig, ax = plt.subplots(figsize=(8.8, 4.9))
    ancho = 0.36
    pos = range(len(edades))
    v1 = [a1[e][0] or 0 for e in edades]
    b1 = ax.bar([p - ancho / 2 for p in pos], v1, ancho, color=TEAL, label=narp)
    if a2:
        v2 = [(a2.get(e, (0, 0))[0] or 0) for e in edades]
        b2 = ax.bar([p + ancho / 2 for p in pos], v2, ancho, color=TEAL_CLARO, label=no_narp)
        for b, v in zip(b2, v2):
            ax.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v),
                        textcoords="offset points", xytext=(0, 4), ha="center",
                        fontsize=9, color=GREY)
    for b, v, e in zip(b1, v1, edades):
        ax.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v),
                    textcoords="offset points", xytext=(0, 4), ha="center",
                    fontsize=9.4, color=DARK)
        ax.annotate(f"n={a1[e][1]:,}".replace(",", "."),
                    (b.get_x() + b.get_width() / 2, 2), ha="center",
                    fontsize=7.8, color="white")

    ax.set_xticks(list(pos))
    ax.set_xticklabels([f"{e} años" for e in edades])
    ax.set_ylim(0, 116)
    ax.set_title(f"Asistencia escolar por grupo de edad ({anio})",
                 fontsize=13.5, fontweight="bold", loc="left", pad=14)
    ax.set_ylabel("Asiste a una institución educativa (%)")
    ax.grid(axis="y", color=BEIGE, linewidth=1.1)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9.2, loc="upper right", ncol=2)
    pie(ax, "Fuente: elaboración propia con microdatos de la GEIH (DANE). Los totales por grupo de edad se "
            "recomponen ponderando por población expandida y no promediando porcentajes. La no respuesta se "
            "excluye del denominador.")
    guardar(fig, salida, "figura_5_8_asistencia_edad")


# =============================================================================
# Figura 5.9 — nivel educativo alcanzado
# =============================================================================
ORDEN_NIVEL = ["Ninguno", "Preescolar", "Básica primaria", "Básica secundaria",
               "Media", "Superior o universitaria", "No sabe, no informa"]
COLORES_NIVEL = ["#C9C4BC", "#B7C6CB", TEAL_CLARO, TEAL, VERDE, "#2E4A54", "#E4DED4"]


def figura_nivel(nivel, salida, anio):
    if not nivel:
        print("  aviso: sin tabla de nivel educativo; se omite la figura.")
        return
    doms = sorted({f["dominio"] for f in nivel})
    orden_dom = [d for d in doms if d.startswith("NARP — ") and "nacional" not in d] + \
                [d for d in doms if d.startswith("No NARP — ") and "nacional" not in d] + \
                [d for d in doms if d == "NARP — nacional"] + \
                [d for d in doms if d == "Total nacional"]
    orden_dom = [d for d in orden_dom if d]
    datos = defaultdict(dict)
    for f in nivel:
        if entero(f["anio"]) != anio:
            continue
        p = num(f["participacion_pct"])
        if p is not None:
            datos[f["dominio"]][f["nivel_educativo"]] = p
    orden_dom = [d for d in orden_dom if d in datos]
    if not orden_dom:
        print("  aviso: sin datos de nivel para ese año; se omite.")
        return

    fig, ax = plt.subplots(figsize=(9.6, 0.85 * len(orden_dom) + 2.6))
    izquierda = [0.0] * len(orden_dom)
    for etiqueta, color in zip(ORDEN_NIVEL, COLORES_NIVEL):
        vals = [datos[d].get(etiqueta, 0) for d in orden_dom]
        if not any(vals):
            continue
        ax.barh(orden_dom, vals, left=izquierda, color=color, label=etiqueta,
                height=0.6, edgecolor="white", linewidth=0.8)
        for i, (v, izq) in enumerate(zip(vals, izquierda)):
            if v >= 6:
                ax.text(izq + v / 2, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=8.8, color="white" if color in (TEAL, VERDE, "#2E4A54") else DARK)
        izquierda = [a + b for a, b in zip(izquierda, vals)]

    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.set_title(f"Máximo nivel educativo alcanzado, población de 25 años y más ({anio})",
                 fontsize=13.5, fontweight="bold", loc="left", pad=14)
    ax.set_xlabel("Participación en la población (%)")
    ax.grid(axis="x", color=BEIGE, linewidth=1.1)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8.8, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, -0.18))
    pie(ax, "Fuente: elaboración propia con microdatos de la GEIH (DANE), ponderado por factor de expansión.",
        y=-0.20)
    guardar(fig, salida, "figura_5_9_nivel_educativo")


# =============================================================================
# Tabla de estadísticos
# =============================================================================
def tabla_estadisticos(serie, salida):
    campos = ["anio", "dominio", "escolaridad_promedio_25mas", "escolaridad_desviacion",
              "escolaridad_mediana", "escolaridad_p25", "escolaridad_p75",
              "escolaridad_coef_variacion_pct", "n_escolaridad",
              "poblacion_expandida_25mas"]
    encabezados = ["Año", "Dominio", "Media", "Desviación", "Mediana", "P25", "P75",
                   "CV (%)", "n muestral", "Población expandida"]
    ruta = os.path.join(salida, "tabla_estadisticos_geih.csv")
    os.makedirs(salida, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(encabezados)
        for fila in serie:
            w.writerow([fila.get(c, "") for c in campos])
    print(f"  escrito {ruta}  ({len(serie)} filas)")


# =============================================================================
# Programa
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", default="data", help="carpeta con las salidas del ETL")
    ap.add_argument("--salida", default="figuras")
    ap.add_argument("--anio", type=int, default=None,
                    help="año para las figuras de corte transversal (por defecto, el último)")
    args = ap.parse_args()

    serie = leer(os.path.join(args.datos, "educacion_geih_serie_anual.csv"))
    if not serie:
        raise SystemExit(
            f"✗ No se encontró educacion_geih_serie_anual.csv en {args.datos}.\n"
            f"  Ejecuta primero etl_educacion_geih.py: este script no calcula, solo dibuja.")
    dist = leer(os.path.join(args.datos, "educacion_geih_distribucion_escolaridad.csv")) or []
    asistencia = leer(os.path.join(args.datos, "educacion_geih_asistencia.csv")) or []
    nivel = leer(os.path.join(args.datos, "educacion_geih_nivel.csv")) or []

    anios = sorted({entero(f["anio"]) for f in serie if entero(f["anio"])})
    anio = args.anio or (anios[-1] if anios else None)
    if anio is None:
        raise SystemExit("✗ La serie no tiene años legibles.")

    print(f"Figuras de la serie GEIH · versión {VERSION}")
    print(f"Años en la serie: {', '.join(str(a) for a in anios)} · corte transversal: {anio}\n")

    figura_serie(serie, args.salida)
    figura_brecha(serie, args.salida)
    figura_distribucion(dist, serie, args.salida, anio)
    figura_asistencia(asistencia, args.salida, anio)
    figura_nivel(nivel, args.salida, anio)
    tabla_estadisticos(serie, args.salida)

    print("\nListo. Inserta los PNG en el capítulo 5 y conserva los SVG para reimprimir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
