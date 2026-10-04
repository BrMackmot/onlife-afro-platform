# =============================================================
# dane_auto.py — Actualización periódica de cifras oficiales para OnLife Afro
# =============================================================
# Qué hace
#   1. Mensual: descarga el anexo de mercado laboral de la GEIH que publica el
#      DANE (anex-GEIH-<mes><año>.xlsx), busca la tasa de desocupación de las
#      ciudades de la plataforma y deja cada valor PENDIENTE de aprobación.
#   2. Anual: consulta la API de datos abiertos del Ministerio de Educación
#      (cobertura neta en media por municipio) y vigila si el DANE publicó un
#      nuevo boletín anual de pobreza, conectividad o mercado laboral
#      departamental. Lo nuevo queda pendiente o como aviso.
#
# Qué NO hace
#   · No publica nada por sí mismo: solo la administración (CAEDI) aprueba.
#   · No inventa datos: si el anexo no trae una ciudad, esa celda queda vacía.
#   · No borra meses: archiva todo; la plataforma muestra los cinco más recientes.
#
# Uso en PythonAnywhere (tarea programada diaria; ver la guía de instalación):
#   python3 /home/<usuario>/<carpeta>/dane_auto.py
#   python3 dane_auto.py --solo-mensual | --solo-anual | --estado
#
# Solo usa la biblioteca estándar y openpyxl (ya instalado en PythonAnywhere).
# =============================================================

import os, sys, re, json, sqlite3, hashlib, logging, argparse
import urllib.request, urllib.error
from datetime import datetime, date

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.environ.get("ONLIFE_DB_PATH", os.path.join(BASE_DIR, "onlife_afro.db"))
DATA_FOLDER = os.path.join(BASE_DIR, "data")
ARCHIVO_DIR = os.path.join(DATA_FOLDER, "dane_auto")          # copias de los anexos descargados
STAMP_PATH  = os.path.join(DATA_FOLDER, "dane_aprobados.stamp")  # avisa a la app que hay aprobaciones nuevas

VENTANA_MESES = 5          # meses que muestra la plataforma
MAX_BYTES     = 30 * 1024 * 1024
TIMEOUT       = 60
USER_AGENT    = "OnLifeAfro/5.0 (+https://onlifeafro.org; actualizacion de cifras oficiales)"

logger = logging.getLogger("dane_auto")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

URL_ANEXO = "https://www.dane.gov.co/files/operaciones/GEIH/anex-GEIH-{mes}{anio}.xlsx"
URL_PAGINA_GEIH = "https://www.dane.gov.co/index.php/estadisticas-por-tema/mercado-laboral/empleo-y-desempleo"

# Ciudad del anexo que corresponde a cada territorio de la plataforma.
# Francisco Pizarro (clave «pacificosur») no es una ciudad de la GEIH y no se busca.
CIUDADES = {
    "buenaventura": {"nombres": ["buenaventura"], "ambito": "Buenaventura (ciudad)"},
    "tumaco":       {"nombres": ["tumaco"], "ambito": "Tumaco (ciudad)"},
    "choco":        {"nombres": ["quibdo", "quibdó"], "ambito": "Quibdó (ciudad)"},
    "sanandres":    {"nombres": ["san andres", "san andrés"], "ambito": "San Andrés (ciudad)"},
    "cartagena":    {"nombres": ["cartagena"], "ambito": "Cartagena (ciudad)"},
    "cali":         {"nombres": ["cali"], "ambito": "Cali (área metropolitana)"},
}

# Municipio (código DANE) de cada territorio para la API del MEN.
MUNICIPIOS_MEN = {
    "buenaventura": ("76109", "Buenaventura (municipio)"),
    "tumaco":       ("52835", "Tumaco (municipio)"),
    "choco":        ("27001", "Quibdó (municipio)"),
    "sanandres":    ("88001", "San Andrés (municipio)"),
    "cartagena":    ("13001", "Cartagena (municipio)"),
    "cali":         ("76001", "Cali (municipio)"),
    "pacificosur":  ("52520", "Francisco Pizarro (municipio)"),
}
URL_MEN = ("https://www.datos.gov.co/resource/nudc-7mev.json"
           "?c_digo_municipio={codigo}&$order=a_o%20DESC&$limit=1"
           "&$select=a_o,municipio,cobertura_neta_media")
URL_MEN_FICHA = "https://www.datos.gov.co/Educaci-n/MEN_ESTADISTICAS_EN_EDUCACION_EN_PREESCOLAR-B-SICA/nudc-7mev"

