"""Pruebas de regresión de OnLife Afro 2.0 (matriz de la guía, sección 15).

Uso, desde la carpeta de la aplicación (donde están app.py y dane_auto.py):
    python3 tests/test_onlife_2_0.py

No toca la base de datos real: copia app.py y dane_auto.py a una carpeta
temporal, crea allí una base nueva y simula los anexos del DANE.
"""
import os, sys, shutil, tempfile, unittest, importlib.util, sqlite3
from datetime import date

ORIGEN = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="onlife_test_")
for f in ("app.py", "dane_auto.py"):
    shutil.copy(os.path.join(ORIGEN, f), TMP)
os.chdir(TMP)
sys.path.insert(0, TMP)
os.environ["SECRET_KEY"] = "prueba"
os.environ.pop("ONLIFE_DB_PATH", None)

spec = importlib.util.spec_from_file_location("onlife_app", os.path.join(TMP, "app.py"))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
import dane_auto as D

CIUDADES = {"Buenaventura": 23.4, "Tumaco": 25.9, "Quibdó": 26.8, "San Andrés": 13.1, "Cartagena": 10.5, "Cali A.M.": 8.9}


def anexo(ruta, td):
    """Anexo simulado con la estructura de ciudades intermedias (bloque por ciudad)."""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Ciudades intermedias"
    ws.append(["Gran Encuesta Integrada de Hogares - GEIH"])
    ws.append(["Concepto", "Periodo anterior", "Periodo actual"])
    for ciudad, v in td.items():
        ws.append([ciudad]); ws.append(["TGP", 60, 61]); ws.append(["TO", 45, 46]); ws.append(["TD", v - 0.5, v])
    wb.save(ruta)


def pagina_completa(c):
    """La portada más sus recursos separados (/assets/app.<huella>.css y .js)."""
    import re as _re
    html = c.get("/").get_data(as_text=True)
    for ruta in _re.findall(r'(?:href|src)="(/assets/app\.[0-9a-f]+\.(?:css|js))"', html):
        html += c.get(ruta).get_data(as_text=True)
    return html


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = A.app.test_client()
        db = sqlite3.connect(A.DB_PATH)
        cls.admin_id = db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()[0]
        db.close()

    def como_admin(self):
        with self.c.session_transaction() as s:
            s["user_id"] = self.admin_id
            s["csrf_token"] = "tok"
        return {"X-CSRF-Token": "tok"}

    def salir(self):
        with self.c.session_transaction() as s:
            s.clear()

    def publicar_meses(self, meses, quitar=None, aprobar=True):
        """Simula la publicación del DANE de los meses dados (2026) y su revisión."""
        pub = {}
        for i, mm in enumerate(meses):
            url = D.URL_ANEXO.format(mes=D.MESES[mm - 1], anio=2026)
            ruta = os.path.join(TMP, f"anexo{mm}.xlsx")
            v = {k: round(x + 0.2 * i, 1) for k, x in CIUDADES.items()}
            if quitar and mm in quitar:
                for k in quitar[mm]:
                    v.pop(k)
            anexo(ruta, v); pub[url] = ruta
        dl = lambda u, d: (shutil.copy(pub[u], d), "sha-" + os.path.basename(u))[1]
        con = D.conectar(A.DB_PATH)
        try:
            for mm in meses:
                D.tarea_mensual(con, hoy=date(2026, mm + 1, 3), descargar_fn=dl, existe_fn=lambda u: u in pub)
                if aprobar:
                    for s in D.pendientes(con):
                        if s["kind"] == "mensual" and s["period"] == f"2026-{mm:02d}":
                            D.aprobar(con, s["id"], "prueba")
        finally:
            con.close()
        A.load_official_indicators()


class T1_Confianza(Base):
    def test_01_sin_lineas_base_manuales(self):
        """Valor actual ausente → «Sin dato»; las cifras escritas a mano no son públicas."""
        A.load_official_indicators()
        t = A.TERRITORIES["pacificosur"]
        self.assertIsNone(t["unemployment"])
        self.assertEqual(t["unemployment_estado"], "sin_dato")
        r = self.c.get("/api/datos/estado?territory=pacificosur&field=unemployment").get_json()
        self.assertEqual(r["dato"]["status"], "sin_dato")
        self.assertIsNone(r["dato"]["value"])
        self.assertEqual(r["dato"]["source_status"], "sin_dato")

    def test_03_francisco_pizarro(self):
        """El territorio antes rotulado «Pacífico Sur» se llama Francisco Pizarro (Nariño)."""
        t = A.TERRITORIES["pacificosur"]
        self.assertEqual(t["name"], "Francisco Pizarro")
        self.assertEqual(D.MUNICIPIOS_MEN["pacificosur"][0], "52520")
        html = pagina_completa(self.c)
        self.assertNotIn("'Pacífico Sur'", html)
        self.assertNotIn("Tumaco, Pacífico Sur", html)

    def test_02_referencia_rotulada(self):
        """Una cifra de la tesis que llena una celda vacía se rotula como referencia."""
        d = self.c.get("/api/datos/estado?territory=buenaventura&field=connectivity").get_json()["dato"]
        self.assertEqual(d["status"], "referencia")
        self.assertEqual(str(d["period"]), "2018")


class T2_Flujo(Base):
    def test_01_publicacion_nueva_queda_pendiente(self):
        """Nuevo anexo del DANE → pendiente; nada público todavía."""
        self.publicar_meses([4], aprobar=False)
        con = D.conectar(A.DB_PATH)
        n = len([p for p in D.pendientes(con) if p["period"] == "2026-04"])
        con.close()
        self.assertEqual(n, 6)
        self.assertIsNone(A.TERRITORIES["buenaventura"]["unemployment"])
        r = self.c.get("/api/dane/ventana?territory=buenaventura").get_json()
        self.assertEqual(r["puntos"], [])

    def test_02_no_autorizado(self):
        """Aprobación por un usuario no autorizado → denegada."""
        self.salir()
        self.assertIn(self.c.get("/api/admin/dane").status_code, (401, 403))
        self.assertIn(self.c.post("/api/admin/dane/lote", json={"ids": [1], "accion": "aprobar"}).status_code, (401, 403))

    def test_03_sin_csrf(self):
        self.como_admin()
        self.assertEqual(self.c.post("/api/admin/dane/lote", json={"ids": [1], "accion": "aprobar"}).status_code, 403)

    def test_04_centro_de_datos(self):
        h = self.como_admin()
        d = self.c.get("/api/admin/dane").get_json()
        self.assertEqual(d["resumen"]["pendientes"], 6)
        rel = [g for g in d["releases"] if g["kind"] == "mensual"]
        self.assertEqual(len(rel), 1, "las seis ciudades de un anexo forman una sola publicación")
        it = rel[0]["items"][0]
        self.assertIn("fuente", it["verificacion"])
        self.assertIn("extraccion", it["verificacion"])
        self.assertIn("comparacion", it["verificacion"])
        self.assertTrue(it["verificacion"]["completa"])

    def test_05_rechazo_sin_nota_bloqueado(self):
        h = self.como_admin()
        ids = [g for g in self.c.get("/api/admin/dane").get_json()["releases"] if g["kind"] == "mensual"][0]["ids"]
        r = self.c.post("/api/admin/dane/lote", headers=h, json={"ids": ids[:1], "accion": "rechazar", "nota": ""})
        self.assertEqual(r.status_code, 400)

    def test_06_rechazo_con_nota_conserva_motivo(self):
        h = self.como_admin()
        g = [g for g in self.c.get("/api/admin/dane").get_json()["releases"] if g["kind"] == "mensual"][0]
        tumaco = [i["id"] for i in g["items"] if i["territory"] == "tumaco"]
        r = self.c.post("/api/admin/dane/lote", headers=h, json={"ids": tumaco, "accion": "rechazar", "nota": "No coincide con el archivo"})
        self.assertEqual(r.status_code, 200)
        hist = self.c.get("/api/admin/dane").get_json()["historial"]
        self.assertTrue(any(x["status"] == "rechazado" and x["note"] == "No coincide con el archivo" for x in hist))

    def test_07_aprobar_lote_publica_y_confirma(self):
        """CAEDI aprueba → capa aprobada, indicadores públicos actualizados y confirmación de dónde."""
        h = self.como_admin()
        g = [g for g in self.c.get("/api/admin/dane").get_json()["releases"] if g["kind"] == "mensual"][0]
        r = self.c.post("/api/admin/dane/lote", headers=h, json={"ids": g["ids"], "accion": "aprobar"}).get_json()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["publicacion"]), 5)
        bva = [p for p in r["publicacion"] if "Buenaventura" in p["titulo"]][0]
        self.assertTrue(bva["en_celda"])
        self.assertIn("Tarjeta de «La cifra y la voz»", bva["vistas"])
        d = self.c.get("/api/datos/estado?territory=buenaventura&field=unemployment").get_json()["dato"]
        self.assertEqual(d["status"], "verificado")
        self.assertEqual(d["value"], 23.4)
        self.assertEqual(d["reviewed_by"], "Equipo CAEDI", "el pasaporte público no expone usuarios")
        self.assertTrue(d["source_url"].startswith("https://www.dane.gov.co/"))
        self.assertEqual(d["sheet"], "Ciudades intermedias")
        # Tumaco fue rechazado: sin dato, no se inventa
        self.assertIsNone(A.TERRITORIES["tumaco"]["unemployment"])