# Boletines anuales del DANE que solo se vigilan (no se leen: son PDF).
PUBLICACIONES_ANUALES = [
    {"clave": "pobreza_departamental", "campo": "poverty",
     "nombre": "Pobreza monetaria departamental",
     "url": "https://www.dane.gov.co/files/operaciones/PM/pres-PMDepartamental-{anio}.pdf"},
    {"clave": "entic_hogares", "campo": "connectivity",
     "nombre": "Tenencia y uso de TIC en hogares (ENTIC)",
     "url": "https://www.dane.gov.co/files/operaciones/ENTIC/bol-ENTICHogares-{anio}.pdf"},
    {"clave": "geih_departamentos", "campo": "unemployment",
     "nombre": "Mercado laboral por departamentos (anual)",
     "url": "https://www.dane.gov.co/files/operaciones/GEIH/bol-GEIHDepartamentos-{anio}.pdf"},
]

# ── Base de datos ─────────────────────────────────────────────

ESQUEMA = """
CREATE TABLE IF NOT EXISTS dane_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- 'mensual' | 'anual' | 'aviso'
    territory TEXT, field TEXT NOT NULL,
    period TEXT NOT NULL,               -- 'AAAA-MM' (mensual) o 'AAAA' (anual)
    period_label TEXT DEFAULT '',       -- texto de la columna en el archivo original
    value REAL,                         -- NULL en los avisos
    source_label TEXT DEFAULT '', source_url TEXT DEFAULT '', ambito TEXT DEFAULT '',
    sheet TEXT DEFAULT '', file_sha256 TEXT DEFAULT '',
    warning TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | aprobado | rechazado | atendido
    fetched_at TEXT NOT NULL,
    reviewed_by TEXT DEFAULT '', reviewed_at TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dane_staging_unico
    ON dane_staging(kind, COALESCE(territory,''), field, period);
CREATE TABLE IF NOT EXISTS dane_aprobados (
    territory TEXT NOT NULL, field TEXT NOT NULL, kind TEXT NOT NULL,
    period TEXT NOT NULL, period_label TEXT DEFAULT '',
    value REAL NOT NULL, source_label TEXT DEFAULT '', source_url TEXT DEFAULT '',
    ambito TEXT DEFAULT '', file_sha256 TEXT DEFAULT '',
    approved_by TEXT DEFAULT '', approved_at TEXT NOT NULL, staging_id INTEGER,
    PRIMARY KEY (territory, field, kind, period)
);
CREATE TABLE IF NOT EXISTS dane_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL, tarea TEXT NOT NULL, estado TEXT NOT NULL, mensaje TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dane_estado (
    clave TEXT PRIMARY KEY, valor TEXT
);
"""