class T3_Ventana(Base):
    def test_01_mes_faltante_es_hueco(self):
        """Mes sin dato en la ventana → hueco, sin interpolación ni arrastre."""
        self.publicar_meses([5, 6, 7, 8], quitar={7: ["Tumaco"]})
        p = self.c.get("/api/dane/ventana?territory=tumaco").get_json()["puntos"]
        self.assertEqual([x["period"] for x in p], ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])
        self.assertIsNone(p[0]["value"])           # abril rechazado
        self.assertIsNone(p[3]["value"])           # julio no publicado
        self.assertIsNotNone(p[4]["value"])
        p12 = self.c.get("/api/dane/ventana?territory=buenaventura&n=12").get_json()
        self.assertEqual(len(p12["puntos"]), 12)
        self.assertEqual(p12["archivo"], 5)

    def test_02_valor_viejo_no_es_actual(self):
        """Existe un valor anterior pero no el actual → no se presenta como actual."""
        self.publicar_meses([9], quitar={9: ["Quibdó"]})
        self.assertIsNone(A.TERRITORIES["choco"]["unemployment"])
        d = self.c.get("/api/datos/estado?territory=choco&field=unemployment").get_json()["dato"]
        self.assertEqual(d["status"], "sin_dato")
        otras = [o for o in A.otras_cifras_oficiales() if o["territory"] == "choco" and o.get("url", "").startswith("https://www.dane")]
        self.assertEqual(otras, [], "un mes anterior tampoco se muestra como «otra cifra» actual")