def conectar(db_path=None):
    con = sqlite3.connect(db_path or DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def registrar(con, tarea, estado, mensaje=""):
    con.execute("INSERT INTO dane_log (run_at, tarea, estado, mensaje) VALUES (?,?,?,?)",
                (_ahora(), tarea, estado, mensaje[:2000]))
    con.commit()
    (logger.warning if estado in ("error", "aviso") else logger.info)(f"[{tarea}] {estado}: {mensaje}")


def _estado_get(con, clave, defecto=None):
    r = con.execute("SELECT valor FROM dane_estado WHERE clave=?", (clave,)).fetchone()
    return r["valor"] if r else defecto


def _estado_set(con, clave, valor):
    con.execute("INSERT OR REPLACE INTO dane_estado (clave, valor) VALUES (?,?)", (clave, str(valor)))
    con.commit()


# ── Red ───────────────────────────────────────────────────────
# urllib respeta las variables de proxy del entorno (http_proxy/https_proxy),
# que es como PythonAnywhere da salida a internet.

def _peticion(url, metodo="GET"):
    return urllib.request.Request(url, method=metodo, headers={"User-Agent": USER_AGENT})


def existe(url):
    """True si el servidor responde 200 a la dirección. Prueba HEAD y, si el
    servidor no lo admite, un GET que se corta al empezar."""
    for metodo in ("HEAD", "GET"):
        try:
            with urllib.request.urlopen(_peticion(url, metodo), timeout=TIMEOUT) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return False
            if metodo == "HEAD" and e.code in (403, 405, 501):
                continue
            raise
    return False


def descargar(url, destino):
    """Descarga con tope de tamaño. Devuelve el sha256 del archivo."""
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(_peticion(url), timeout=TIMEOUT) as r, open(destino, "wb") as f:
        while True:
            trozo = r.read(1024 * 256)
            if not trozo:
                break
            total += len(trozo)
            if total > MAX_BYTES:
                raise ValueError(f"el archivo supera {MAX_BYTES // (1024 * 1024)} MB")
            h.update(trozo)
            f.write(trozo)
    return h.hexdigest()


def leer_json(url):
    with urllib.request.urlopen(_peticion(url), timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ── Lectura del anexo de la GEIH ──────────────────────────────

def _norm(t):
    t = str(t or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


_RE_TD = re.compile(r"^(td\b|t\.?d\.?\b|tasa de desocupacion|tasa de desempleo)")
_RE_CONCEPTO = re.compile(r"^(t[a-z]{1,2}\b|tasa|poblacion|ocupados|desocupados|fuerza|inactivos|%)")


def _es_numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ciudad_de(texto):
    """Territorio cuyo nombre de ciudad aparece en el texto de una celda."""
    t = _norm(texto)
    if not t or len(t) > 60:
        return None
    for ter, d in CIUDADES.items():
        for n in d["nombres"]:
            n = _norm(n)
            # «cali» no debe coincidir con «calidad»: se exige palabra completa.
            if re.search(rf"(^|[^a-z]){re.escape(n)}([^a-z]|$)", t):
                return ter
    return None


def _prioridad_hoja(nombre, ter):
    """Para Buenaventura y Tumaco se prefieren las hojas de ciudades intermedias;
    para el resto, las de 23 o 32 ciudades. Las hojas desestacionalizadas o de
    población (miles de personas) quedan al final."""
    n = _norm(nombre)
    p = 0
    if ter in ("buenaventura", "tumaco", "choco", "sanandres") and "intermed" in n:
        p += 30
    if re.search(r"\b(23|32)\b", n) or "ciudad" in n:
        p += 20
    if "td" in n or "desocup" in n or "tasa" in n:
        p += 10
    if "desest" in n or "miles" in n or "poblacion" in n:
        p -= 40
    return p


def _encabezado_columna(filas_previas, col):
    """Texto del encabezado más cercano por encima en esa columna (para que la
    persona que aprueba vea qué periodo dice el propio archivo)."""
    for fila in reversed(filas_previas):
        if col < len(fila):
            v = fila[col]
            if v is not None and not _es_numero(v) and str(v).strip():
                return str(v).strip()[:80]
            if isinstance(v, (datetime, date)):
                return v.strftime("%Y-%m")
    return ""


def leer_anexo(ruta):
    """Devuelve {territorio: {valor, hoja, periodo_texto}} con la tasa de
    desocupación más reciente (última columna con número) de cada ciudad.

    Reconoce dos disposiciones habituales de los anexos del DANE:
      A. Bloques por ciudad: una fila con el nombre de la ciudad y debajo los
         conceptos (TGP, TO, TD...).
      B. Tabla de un solo concepto: una hoja o sección de tasa de desocupación
         con una fila por ciudad.
      C. Tabla de un solo concepto con una columna por ciudad y una fila por
         periodo: se toma la última fila con números.
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("falta openpyxl (pip install --user openpyxl)")
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    candidatos = {}   # ter -> lista de (prioridad, valor, hoja, periodo)
    try:
        for ws in wb.worksheets:
            hoja = ws.title
            filas = []
            ciudad_actual = None
            seccion_td = bool(re.search(r"desocup|\btd\b", _norm(hoja)))
            columnas = {}          # disposición C: columna -> territorio
            ultima_c = None        # (fila, td_activa) con números bajo ese encabezado

            def cerrar_c():
                if columnas and ultima_c and ultima_c[1]:
                    fila_c = ultima_c[0]
                    etiqueta = next((str(v).strip()[:80] for v in fila_c if isinstance(v, str) and v.strip()), "")
                    if not etiqueta:
                        etiqueta = next((v.strftime("%Y-%m") for v in fila_c if isinstance(v, (datetime, date))), "")
                    for col, ter_c in columnas.items():
                        if col < len(fila_c) and _es_numero(fila_c[col]):
                            candidatos.setdefault(ter_c, []).append(
                                (_prioridad_hoja(hoja, ter_c) + 3, float(fila_c[col]), hoja, etiqueta))

            for fila in ws.iter_rows(values_only=True):
                fila = list(fila)
                textos = [(i, v) for i, v in enumerate(fila) if isinstance(v, str) and v.strip()]
                numeros = [(i, v) for i, v in enumerate(fila) if _es_numero(v)]
                primero = textos[0][1] if textos else ""
                n_primero = _norm(primero)
                if textos and re.search(r"tasa de desocupacion|tasa de desempleo", n_primero) and not numeros:
                    seccion_td = True          # título de sección dentro de la hoja
                elif textos and not numeros and _RE_CONCEPTO.match(n_primero) and not _RE_TD.match(n_primero):
                    if len(textos) == 1 and "tasa" in n_primero:
                        seccion_td = False     # empieza la sección de otro concepto
                cols_ciudad = {i: _ciudad_de(v) for i, v in textos}
                cols_ciudad = {i: t for i, t in cols_ciudad.items() if t}
                if len(cols_ciudad) >= 2 and not numeros:
                    cerrar_c()                     # disposición C: fila de encabezado
                    columnas, ultima_c = cols_ciudad, None
                    filas.append(fila)
                    continue
                if columnas and numeros and seccion_td:
                    ultima_c = (fila, True)
                ter = _ciudad_de(primero) if textos else None
                if ter and not numeros:
                    ciudad_actual = ter            # disposición A: encabezado de bloque
                elif ter and numeros and seccion_td:
                    col, val = numeros[-1]         # disposición B: fila de la ciudad
                    candidatos.setdefault(ter, []).append(
                        (_prioridad_hoja(hoja, ter) + 5, float(val), hoja, _encabezado_columna(filas, col)))
                elif ciudad_actual and textos and numeros and _RE_TD.match(n_primero):
                    col, val = numeros[-1]
                    candidatos.setdefault(ciudad_actual, []).append(
                        (_prioridad_hoja(hoja, ciudad_actual), float(val), hoja, _encabezado_columna(filas, col)))
                    ciudad_actual = None
                filas.append(fila)
                if len(filas) > 40:
                    filas.pop(0)
            cerrar_c()
    finally:
        wb.close()
    resultado = {}
    for ter, lista in candidatos.items():
        lista.sort(key=lambda x: -x[0])
        p, val, hoja, periodo = lista[0]
        resultado[ter] = {"valor": round(val, 2), "hoja": hoja, "periodo_texto": periodo}
    return resultado


# ── Tarea mensual: tasa de desocupación por ciudad ────────────

def _meses_candidatos(hoy=None, atras=4):
    hoy = hoy or date.today()
    a, m = hoy.year, hoy.month
    for _ in range(atras):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        yield a, m


def _ultimo_aprobado(con, ter, field="unemployment"):
    r = con.execute("SELECT value, period FROM dane_aprobados WHERE territory=? AND field=? AND kind='mensual' "
                    "ORDER BY period DESC LIMIT 1", (ter, field)).fetchone()
    return (r["value"], r["period"]) if r else (None, None)


def _guardar_pendiente(con, **d):
    try:
        con.execute("""INSERT INTO dane_staging (kind, territory, field, period, period_label, value,
                       source_label, source_url, ambito, sheet, file_sha256, warning, status, fetched_at)
                       VALUES (:kind,:territory,:field,:period,:period_label,:value,:source_label,
                               :source_url,:ambito,:sheet,:file_sha256,:warning,'pendiente',:fetched_at)""",
                    {"period_label": "", "value": None, "source_label": "", "source_url": "", "ambito": "",
                     "sheet": "", "file_sha256": "", "warning": "", "territory": None,
                     "fetched_at": _ahora(), **d})
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False     # ya estaba registrado (pendiente, aprobado o rechazado)


def tarea_mensual(con, hoy=None, descargar_fn=None, existe_fn=None):
    descargar_fn = descargar_fn or descargar
    existe_fn = existe_fn or existe
    os.makedirs(ARCHIVO_DIR, exist_ok=True)
    for anio, mes in _meses_candidatos(hoy):
        periodo = f"{anio}-{mes:02d}"
        ya = con.execute("SELECT COUNT(*) FROM dane_staging WHERE kind='mensual' AND period=?", (periodo,)).fetchone()[0]
        if ya:
            registrar(con, "mensual", "ok", f"El anexo de {MESES_LARGOS[mes-1]} de {anio} ya se procesó; no hay nada nuevo.")
            return 0
        url = URL_ANEXO.format(mes=MESES[mes - 1], anio=anio)
        try:
            if not existe_fn(url):
                continue
        except Exception as e:
            registrar(con, "mensual", "error", f"No se pudo consultar {url}: {e}")
            return 0
        destino = os.path.join(ARCHIVO_DIR, os.path.basename(url))
        try:
            sha = descargar_fn(url, destino)
            datos = leer_anexo(destino)
        except Exception as e:
            registrar(con, "mensual", "error", f"Anexo de {MESES_LARGOS[mes-1]} de {anio}: {e}. No se cargó nada.")
            return 0
        if not datos:
            registrar(con, "mensual", "error",
                      f"El anexo de {MESES_LARGOS[mes-1]} de {anio} se descargó, pero no se encontró la tasa de "
                      f"desocupación de ninguna ciudad. Puede que el DANE haya cambiado la estructura del archivo.")
            return 0
        nuevos, faltan = 0, []
        for ter, info in CIUDADES.items():
            d = datos.get(ter)
            if not d:
                faltan.append(info["ambito"])
                continue
            aviso = []
            if not (0 < d["valor"] < 60):
                aviso.append("valor fuera del rango esperado (0–60 %)")
            previo, p_periodo = _ultimo_aprobado(con, ter)
            if previo is not None and abs(d["valor"] - previo) > 8:
                aviso.append(f"cambio de {d['valor'] - previo:+.1f} puntos frente a {p_periodo}")
            ok = _guardar_pendiente(
                con, kind="mensual", territory=ter, field="unemployment", period=periodo,
                period_label=d["periodo_texto"] or f"anexo de {MESES_LARGOS[mes-1]} de {anio}",
                value=d["valor"], source_label=f"DANE — GEIH, anexo de mercado laboral ({MESES_LARGOS[mes-1]} de {anio})",
                source_url=url, ambito=info["ambito"], sheet=d["hoja"], file_sha256=sha,
                warning="; ".join(aviso))
            nuevos += int(ok)
        msg = f"Anexo de {MESES_LARGOS[mes-1]} de {anio}: {nuevos} cifra(s) pendiente(s) de aprobación."
        if faltan:
            msg += f" Sin dato en el anexo (las celdas quedan vacías): {', '.join(faltan)}."
        registrar(con, "mensual", "ok", msg)
        return nuevos
    registrar(con, "mensual", "ok", "Todavía no hay un anexo nuevo publicado.")
    return 0


# ── Tarea anual: MEN (con valor) y boletines del DANE (aviso) ─

def tarea_anual(con, leer_json_fn=None, existe_fn=None, anio_actual=None):
    leer_json_fn = leer_json_fn or leer_json
    existe_fn = existe_fn or existe
    anio_actual = anio_actual or date.today().year
    nuevos = 0
    # 1. Cobertura neta en media (MEN, datos abiertos), por municipio.
    for ter, (codigo, ambito) in MUNICIPIOS_MEN.items():
        try:
            filas = leer_json_fn(URL_MEN.format(codigo=codigo))
        except Exception as e:
            registrar(con, "anual", "error", f"API del MEN ({ambito}): {e}")
            continue
        if not filas:
            continue
        f = filas[0]
        try:
            anio = str(int(f.get("a_o")))
            valor = float(f.get("cobertura_neta_media"))
        except (TypeError, ValueError):
            registrar(con, "aviso", "aviso", f"La API del MEN devolvió un registro sin año o sin cobertura neta en media para {ambito}.")
            continue
        aviso = "" if 0 <= valor <= 120 else "valor fuera del rango esperado (0–120 %)"
        if _guardar_pendiente(con, kind="anual", territory=ter, field="edu_media", period=anio,
                              period_label=f"año {anio}", value=round(valor, 2),
                              source_label="MEN — Estadísticas de educación por municipio (SIMAT y proyecciones DANE)",
                              source_url=URL_MEN_FICHA, ambito=ambito, warning=aviso):
            nuevos += 1
    # 2. Boletines anuales del DANE: solo se avisa que existen.
    for pub in PUBLICACIONES_ANUALES:
        clave = "ultimo_" + pub["clave"]
        ultimo = int(_estado_get(con, clave, anio_actual - 2))
        siguiente = ultimo + 1
        if siguiente > anio_actual:
            continue
        url = pub["url"].format(anio=siguiente)
        try:
            hay = existe_fn(url)
        except Exception as e:
            registrar(con, "anual", "error", f"{pub['nombre']}: no se pudo consultar ({e}).")
            continue
        if hay:
            _estado_set(con, clave, siguiente)
            if _guardar_pendiente(con, kind="aviso", territory=None, field=pub["campo"], period=str(siguiente),
                                  period_label=pub["nombre"], source_label=f"DANE — {pub['nombre']} {siguiente}",
                                  source_url=url,
                                  warning="Publicación nueva. Procesarla con el procedimiento local (Anexo F) "
                                          "y subir el archivo de indicadores."):
                nuevos += 1
    registrar(con, "anual", "ok", f"{nuevos} novedad(es) anual(es) registrada(s).")
    return nuevos


# ── Revisión (la usa la aplicación desde la página de administración) ─

def tocar_stamp():
    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(STAMP_PATH, "w") as f:
        f.write(_ahora())


def aprobar(con, staging_id, usuario):
    s = con.execute("SELECT * FROM dane_staging WHERE id=?", (staging_id,)).fetchone()
    if not s:
        return False, "No existe esa cifra."
    if s["status"] != "pendiente":
        return False, "Esa cifra ya fue revisada."
    ahora = _ahora()
    if s["kind"] == "aviso":
        con.execute("UPDATE dane_staging SET status='atendido', reviewed_by=?, reviewed_at=? WHERE id=?",
                    (usuario, ahora, staging_id))
        con.commit()
        return True, "Aviso marcado como atendido."
    con.execute("""INSERT OR REPLACE INTO dane_aprobados (territory, field, kind, period, period_label, value,
                   source_label, source_url, ambito, file_sha256, approved_by, approved_at, staging_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s["territory"], s["field"], s["kind"], s["period"], s["period_label"], s["value"],
                 s["source_label"], s["source_url"], s["ambito"], s["file_sha256"], usuario, ahora, staging_id))
    con.execute("UPDATE dane_staging SET status='aprobado', reviewed_by=?, reviewed_at=? WHERE id=?",
                (usuario, ahora, staging_id))
    con.commit()
    tocar_stamp()
    return True, "Cifra aprobada y publicada."


def rechazar(con, staging_id, usuario, nota):
    nota = (nota or "").strip()
    if not nota:
        return False, "Escribe por qué se rechaza."
    s = con.execute("SELECT status FROM dane_staging WHERE id=?", (staging_id,)).fetchone()
    if not s:
        return False, "No existe esa cifra."
    if s["status"] != "pendiente":
        return False, "Esa cifra ya fue revisada."
    con.execute("UPDATE dane_staging SET status='rechazado', reviewed_by=?, reviewed_at=?, note=? WHERE id=?",
                (usuario, _ahora(), nota[:500], staging_id))
    con.commit()
    return True, "Cifra rechazada."


def pendientes(con):
    return [dict(r) for r in con.execute(
        "SELECT * FROM dane_staging WHERE status='pendiente' ORDER BY kind, territory, period DESC")]


def _mes_anterior(periodo, k):
    a, m = int(periodo[:4]), int(periodo[5:7])
    m -= k
    while m <= 0:
        a, m = a - 1, m + 12
    return f"{a}-{m:02d}"


def ventana(con, territory, field="unemployment", n=VENTANA_MESES):
    """Los n meses más recientes publicados por la plataforma, en orden
    cronológico. Todas las ciudades comparten la misma ventana (la del último
    anexo aprobado); un mes sin dato para esta ciudad aparece con valor None,
    nunca con el valor de otro mes."""
    r = con.execute("SELECT MAX(period) FROM dane_aprobados WHERE field=? AND kind='mensual'", (field,)).fetchone()
    ultimo = r[0] if r else None
    if not ultimo:
        return []
    periodos = [_mes_anterior(ultimo, k) for k in range(n - 1, -1, -1)]
    datos = {row["period"]: dict(row) for row in con.execute(
        "SELECT period, period_label, value, source_label, source_url, ambito, approved_at "
        "FROM dane_aprobados WHERE territory=? AND field=? AND kind='mensual' AND period>=? AND period<=?",
        (territory, field, periodos[0], periodos[-1]))}
    return [datos.get(p, {"period": p, "value": None, "period_label": "", "source_label": "",
                          "source_url": "", "ambito": "", "approved_at": ""}) for p in periodos]


def ultimo_anual(con, territory, field):
    r = con.execute("SELECT * FROM dane_aprobados WHERE territory=? AND field=? AND kind='anual' "
                    "ORDER BY period DESC LIMIT 1", (territory, field)).fetchone()
    return dict(r) if r else None


def bitacora(con, n=15):
    return [dict(r) for r in con.execute("SELECT * FROM dane_log ORDER BY id DESC LIMIT ?", (n,))]


# ── Centro de datos (OnLife Afro 2.0) ─────────────────────────
# Lo que la página de administración necesita para verificar antes de
# publicar: lotes por publicación, evidencia de cada cifra, estado del
# sistema e historial. Nada de esto publica: solo aprobar() y aprobar_lote().

NOMBRE_CAMPO = {"unemployment": "Desocupación", "edu_media": "Cobertura neta en media",
                "poverty": "Pobreza", "connectivity": "Internet en el hogar",
                "education": "Años de escolaridad", "healthcare": "Afiliación a salud"}
FUENTES_RECONOCIDAS = ("dane.gov.co", "datos.gov.co")


def periodo_humano(kind, period):
    p = str(period or "")
    if kind == "mensual" and re.match(r"^\d{4}-\d{2}$", p):
        return f"{MESES_LARGOS[int(p[5:7]) - 1]} de {p[:4]}"
    return f"año {p}" if p else ""


def _host(url):
    m = re.match(r"^https?://([^/]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def _anterior(con, s):
    """Última observación aprobada anterior a la que se revisa (misma ciudad o municipio)."""
    if not s["territory"]:
        return None
    r = con.execute("SELECT value, period FROM dane_aprobados WHERE territory=? AND field=? AND kind=? AND period<? "
                    "ORDER BY period DESC LIMIT 1", (s["territory"], s["field"], s["kind"], s["period"])).fetchone()
    return {"value": r["value"], "period": r["period"], "period_humano": periodo_humano(s["kind"], r["period"])} if r else None


def verificacion(con, s):
    """Evidencia para decidir: fuente, extracción y comparación. ok=None significa «no aplica»."""
    s = dict(s)
    host = _host(s.get("source_url"))
    reconocida = any(host == h or host.endswith("." + h) for h in FUENTES_RECONOCIDAS)
    es_api = s["kind"] == "anual" and "datos.gov.co" in host
    archivo_local = os.path.join(ARCHIVO_DIR, os.path.basename(s.get("source_url") or "")) if s.get("source_url") else ""
    fuente = [
        {"ok": reconocida, "texto": "Fuente oficial reconocida (DANE o MEN)" if reconocida else f"Fuente no reconocida: {host or 'sin enlace'}"},
        {"ok": bool(s.get("source_url")) and (es_api or s["kind"] != "mensual" or os.path.exists(archivo_local)),
         "texto": ("Consulta a la API de datos abiertos registrada" if es_api else
                   "Archivo encontrado y guardado en el servidor" if s["kind"] == "mensual" else "Publicación encontrada")},
        ({"ok": bool(s.get("file_sha256")), "texto": "Huella SHA-256 del archivo registrada"} if not es_api and s["kind"] == "mensual"
         else {"ok": None, "texto": "Huella del archivo: no aplica (dato leído de una API o aviso)"}),
    ]
    if s["kind"] == "aviso":
        extraccion = [{"ok": None, "texto": "Sin extracción automática: el boletín se lee y verifica a mano"}]
    else:
        fuera = "fuera del rango" in (s.get("warning") or "")
        extraccion = [
            {"ok": bool(s.get("territory")), "texto": f"Territorio identificado: {s.get('ambito') or s.get('territory') or '—'}"},
            {"ok": s["field"] in NOMBRE_CAMPO, "texto": f"Indicador identificado: {NOMBRE_CAMPO.get(s['field'], s['field'])}"},
            {"ok": s.get("value") is not None, "texto": "Valor numérico leído" if s.get("value") is not None else "No hay valor numérico"},
            {"ok": not fuera, "texto": "Dentro del rango esperado" if not fuera else "Fuera del rango esperado"},
        ]
        if s.get("sheet"):
            extraccion.append({"ok": True, "texto": f"Hoja del archivo: «{s['sheet']}»"})
        if s.get("period_label"):
            extraccion.append({"ok": True, "texto": f"Columna o periodo en el archivo: «{s['period_label']}»"})
    previo = _anterior(con, s) if s["kind"] != "aviso" else None
    cambio = round(s["value"] - previo["value"], 2) if (previo and s.get("value") is not None) else None
    comparacion = {"actual": {"value": s.get("value"), "period": s["period"], "period_humano": periodo_humano(s["kind"], s["period"])},
                   "anterior": previo, "cambio": cambio, "alerta": s.get("warning") or ""}
    return {"fuente": fuente, "extraccion": extraccion, "comparacion": comparacion,
            "completa": all(c["ok"] is not False for c in fuente + extraccion)}


def releases(con):
    """Pendientes agrupados por publicación: tipo, indicador, periodo y archivo."""
    grupos = {}
    for r in con.execute("SELECT * FROM dane_staging WHERE status='pendiente' ORDER BY kind, period DESC, territory"):
        r = dict(r)
        clave = (r["kind"], r["field"], r["period"], r["source_url"] if r["kind"] != "aviso" else str(r["id"]))
        g = grupos.get(clave)
        if not g:
            fuente = "MEN" if r["field"] == "edu_media" else "DANE"
            g = grupos[clave] = {
                "clave": "|".join(map(str, clave)), "kind": r["kind"], "field": r["field"],
                "indicador": NOMBRE_CAMPO.get(r["field"], r["field"]), "period": r["period"],
                "period_humano": periodo_humano(r["kind"], r["period"]),
                "titulo": (f"DANE · GEIH · {periodo_humano('mensual', r['period'])}" if r["kind"] == "mensual"
                           else f"{fuente} · {periodo_humano('anual', r['period'])}" if r["kind"] == "anual"
                           else f"Aviso · {r['period_label'] or r['source_label']}"),
                "source_label": r["source_label"], "source_url": r["source_url"], "items": [], "faltan": []}
        r["verificacion"] = verificacion(con, r)
        g["items"].append(r)
    out = list(grupos.values())
    for g in out:
        g["ids"] = [i["id"] for i in g["items"]]
        g["alertas"] = sum(1 for i in g["items"] if i.get("warning") and i["kind"] != "aviso")
        if g["kind"] == "mensual":
            presentes = {i["territory"] for i in g["items"]}
            g["faltan"] = [c["ambito"] for t, c in CIUDADES.items() if t not in presentes]
    orden = {"mensual": 0, "anual": 1, "aviso": 2}
    out.sort(key=lambda g: (orden.get(g["kind"], 3), [-ord(c) for c in g["period"]]))
    return out


def aprobar_lote(con, ids, usuario):
    hechos, errores = [], []
    for i in ids:
        ok, msg = aprobar(con, int(i), usuario)
        (hechos if ok else errores).append({"id": int(i), "mensaje": msg})
    return hechos, errores


def rechazar_lote(con, ids, usuario, nota):
    if not (nota or "").strip():
        return [], [{"id": None, "mensaje": "Escribe por qué se rechaza."}]
    hechos, errores = [], []
    for i in ids:
        ok, msg = rechazar(con, int(i), usuario, nota)
        (hechos if ok else errores).append({"id": int(i), "mensaje": msg})
    return hechos, errores


def resumen(con, hoy=None):
    """Contadores y estado del sistema para la cabecera del Centro de datos."""
    hoy = hoy or datetime.now()
    n = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    pend = n("SELECT COUNT(*) FROM dane_staging WHERE status='pendiente'")
    alert_pend = n("SELECT COUNT(*) FROM dane_staging WHERE status='pendiente' AND kind!='aviso' AND COALESCE(warning,'')!=''")
    avisos = n("SELECT COUNT(*) FROM dane_staging WHERE status='pendiente' AND kind='aviso'")
    fallos = []
    for tarea in ("mensual", "anual", "general"):
        r = con.execute("SELECT estado, mensaje, run_at FROM dane_log WHERE tarea=? ORDER BY id DESC LIMIT 1", (tarea,)).fetchone()
        if r and r["estado"] == "error":
            fallos.append({"tarea": tarea, "mensaje": r["mensaje"], "run_at": r["run_at"]})
    ultima = con.execute("SELECT MAX(run_at) FROM dane_log").fetchone()[0]
    dias = None
    if ultima:
        try:
            dias = (hoy - datetime.fromisoformat(ultima)).days
        except ValueError:
            dias = None
    if not ultima:
        sistema = {"k": "sin_ejecutar", "texto": "Todavía no se ha ejecutado"}
    elif fallos:
        sistema = {"k": "error", "texto": "Con errores en la última revisión"}
    elif dias is not None and dias > 3:
        sistema = {"k": "detenido", "texto": f"Sin revisiones desde hace {dias} días: revisa la tarea programada"}
    else:
        sistema = {"k": "ok", "texto": "Funcionando"}
    return {"pendientes": pend, "aprobados": n("SELECT COUNT(*) FROM dane_aprobados"),
            "rechazados": n("SELECT COUNT(*) FROM dane_staging WHERE status='rechazado'"),
            "alertas": alert_pend + len(fallos), "avisos": avisos, "fallos": fallos,
            "ultima_revision": ultima or "", "sistema": sistema,
            "ultimo_mes": n("SELECT COALESCE(MAX(period),'') FROM dane_aprobados WHERE kind='mensual'")}


def historial(con, n=25):
    return [dict(r) for r in con.execute(
        "SELECT id, kind, territory, field, period, value, ambito, source_label, source_url, status, "
        "reviewed_by, reviewed_at, note FROM dane_staging WHERE status IN ('aprobado','rechazado','atendido') "
        "ORDER BY reviewed_at DESC, id DESC LIMIT ?", (n,))]


def pasaporte(con, territory, field, kind=None, period=None):
    """Procedencia completa de una cifra aprobada (la más reciente si no se indica periodo)."""
    sql = ("SELECT a.*, s.sheet, s.fetched_at, s.warning FROM dane_aprobados a "
           "LEFT JOIN dane_staging s ON s.id=a.staging_id WHERE a.territory=? AND a.field=?")
    args = [territory, field]
    if kind:
        sql += " AND a.kind=?"; args.append(kind)
    if period:
        sql += " AND a.period=?"; args.append(period)
    r = con.execute(sql + " ORDER BY a.period DESC LIMIT 1", args).fetchone()
    return dict(r) if r else None


def meses_archivados(con, field="unemployment"):
    """Cuántos meses hay entre el primero y el último aprobados (para el histórico mensual)."""
    r = con.execute("SELECT MIN(period), MAX(period) FROM dane_aprobados WHERE field=? AND kind='mensual'", (field,)).fetchone()
    if not r or not r[0]:
        return 0
    a0, m0, a1, m1 = int(r[0][:4]), int(r[0][5:7]), int(r[1][:4]), int(r[1][5:7])
    return (a1 - a0) * 12 + (m1 - m0) + 1


# ── Ejecución ─────────────────────────────────────────────────

def ejecutar(solo=None, db_path=None):
    con = conectar(db_path)
    try:
        hoy = date.today()
        if solo in (None, "mensual"):
            tarea_mensual(con, hoy)
        # La consulta anual se hace una vez al mes, no todos los días.
        if solo == "anual" or (solo is None and _estado_get(con, "ultima_anual", "") != hoy.strftime("%Y-%m")):
            tarea_anual(con, anio_actual=hoy.year)
            _estado_set(con, "ultima_anual", hoy.strftime("%Y-%m"))
    except Exception as e:
        registrar(con, "general", "error", f"Fallo inesperado: {e}")
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Actualiza cifras oficiales del DANE y el MEN para OnLife Afro.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--solo-mensual", action="store_true")
    g.add_argument("--solo-anual", action="store_true")
    g.add_argument("--estado", action="store_true", help="muestra pendientes y la bitácora sin descargar nada")
    a = ap.parse_args()
    if a.estado:
        c = conectar()
        print(json.dumps({"pendientes": pendientes(c), "bitacora": bitacora(c)}, ensure_ascii=False, indent=2))
        c.close()
    else:
        ejecutar("mensual" if a.solo_mensual else "anual" if a.solo_anual else None)