class T4_Anual_y_fallos(Base):
    def test_01_anual_reemplaza_referencia(self):
        con = D.conectar(A.DB_PATH)
        D.tarea_anual(con, leer_json_fn=lambda u: [{"a_o": "2024", "cobertura_neta_media": "32.34"}],
                      existe_fn=lambda u: False, anio_actual=2026)
        sid = [p["id"] for p in D.pendientes(con) if p["kind"] == "anual" and p["territory"] == "buenaventura"][0]
        con.close()
        h = self.como_admin()
        r = self.c.post(f"/api/admin/dane/{sid}/aprobar", headers=h).get_json()
        self.assertEqual(r["status"], "ok")
        d = self.c.get("/api/datos/estado?territory=buenaventura&field=edu_media").get_json()["dato"]
        self.assertEqual((d["status"], d["value"], str(d["period"])), ("verificado", 32.34, "2024"))

    def test_02_fallo_del_actualizador(self):
        """Falla la revisión automática → la administración lo ve; lo aprobado sigue intacto."""
        antes = A.TERRITORIES["buenaventura"]["unemployment"]
        con = D.conectar(A.DB_PATH)

        def roto(u, d):
            with open(d, "w") as f:
                f.write("no es un excel")
            return "sha"
        D.tarea_mensual(con, hoy=date(2026, 11, 3), descargar_fn=roto, existe_fn=lambda u: "oct2026" in u)
        con.close()
        self.como_admin()
        R = self.c.get("/api/admin/dane").get_json()["resumen"]
        self.assertEqual(R["sistema"]["k"], "error")
        self.assertGreaterEqual(R["alertas"], 1)
        A.load_official_indicators()
        self.assertEqual(A.TERRITORIES["buenaventura"]["unemployment"], antes)

    def test_03_revision_manual_no_publica(self):
        """«Revisar ahora» lanza una revisión sin publicar nada por sí misma."""
        h = self.como_admin()
        llamado = {}
        orig = D.ejecutar
        D.ejecutar = lambda solo=None, db_path=None: llamado.setdefault("ok", True)
        try:
            r = self.c.post("/api/admin/dane/ejecutar", headers=h).get_json()
            import time; time.sleep(0.3)
        finally:
            D.ejecutar = orig
        self.assertEqual(r["status"], "ok")
        self.assertTrue(llamado.get("ok"))


class T5_Comunidad_y_pagina(Base):
    def test_01_cero_comunitario_no_es_falta(self):
        """La comunidad reporta 0 → 0; sin aporte → no hay cifra (no 0)."""
        db = sqlite3.connect(A.DB_PATH)
        db.execute("""INSERT INTO community_indicators (territory,indicator,layer,official_value,official_source,
                      community_value,community_source,difference,direction,evidence_body,validated)
                      VALUES ('cartagena','Tasa de desempleo (%)','Empleo',NULL,'',0,'Prueba',0,'','prueba',1)""")
        db.commit(); db.close()
        cells = self.c.get("/api/narrative-data/radar?all=1").get_json()["cells"]
        cg = [c for c in cells if c["territory"] == "cartagena" and c["indicator"]["field"] == "unemployment"]
        self.assertTrue(cg and cg[0]["community_value"] == 0)
        sa = [c for c in cells if c["territory"] == "sanandres" and c["indicator"]["field"] == "connectivity"]
        self.assertTrue(not sa or sa[0].get("community_value") is None)

    def test_02_correccion_antigua_no_es_cifra_oficial(self):
        """Una cifra oficial guardada en una corrección antigua no ocupa el lugar de la vigente."""
        cells = self.c.get("/api/narrative-data/radar?all=1").get_json()["cells"]
        ps = [c for c in cells if c["territory"] == "pacificosur" and c["indicator"]["field"] == "connectivity"]
        self.assertTrue(ps)
        self.assertIsNone(ps[0]["indicator"]["official_value"])

    def test_03_pagina_y_rotulos(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        html = pagina_completa(self.c)
        for marca in ("function sourcePassportHTML", "Sin aporte comunitario", "function mxTrend", "Centro de datos OnLife Afro"):
            self.assertIn(marca, html)
        self.assertNotIn("TER_DATA[s]?.[metric] || 0", html, "el gráfico ya no rellena con líneas base")


class T6_Archivo_oficial(Base):
    def test_01_francisco_pizarro_con_narino(self):
        """Con el archivo de indicadores antiguo (agregado Cauca + Nariño), Francisco Pizarro toma las cifras de Nariño."""
        import csv
        os.makedirs(A.DATA_FOLDER, exist_ok=True)
        ind = os.path.join(A.DATA_FOLDER, "official_indicators.csv")
        fic = os.path.join(A.DATA_FOLDER, "official_indicators_ficha.csv")
        campos = ["unemployment", "poverty", "education", "edu_media", "healthcare", "connectivity"]
        filas = {"tumaco": [6.5, 39.2, 7.68, "", 94.0, 21.9], "pacificosur": [7.3, 41.1, 7.90, "", 95.2, 19.8]}
        with open(ind, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["territory"] + campos)
            for t, v in filas.items(): w.writerow([t] + v)
        with open(fic, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["territory", "field", "anio", "fuente", "ambito"])
            for c in campos:
                w.writerow(["tumaco", c, "2024", "DANE — GEIH 2024", "Nariño (departamento)"])
                w.writerow(["pacificosur", c, "2024", "DANE — GEIH 2024", "Cauca y Nariño (departamentos)"])
        try:
            A._OFFICIAL_INDICATORS_CACHE = None; A._OFFICIAL_STAMP = -1
            A.load_official_indicators()
            t = A.TERRITORIES["pacificosur"]
            self.assertEqual((t["unemployment"], t["poverty"], t["education"], t["healthcare"], t["connectivity"]),
                             (6.5, 39.2, 7.68, 94.0, 21.9))
            self.assertEqual(t["unemployment_ambito"], "Nariño (departamento)")
            self.assertEqual(t["advertencia"], "")
            d = self.c.get("/api/datos/estado?territory=pacificosur&field=poverty").get_json()["dato"]
            self.assertEqual((d["status"], d["value"], d["scope"]), ("verificado", 39.2, "Nariño (departamento)"))
        finally:
            os.remove(ind); os.remove(fic)
            A._OFFICIAL_INDICATORS_CACHE = None; A._OFFICIAL_STAMP = -1
            A.load_official_indicators()


class T7_Relatos_en_el_mapa(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db = sqlite3.connect(A.DB_PATH)
        ins = ("INSERT INTO contributions (territory,category,type,title,body,author,media_url,media_type,lat,lon,approved,status) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        cls.ids = {}
        for k, v in {
            "audio": ("buenaventura", "Historia y Memoria", "story", "La marimba del estero", "Relato del estero.", "Mesa BVA", "/gallery/a.mp3", "audio", 3.88, -77.031, 1, "published"),
            "video": ("buenaventura", "Cultura y Tradición", "story", "La pesca", "Mira https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Ana", "", "", 3.95, -77.10, 1, "published"),
            "denuncia": ("buenaventura", "Denuncia Comunitaria", "denuncia", "Amenaza", "Texto", "Anónimo", "", "", 3.90, -77.0, 1, "published"),
            "pendiente": ("buenaventura", "Historia y Memoria", "story", "Pendiente", "Texto", "X", "", "", 3.9, -77.0, 0, "pending"),
            "tumaco": ("tumaco", "Historia y Memoria", "story", "El cacao", "Texto", "Y", "", "", 1.81, -78.76, 1, "published"),
        }.items():
            cls.ids[k] = db.execute(ins, v).lastrowid
        db.commit(); db.close()

    def _rel(self, ter="buenaventura"):
        return self.c.get(f"/api/relatos?territory={ter}").get_json()

    def test_01_territorios_y_agrupacion(self):
        t = self.c.get("/api/relatos/territorios").get_json()["territorios"]
        self.assertEqual(len([x for x in t if x["narp"]]), 7)
        d = self._rel()
        titulos = [r["title"] for l in d["lugares"] for r in l["relatos"]]
        self.assertIn("La marimba del estero", titulos)
        self.assertNotIn("Amenaza", titulos, "las denuncias no se muestran en el mapa de relatos")
        self.assertNotIn("Pendiente", titulos, "solo relatos publicados")
        self.assertTrue(d["bienvenida"].get("defecto"))
        self.assertEqual(self.c.get("/api/relatos?territory=xx").status_code, 400)

    def test_02_lugares_solo_admin(self):
        self.salir()
        body = {"territory": "buenaventura", "nombre": "Estero San Antonio", "lat": 3.87, "lon": -77.05}
        self.assertIn(self.c.post("/api/relatos/lugares", json=body).status_code, (401, 403))
        self.como_admin()
        self.assertEqual(self.c.post("/api/relatos/lugares", json=body).status_code, 403, "sin token CSRF")

    def test_03_crear_asignar_narradores_bienvenida(self):
        h = self.como_admin()
        r = self.c.post("/api/relatos/lugares", headers=h, json={"territory": "buenaventura", "nombre": "Estero San Antonio",
                        "tipo": "estero", "lat": 3.87, "lon": -77.05}).get_json()
        self.assertEqual(r["status"], "ok"); lid = r["id"]
        self.assertEqual(self.c.post("/api/relatos/lugares", headers=h, json={"territory": "buenaventura", "nombre": "Fuera",
                         "lat": 40, "lon": 3}).status_code, 400)
        self.assertEqual(self.c.post("/api/relatos/asignar", headers=h, json={"contribution_id": self.ids["tumaco"], "place_id": lid}).status_code, 400,
                         "no se puede ubicar un relato en un lugar de otro territorio")
        self.assertEqual(self.c.post("/api/relatos/asignar", headers=h, json={"contribution_id": self.ids["audio"], "place_id": lid}).get_json()["status"], "ok")
        self.assertEqual(self.c.post("/api/relatos/narradores", headers=h, json={"contribution_id": self.ids["audio"],
                         "narradores": [{"nombre": "Marius"}]}).status_code, 400, "sin consentimiento no se guardan nombres")
        self.c.post("/api/relatos/narradores", headers=h, json={"contribution_id": self.ids["audio"], "consentimiento": True,
                    "narradores": [{"nombre": "Marius"}, {"nombre": "Josefa <b>Pérez</b>"}]})
        self.c.post("/api/relatos/bienvenida", headers=h, json={"territory": "buenaventura", "texto": "Bienvenidos al estero.", "idioma": "es"})
        d = self._rel()
        lugar = [l for l in d["lugares"] if l["id"] == lid][0]
        self.assertEqual(lugar["tipo"], "estero")
        rel = lugar["relatos"][0]
        self.assertEqual([n["nombre"] for n in rel["narradores"]][0], "Marius")
        self.assertNotIn("<b>", rel["narradores"][1]["nombre"])
        self.assertEqual(d["bienvenida"]["texto"], "Bienvenidos al estero.")
        # eliminar el lugar devuelve el relato a su ubicación original
        self.c.delete(f"/api/relatos/lugares/{lid}", headers=h)
        d = self._rel()
        self.assertTrue(any(r["title"] == "La marimba del estero" and l["auto"] for l in d["lugares"] for r in l["relatos"]))

    def test_04_pagina(self):
        html = pagina_completa(self.c)
        for marca in ('id="p-relatos"', "function initRelatos", "Relatos en el mapa", "opentopomap"):
            self.assertIn(marca, html)
        sw = self.c.get("/sw.js").get_data(as_text=True)
        self.assertIn("onlife-teselas", sw)


class T8_Pulido(Base):
    def test_01_recursos_con_cache_larga(self):
        import re as _re
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        rutas = _re.findall(r'(?:href|src)="(/assets/app\.[0-9a-f]+\.(?:css|js))"', html)
        self.assertEqual(len(rutas), 2)
        self.assertLess(len(html), 400_000, "la portada ya no lleva el CSS y el JS en línea")
        for ruta in rutas:
            a = self.c.get(ruta, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(a.status_code, 200)
            self.assertIn("immutable", a.headers["Cache-Control"])
            self.assertEqual(a.headers.get("Content-Encoding"), "gzip")
        self.assertEqual(self.c.get("/assets/app.000000000000.js").status_code, 404)
        self.assertIn("window.__OA={", html)
        sw = self.c.get("/sw.js").get_data(as_text=True)
        for ruta in rutas:
            self.assertIn(ruta, sw)
        self.assertIn("allSettled", sw)

    def test_02_csp_permite_precarga_del_service_worker(self):
        csp = self.c.get("/sw.js").headers["Content-Security-Policy"]
        conectar = csp.split("connect-src")[1].split(";")[0]
        for origen in ("https://cdnjs.cloudflare.com", "https://unpkg.com", "https://fonts.googleapis.com"):
            self.assertIn(origen, conectar)

    def test_03_pendientes_no_son_publicos(self):
        self.salir()
        d = self.c.get("/api/contributions?status=pending").get_json()
        self.assertEqual(d, [])
        todos = self.c.get("/api/contributions?status=all&per_page=100").get_json()
        self.assertTrue(all(x["status"] == "published" for x in todos))
        self.assertTrue(all("author_uid" not in x for x in todos))
        # quien envió algo sí ve su propio pendiente
        yo = "persistent_" + "a" * 24
        db = sqlite3.connect(A.DB_PATH)
        cid = db.execute("INSERT INTO contributions (territory,title,body,author_uid,approved,status) "
                         "VALUES ('choco','Mío pendiente','x',?,0,'pending')", (yo,)).lastrowid
        db.commit(); db.close()
        mios = self.c.get(f"/api/contributions?status=all&mine=1&viewer={yo}").get_json()
        self.assertEqual([x["id"] for x in mios], [cid])
        self.assertEqual(self.c.get(f"/api/archive/story/{cid}/history").status_code, 404)
        self.assertEqual(self.c.get(f"/api/archive/story/{cid}/history?viewer={yo}").status_code, 200)
        self.assertNotIn("author_uid", self.c.get(f"/api/archive/story/{cid}/history?viewer={yo}").get_json()["contribution"])
        self.assertEqual(self.c.get(f"/api/narrative-data/{cid}").status_code, 404)
        h = self.como_admin()
        self.assertTrue(any(x["id"] == cid for x in self.c.get("/api/contributions?status=pending").get_json()))

    def test_04_borrar_comentario_requiere_autoria_real(self):
        self.salir()
        dueno = "persistent_" + "b" * 24
        with self.c.session_transaction() as s:
            s["csrf_token"] = "tok"
        h = {"X-CSRF-Token": "tok"}
        cid = self.c.post("/api/comment/1", headers=h, json={"body": "hola", "author": "Comunidad", "voter": dueno}).get_json()["id"]
        otro = "persistent_" + "c" * 24
        self.assertEqual(self.c.delete(f"/api/comment/{cid}", headers=h, json={"voter": otro}).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/comment/{cid}", headers=h, json={"voter": dueno}).status_code, 200)

    def test_06_solo_la_persona_autora_ve_borrar(self):
        self.salir()
        yo = "persistent_" + "d" * 24
        db = sqlite3.connect(A.DB_PATH)
        cid = db.execute("INSERT INTO contributions (territory,title,body,author_uid,approved,status) "
                         "VALUES ('choco','Mía publicada','x',?,1,'published')", (yo,)).lastrowid
        db.commit(); db.close()
        mia = [x for x in self.c.get(f"/api/contributions?per_page=100&viewer={yo}").get_json() if x["id"] == cid][0]
        self.assertTrue(mia["is_mine"])
        otra = [x for x in self.c.get("/api/contributions?per_page=100&viewer=persistent_" + "e" * 24).get_json() if x["id"] == cid][0]
        self.assertFalse(otra["is_mine"])
        self.como_admin()
        adm = [x for x in self.c.get("/api/contributions?per_page=100").get_json() if x["id"] == cid][0]
        self.assertFalse(adm["is_mine"], "la administración no ve el menú de borrar en el muro")
        html = pagina_completa(self.c)
        self.assertNotIn("modTab('published')\">Publicadas", html)
        self.assertIn("html.large-text{font-size:20px;}", html)

    def test_05_ids_unicos(self):
        import re as _re, collections
        html = self.c.get("/").get_data(as_text=True)
        ids = _re.findall(r'\sid="([^"$`{]+)"', html)
        dup = [k for k, v in collections.Counter(ids).items() if v > 1]
        self.assertEqual(dup, [])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
