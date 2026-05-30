# =============================================================
# ONLIFE AFRO PLATFORM v6.0 PWA
# Plataforma de Humanidades Digitales Afrocolombianas
# Mackmot Pachotto Ambrose
# Universidad Santo Tomás · CAEDI
# =============================================================
#
# INSTALLATION:  python -m pip install flask
# RUN:           python app.py
# OPEN:          http://127.0.0.1:5000
#
# FOLDER STRUCTURE
#   app.py
#   static/
#     hero.png / logo_usta.png
#     gallery/      ← photos (jpg,png), video (mp4,mov), audio (mp3,wav,ogg)
#     pdfs/         ← infographic PDFs (auto-served for download)
#     territories/  ← territory photos named by territory slug (e.g. choco.jpg)
# =============================================================

import os
import sqlite3
import json
from flask import (
    Flask, render_template_string, request,
    jsonify, send_from_directory
)
from datetime import datetime

app = Flask(__name__)
app.secret_key = "onlife_afro_caedi_2026"

STATIC_FOLDER      = os.path.join(os.path.dirname(__file__), "static")
GALLERY_FOLDER     = os.path.join(STATIC_FOLDER, "gallery")
PDF_FOLDER         = os.path.join(STATIC_FOLDER, "pdfs")
TERRITORY_FOLDER   = os.path.join(STATIC_FOLDER, "territories")
DB_PATH            = os.path.join(os.path.dirname(__file__), "community.db")
os.makedirs(GALLERY_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)
os.makedirs(TERRITORY_FOLDER, exist_ok=True)

# =============================================================
# DATABASE SETUP — SQLite community chat
# =============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                room      TEXT    NOT NULL DEFAULT 'general',
                sender    TEXT    NOT NULL,
                text      TEXT    NOT NULL,
                ts        TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT    NOT NULL UNIQUE,
                password  TEXT    NOT NULL,
                name      TEXT    NOT NULL,
                role      TEXT    NOT NULL DEFAULT 'community',
                room      TEXT    NOT NULL DEFAULT 'general',
                created   TEXT,
                last_seen TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS testimonials (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    NOT NULL,
                territory TEXT    NOT NULL,
                message   TEXT    NOT NULL,
                approved  INTEGER NOT NULL DEFAULT 0,
                ts        TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title     TEXT    NOT NULL,
                date      TEXT    NOT NULL,
                time      TEXT    NOT NULL,
                location  TEXT    NOT NULL,
                territory TEXT    NOT NULL DEFAULT 'general',
                link      TEXT    DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL
            )
        """)
        # Seed messages if empty
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if count == 0:
            seed = [
                ("general","CAEDI","¡Bienvenidos a la Red Comunitaria OnLife Afro! 🌍","09:00"),
                ("general","CAEDI","Este es el espacio oficial de coordinación territorial afrocolombiana. 📊","09:01"),
                ("choco","Líder Chocó","Red del Chocó activa. Pobreza 62% · Conectividad 31%. 🌿","10:00"),
                ("buenaventura","Consejo BVA","Puerto Pacífico presente. 16.1% desempleo — visibilización urgente. ⚓","08:00"),
                ("investigadores","Mackmot","Nueva versión del pipeline de datos lista para revisión. 🔬","Lun"),
            ]
            conn.executemany("INSERT INTO messages(room,sender,text,ts) VALUES(?,?,?,?)", seed)
        # Seed events if empty
        ev_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if ev_count == 0:
            events_seed = [
                ("Asamblea Territorial Chocó","2026-06-06","3:00 PM","Virtual · Zoom","choco","https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y"),
                ("Presentación Dashboard DANE","2026-06-12","10:00 AM","CAEDI · Calle 42 #13-50","general","https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y"),
                ("Foro Pacífico Sur","2026-06-20","2:00 PM","Buenaventura · Virtual","pacificosur","https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y"),
                ("Taller Vigilancia Epistemológica","2026-07-05","9:00 AM","Universidad Santo Tomás","investigadores",""),
            ]
            conn.executemany("INSERT INTO events(title,date,time,location,territory,link) VALUES(?,?,?,?,?,?)", events_seed)
        conn.commit()

init_db()

# WhatsApp group links — replace with your real invite URLs
WHATSAPP_GROUPS = {
    "general":       "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "choco":         "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "buenaventura":  "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "tumaco":        "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "investigadores":"https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "sanandres":     "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
    "pacificosur":   "https://chat.whatsapp.com/DSWFYlg6hsRIbTfMVzPz9y",
}

# =============================================================
# MEDIA DETECTION
# =============================================================

IMAGE_EXTS = {".jpg",".jpeg",".png",".webp",".gif"}
VIDEO_EXTS = {".mp4",".webm",".mov",".avi",".mkv"}
AUDIO_EXTS = {".mp3",".wav",".ogg",".m4a",".aac",".flac"}

def media_type(f):
    e = os.path.splitext(f)[1].lower()
    if e in IMAGE_EXTS: return "image"
    if e in VIDEO_EXTS: return "video"
    if e in AUDIO_EXTS: return "audio"
    return None

def get_gallery_media():
    try:
        out = []
        for f in sorted(os.listdir(GALLERY_FOLDER)):
            mt = media_type(f)
            if mt: out.append({"name":f,"type":mt,"url":f"/gallery/{f}"})
        return out
    except: return []

def get_hero_photo():
    for m in get_gallery_media():
        if m["type"] == "image": return m["url"]
    return "/static/hero.png"

def get_territory_photo(slug):
    """Return a photo URL for a territory slug if it exists."""
    for ext in [".jpg",".jpeg",".png",".webp"]:
        path = os.path.join(TERRITORY_FOLDER, slug + ext)
        if os.path.exists(path):
            return f"/territories/{slug}{ext}"
    return None

def get_pdfs():
    try:
        pdfs = []
        labels = {
            "infografia_pobreza_afrocolombiana":  ("Pobreza Monetaria Afrocolombiana",  "43% de la población afro vive en pobreza", "📊"),
            "infografia_desempleo_juvenil":        ("Desempleo Juvenil Afro",             "26% desempleo en jóvenes 18-28 años",      "📉"),
            "infografia_brecha_digital":           ("Brecha Digital Territorial",          "Solo 39% de hogares con internet",         "📡"),
            "infografia_educacion_superior":       ("Acceso a Educación Superior",        "35% acceso a educación superior",          "🎓"),
            "infografia_territorios_estrategicos": ("7 Territorios Estratégicos",         "Chocó, Buenaventura, Tumaco y más",        "📍"),
            "metodologia_onlife_afro":             ("Metodología OnLife Afro",            "Investigación mixta: datos + testimonios", "🔬"),
        }
        for f in sorted(os.listdir(PDF_FOLDER)):
            if f.lower().endswith(".pdf"):
                key = os.path.splitext(f)[0]
                title, desc, icon = labels.get(key, (f.replace("_"," ").replace(".pdf",""), "Infografía CAEDI", "📄"))
                pdfs.append({"file":f,"title":title,"desc":desc,"icon":icon,"url":f"/pdfs/{f}"})
        return pdfs
    except: return []

# =============================================================
# DATA
# =============================================================

TERRITORIES = [
    {
        "name":"Chocó","slug":"choco","icon":"🌿",
        "desc":"Pacífico colombiano · Mayor biodiversidad del país",
        "region":"Región Pacífica","population":"540,000 hab.",
        "unemployment":18.4,"connectivity":31,"education":6.2,"poverty":62,
        "healthcare":42,"youth_unemployment":31.2,
        "key_fact":"Solo 1 médico por cada 4,200 habitantes",
        "history":"El Chocó es el único departamento de Colombia con costas en dos océanos. Su población es mayoritariamente afrocolombiana e indígena, y enfrenta las mayores brechas de desigualdad del país.",
        "challenges":["Alta tasa de minería ilegal","Falta de infraestructura vial","Desplazamiento forzado","Acceso limitado a servicios de salud"],
        "strengths":["Mayor biodiversidad del mundo","Cultura ancestral viva","Recursos hídricos abundantes","Gastronomía única"]
    },
    {
        "name":"Buenaventura","slug":"buenaventura","icon":"⚓",
        "desc":"Principal puerto del Pacífico colombiano",
        "region":"Valle del Cauca","population":"440,000 hab.",
        "unemployment":16.1,"connectivity":45,"education":7.4,"poverty":55,
        "healthcare":51,"youth_unemployment":28.7,
        "key_fact":"Maneja el 60% del comercio exterior de Colombia",
        "history":"Buenaventura es la ciudad portuaria más importante del Pacífico colombiano. Pese a mover miles de millones en mercancías, su población afrocolombiana enfrenta pobreza estructural y violencia.",
        "challenges":["Violencia urbana y grupos armados","Pobreza extrema en barrios periféricos","Contaminación portuaria","Desigualdad en distribución de riqueza portuaria"],
        "strengths":["Puerto estratégico nacional","Cultura del Pacífico","Gastronomía de mar","Identidad afrocolombiana fuerte"]
    },
    {
        "name":"Tumaco","slug":"tumaco","icon":"🌊",
        "desc":"Nariño · Costa Pacífica sur",
        "region":"Nariño","population":"220,000 hab.",
        "unemployment":19.3,"connectivity":28,"education":5.9,"poverty":67,
        "healthcare":38,"youth_unemployment":34.1,
        "key_fact":"Mayor producción de cacao fino de aroma del Pacífico",
        "history":"Tumaco, conocido como 'La Perla del Pacífico', es un municipio de Nariño con una rica tradición cultural afrocolombiana. Enfrenta desafíos de seguridad ligados al narcotráfico y la economía ilícita.",
        "challenges":["Crisis de seguridad pública","Economías ilegales","Falta de oportunidades laborales","Erosión costera"],
        "strengths":["Producción de cacao de exportación","Cultura afronariñense vibrante","Potencial turístico","Pesca artesanal"]
    },
    {
        "name":"San Andrés","slug":"sanandres","icon":"🏝️",
        "desc":"Archipiélago · Caribe colombiano",
        "region":"Archipiélago","population":"80,000 hab.",
        "unemployment":11.7,"connectivity":72,"education":9.8,"poverty":22,
        "healthcare":78,"youth_unemployment":19.4,
        "key_fact":"Único territorio con mayoría raizal en Colombia",
        "history":"El archipiélago de San Andrés, Providencia y Santa Catalina es el hogar del pueblo Raizal, una comunidad afrocolombiana con idioma propio (Creole inglés) y cultura única del Caribe.",
        "challenges":["Sobrepoblación y presión ambiental","Pérdida de cultura raizal","Acceso limitado a tierras","Cambio climático y elevación del mar"],
        "strengths":["Turismo internacional","Cultura raizal única","Biodiversidad marina excepcional","Bilingüismo Creole-Español"]
    },
    {
        "name":"Cali","slug":"cali","icon":"🏙️",
        "desc":"Valle del Cauca · Mayor población afro urbana",
        "region":"Valle del Cauca","population":"2.2M hab.",
        "unemployment":14.8,"connectivity":58,"education":8.3,"poverty":38,
        "healthcare":65,"youth_unemployment":26.8,
        "key_fact":"40% de la población caleña se identifica como afrocolombiana",
        "history":"Cali alberga la mayor concentración de población afrocolombiana en una ciudad de Colombia. Barrios como Aguablanca son epicentros culturales afros con alta densidad y diversidad.",
        "challenges":["Segregación urbana","Desempleo en comunas populares","Violencia y inseguridad","Acceso desigual a educación superior"],
        "strengths":["Capital mundial de la salsa","Movimiento cultural afrocolombiano","Universidades e investigación","Activismo y organizaciones sociales"]
    },
    {
        "name":"Cartagena","slug":"cartagena","icon":"🏰",
        "desc":"Bolívar · Caribe colombiano",
        "region":"Bolívar","population":"1.1M hab.",
        "unemployment":15.2,"connectivity":51,"education":7.9,"poverty":44,
        "healthcare":59,"youth_unemployment":27.3,
        "key_fact":"Ciudad turística con alta desigualdad racial en el centro histórico",
        "history":"Cartagena fue el principal puerto de llegada de africanos esclavizados en América del Sur. Hoy tiene una población mayoritariamente afrocolombiana, concentrada en barrios periféricos mientras el turismo se centraliza en la ciudad amurallada.",
        "challenges":["Gentrificación del centro histórico","Desigualdad racial visible","Informalidad laboral turística","Falta de acceso a tierra"],
        "strengths":["Patrimonio histórico UNESCO","Cultura caribeña afrocolombiana","Gastronomía afrocartagenera","Identidad palenquera"]
    },
    {
        "name":"Pacífico Sur","slug":"pacificosur","icon":"🌺",
        "desc":"Territorios colectivos · Comunidades étnicas",
        "region":"Nariño / Cauca","population":"180,000 hab.",
        "unemployment":20.1,"connectivity":22,"education":5.4,"poverty":71,
        "healthcare":31,"youth_unemployment":36.5,
        "key_fact":"Mayor concentración de territorios colectivos afrocolombianos",
        "history":"El Pacífico Sur alberga cientos de consejos comunitarios y territorios colectivos titulados a comunidades negras bajo la Ley 70 de 1993. Es la región con mayor biodiversidad y mayor brecha de desarrollo del país.",
        "challenges":["Aislamiento geográfico extremo","Conflicto armado persistente","Falta de servicios básicos","Minería ilegal invasiva"],
        "strengths":["Autonomía territorial y Ley 70","Medicina tradicional y etnobotánica","Consejos comunitarios organizados","Biodiversidad planetaria"]
    },
]

DASHBOARDS = [
    {"label":"La Hoja de Ruta", "url":"https://public.tableau.com/app/profile/ambrose.mackmot/viz/AfroDataColombiaPlataformaOnLifeAfro/LaHojadeRuta","embed":"https://public.tableau.com/views/AfroDataColombiaPlataformaOnLifeAfro/LaHojadeRuta?:showVizHome=no&:embed=true&:toolbar=yes"},
    {"label":"Datos DANE",      "url":"https://public.tableau.com/app/profile/ambrose.mackmot/viz/AfroDataColombiaPlataformaOnLifeAfro/","embed":"https://public.tableau.com/views/AfroDataColombiaPlataformaOnLifeAfro/?:showVizHome=no&:embed=true&:toolbar=yes"},
    {"label":"Perfil Tableau",  "url":"https://public.tableau.com/app/profile/ambrose.mackmot/","embed":None},
]

NEWS = [
    {
        "tag":"Investigación",
        "photo":"https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=600&q=80",
        "photo_alt":"Dashboard de datos afrocolombianos",
        "title":"AfroData Colombia: justicia epistémica y datos abiertos",
        "body":"La plataforma integra datos del DANE, GEIH y Censo 2018 para visibilizar las condiciones de vida de la población afrocolombiana a través de dashboards interactivos.",
        "link":"https://public.tableau.com/app/profile/ambrose.mackmot/viz/AfroDataColombiaPlataformaOnLifeAfro/LaHojadeRuta",
        "link_text":"Ver dashboard →","meta":"Mayo 2026"
    },
    {
        "tag":"Comunidad",
        "photo":"https://images.unsplash.com/photo-1531206715517-5c0ba140b2b8?w=600&q=80",
        "photo_alt":"Comunidad afrocolombiana reunida",
        "title":"Centro Afrobogotá: espiritualidad y desarrollo integral",
        "body":"El CAEDI acompaña a comunidades afrocolombianas en Bogotá desde la Calle 42 #13-50, con programas de formación, cultura y memoria.",
        "link":"https://centroafrobogota.com/",
        "link_text":"centroafrobogota.com →","meta":"2026"
    },
    {
        "tag":"Digital",
        "photo":"https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=600&q=80",
        "photo_alt":"Cultura afrocolombiana Pacífico",
        "title":"OnLife Afro: plataforma de humanidades digitales",
        "body":"La plataforma combina Python, Tableau, datos geoespaciales Folium e IA conversacional para fortalecer la ciudadanía digital de comunidades afrocolombianas.",
        "link":"https://web.facebook.com/centro.afro.942",
        "link_text":"Seguir en Facebook →","meta":"5.1K seguidores"
    },
    {
        "tag":"Epistémico",
        "photo":"https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?w=600&q=80",
        "photo_alt":"Investigación y datos comunitarios",
        "title":"Vigilancia Epistemológica: datos que sirven a la comunidad",
        "body":"Inspirado en Bachelard y Bourdieu, el pipeline de datos incluye tres etapas de verificación que impiden que los datos del DANE sobrescriban realidades locales no capturadas.",
        "link":"#metodologia",
        "link_text":"Ver metodología →","meta":"CAEDI · 2026"
    },
]

CHATBOT = {
    "afro":         "La plataforma OnLife Afro promueve justicia epistémica, visibilidad territorial y bienestar de las comunidades afrocolombianas.",
    "dashboard":    "Los dashboards de Tableau visualizan desigualdades en empleo, educación, pobreza y conectividad usando datos del DANE y Censo 2018.",
    "infografia":   "Puedes descargar las infografías en PDF desde el menú 'Infografías' en la barra de navegación.",
    "pdf":          "Las infografías en PDF están disponibles para descarga gratuita. Ve al menú Infografías en la barra superior.",
    "chocó":        "Chocó tiene el 62% de pobreza y solo 31% de conectividad, siendo uno de los territorios con mayor brecha digital.",
    "buenaventura": "Buenaventura es el principal puerto del Pacífico con 16.1% de desempleo y 55% de pobreza.",
    "caedi":        "CAEDI es el Centro Afrocolombiano de Espiritualidad y Desarrollo Integral, ubicado en Calle 42 #13-50, Bogotá.",
    "dato":         "Los datos provienen del DANE, GEIH, Censo Nacional 2018 y datos abiertos del gobierno colombiano.",
    "territorio":   "La plataforma analiza 7 territorios: Chocó, Buenaventura, Tumaco, San Andrés, Cali, Cartagena y Pacífico Sur.",
    "audio":        "La galería incluye audio (MP3, WAV) y video (MP4, MOV) de las comunidades afrocolombianas. Ve a la sección Galería.",
    "comunidad":    "El espacio Comunidad es como un WhatsApp: puedes enviar mensajes, hacer llamadas de voz y video a líderes comunitarios.",
    "mensaje":      "Ve al módulo Comunidad para enviar mensajes y coordinar con otros miembros de la red afrocolombiana.",
    "llamada":      "Desde el módulo Comunidad puedes iniciar llamadas de voz y video con líderes territoriales conectados.",
    "pregunta":     "La pregunta de investigación es: ¿De qué manera la visualización de datos abiertos sobre bienestar afrocolombiano puede convertirse en un instrumento de apropiación epistémica? Ve a la sección Investigación.",
    "objetivo":     "El objetivo general es reducir la brecha epistémica entre producción estadística institucional y apropiación comunitaria afrocolombiana. Ve a #investigacion.",
    "onlife":       "OnLife viene de Floridi (2015): vida simultánea en lo físico y digital. Para comunidades NARP implica doble exclusión — territorial y epistémica.",
    "floridi":      "Luciano Floridi acuñó el término OnLife en 2015 para describir la condición de vivir simultáneamente en lo físico y digital. Base conceptual de esta plataforma.",
    "dane":         "Los datos del DANE provienen de la GEIH 2020-2024 y el Censo Nacional 2018. TD NARP es 4.8pp mayor que la media nacional. Ve a la sección Datos Abiertos.",
    "cita":         "Las referencias están en la sección Bibliografía de la plataforma. 44 fuentes en APA 7ª. Autores clave: Floridi, Mignolo, D'Ignazio & Klein, Santos, Noble.",
    "ocap":         "OCAP: Propiedad, Control, Acceso y Posesión. Principios del First Nations Information Governance Centre para soberanía de datos comunitarios.",
    "narp":         "NARP = Negros, Afrocolombianos, Raizales y Palenqueros. Según DANE 2018: 4.7 millones de personas (9.34% de la población). Subregistro estimado: 40-60%.",
    "csv":          "Los datasets están disponibles via API: /api/territories, /api/stats, /api/compare. Ve a la sección Datos Abiertos para la lista completa.",
    "pipeline":     "El pipeline tiene 6 etapas: Datos Abiertos → Limpieza Python → Vigilancia Epistemológica → Visualización Tableau → Validación Comunitaria → Justicia Epistémica.",
    "default":      "Gracias por tu pregunta. Explora los territorios, la investigación en #investigacion, las referencias en #referencias, o los datos abiertos en #datos-abiertos.",
}

# =============================================================
# SVG ICONS
# =============================================================

ICONS = {
    "facebook": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="#1877F2" d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.235 2.686.235v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.27h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/></svg>''',
    "tableau": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50" width="18" height="18"><rect width="50" height="50" rx="6" fill="#E97627"/><g fill="white"><rect x="23" y="5" width="4" height="14"/><rect x="23" y="31" width="4" height="14"/><rect x="5" y="23" width="14" height="4"/><rect x="31" y="23" width="14" height="4"/><rect x="14" y="10" width="3" height="10"/><rect x="14" y="30" width="3" height="10"/><rect x="33" y="10" width="3" height="10"/><rect x="33" y="30" width="3" height="10"/><rect x="10" y="14" width="10" height="3"/><rect x="10" y="33" width="10" height="3"/><rect x="30" y="14" width="10" height="3"/><rect x="30" y="33" width="10" height="3"/></g></svg>''',
    "web": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><circle cx="12" cy="12" r="10" fill="none" stroke="white" stroke-width="1.5"/><path d="M12 2a14.5 14.5 0 0 1 0 20M12 2a14.5 14.5 0 0 0 0 20M2 12h20" fill="none" stroke="white" stroke-width="1.5"/></svg>''',
    "pdf": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline fill="none" stroke="currentColor" stroke-width="1.8" points="14,2 14,8 20,8"/><line fill="none" stroke="currentColor" stroke-width="1.8" x1="12" y1="18" x2="12" y2="12"/><polyline fill="none" stroke="currentColor" stroke-width="1.8" points="9,15 12,18 15,15"/></svg>''',
    "download": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>''',
    "community": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="white" stroke-width="1.5" d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle fill="none" stroke="white" stroke-width="1.5" cx="9" cy="7" r="4"/><path fill="none" stroke="white" stroke-width="1.5" d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>''',
    "phone": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.42 2 2 0 0 1 3.6 1.27h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 8.91a16 16 0 0 0 6.18 6.18l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>''',
    "video_call": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><polygon fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="23 7 16 12 23 17 23 7"/><rect fill="none" stroke="currentColor" stroke-width="2" x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>''',
    "send": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" x1="22" y1="2" x2="11" y2="13"/><polygon fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="22 2 15 22 11 13 2 9 22 2"/></svg>''',
    "chart": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="18" y1="20" x2="18" y2="10"/><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="12" y1="20" x2="12" y2="4"/><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="6" y1="20" x2="6" y2="14"/><line fill="none" stroke="currentColor" stroke-width="2" x1="2" y1="20" x2="22" y2="20"/></svg>''',
    "map_pin": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle fill="none" stroke="currentColor" stroke-width="2" cx="12" cy="10" r="3"/></svg>''',
    "search": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><circle fill="none" stroke="currentColor" stroke-width="2" cx="11" cy="11" r="8"/><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="21" y1="21" x2="16.65" y2="16.65"/></svg>''',
    "mic": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M19 10v2a7 7 0 0 1-14 0v-2"/><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="12" y1="19" x2="12" y2="23"/><line fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" x1="8" y1="23" x2="16" y2="23"/></svg>''',
    "attach": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>''',
    "whatsapp": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18"><path fill="#25D366" d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>''',
}

# =============================================================
# HTML TEMPLATE
# =============================================================

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#B5341A">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="OnLife Afro">
<meta name="mobile-web-app-capable" content="yes">
<meta name="application-name" content="OnLife Afro">
<meta name="description" content="Plataforma de Humanidades Digitales Afrocolombianas · CAEDI · Universidad Santo Tomás">
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="/static/icons/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icons/icon-192x192.png">
<title>OnLife Afro – Plataforma de Humanidades Digitales Afrocolombianas</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --terra:#B5341A;--deep:#1B1B1B;--gold:#C9810A;--sky:#1B5E7A;
  --cream:#F7F1E8;--muted:#6B5B4E;--border:rgba(181,52,26,0.15);
  --green:#2D6A4F;--wa:#25D366;--wa-dark:#128C7E;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{font-family:'DM Sans',sans-serif;background:var(--cream);color:var(--deep);overflow-x:hidden;}

/* ── HEADER ── */
header{background:var(--deep);position:sticky;top:0;z-index:200;border-bottom:3px solid var(--terra);}
.header-inner{max-width:1400px;margin:auto;display:flex;align-items:center;justify-content:space-between;padding:12px 40px;gap:14px;flex-wrap:wrap;}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;}
.brand-logo{width:48px;height:48px;border-radius:50%;overflow:hidden;border:2px solid var(--gold);flex-shrink:0;}
.brand-logo img{width:100%;height:100%;object-fit:cover;}
.brand-text h1{font-family:'Playfair Display',serif;color:white;font-size:20px;line-height:1;}
.brand-text span{color:var(--gold);font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:500;}

/* ── NAV ── */
nav{display:flex;gap:2px;flex-wrap:wrap;align-items:center;}
nav>a,nav .drop-trigger{color:rgba(255,255,255,0.75);text-decoration:none;font-size:12.5px;font-weight:500;padding:7px 12px;border-radius:6px;transition:all .18s;cursor:pointer;background:none;border:none;font-family:'DM Sans',sans-serif;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;}
nav>a:hover,nav .drop-trigger:hover,nav>a.active{color:white;background:var(--terra);}
.dropdown{position:relative;}
.dropdown:hover .drop-menu,.dropdown:focus-within .drop-menu{display:block;}
.drop-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;min-width:320px;background:var(--deep);border:1px solid rgba(255,255,255,.12);border-radius:12px;overflow:hidden;box-shadow:0 24px 56px rgba(0,0,0,.45);z-index:300;}
.drop-menu a,.drop-menu button{display:flex;align-items:center;gap:12px;padding:12px 18px;color:rgba(255,255,255,.82);text-decoration:none;font-size:13px;transition:background .15s;border-bottom:1px solid rgba(255,255,255,.06);width:100%;background:none;border-left:none;border-right:none;border-top:none;font-family:'DM Sans',sans-serif;cursor:pointer;text-align:left;}
.drop-menu a:last-child,.drop-menu button:last-child{border-bottom:none;}
.drop-menu a:hover,.drop-menu button:hover{background:var(--terra);color:white;}
.drop-menu .di{width:28px;height:28px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:18px;}
.drop-menu .dm{flex:1;}
.drop-menu .dm small{display:block;font-size:10px;opacity:.6;margin-top:1px;}
.drop-caret{font-size:9px;opacity:.55;margin-left:1px;}
.drop-menu .drop-header{padding:10px 18px 6px;color:rgba(255,255,255,.35);font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:700;border-bottom:1px solid rgba(255,255,255,.06);}
.pdf-badge{background:rgba(181,52,26,.25);color:var(--gold);font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;letter-spacing:.5px;text-transform:uppercase;white-space:nowrap;}
.stat-badge{background:rgba(45,106,79,.25);color:#5cb98a;font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;white-space:nowrap;}

/* ── LINKS BAR ── */
.links-bar{background:var(--terra);padding:10px 40px;display:flex;align-items:center;justify-content:center;gap:20px;flex-wrap:wrap;}
.links-bar a{color:white;text-decoration:none;font-size:12px;font-weight:600;display:flex;align-items:center;gap:7px;opacity:.92;transition:opacity .2s;}
.links-bar a:hover{opacity:1;}
.links-bar a svg{flex-shrink:0;}
.links-bar .div{width:1px;height:16px;background:rgba(255,255,255,.3);}

/* ── HERO ── */
.hero{position:relative;min-height:92vh;display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:60px;padding:80px 60px;overflow:hidden;}
.hero-bg{position:absolute;inset:0;z-index:0;}
.hero-bg img{width:100%;height:100%;object-fit:cover;display:block;}
.hero-bg::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(27,27,27,.93) 0%,rgba(42,24,16,.88) 45%,rgba(27,58,74,.76) 100%);}
.hero-content{position:relative;z-index:2;}
.hero-eyebrow{display:inline-flex;align-items:center;gap:8px;background:rgba(181,52,26,.25);border:1px solid rgba(181,52,26,.5);color:var(--gold);font-size:11px;letter-spacing:2.5px;text-transform:uppercase;font-weight:600;padding:6px 14px;border-radius:20px;margin-bottom:24px;}
.hero h2{font-family:'Playfair Display',serif;font-size:clamp(38px,4.5vw,62px);font-weight:900;color:white;line-height:1.08;margin-bottom:20px;}
.hero h2 em{font-style:italic;color:var(--gold);}
.hero-tagline{font-family:'Playfair Display',serif;font-size:clamp(14px,1.6vw,20px);color:var(--gold);font-style:italic;letter-spacing:0.5px;line-height:1.5;margin-bottom:16px;font-weight:700;}
.hero-desc{color:rgba(255,255,255,.75);font-size:16px;line-height:1.75;max-width:480px;margin-bottom:36px;}
.hero-btns{display:flex;gap:12px;flex-wrap:wrap;}
.btn-primary{background:var(--terra);color:white;padding:13px 24px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:8px;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;}
.btn-primary:hover{background:#8f2612;transform:translateY(-2px);box-shadow:0 8px 24px rgba(181,52,26,.4);}
.btn-sky{background:var(--sky);color:white;padding:13px 24px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:8px;}
.btn-sky:hover{background:#144d63;transform:translateY(-2px);}
.btn-ghost{background:rgba(255,255,255,.1);color:white;border:1.5px solid rgba(255,255,255,.3);padding:13px 24px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:8px;}
.btn-ghost:hover{background:rgba(255,255,255,.2);}
.btn-wa{background:var(--wa);color:white;padding:13px 24px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:8px;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;}
.btn-wa:hover{background:var(--wa-dark);transform:translateY(-2px);}
.hero-stats{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:44px;}
.stat-chip{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:16px 18px;backdrop-filter:blur(6px);}
.stat-chip .num{font-family:'Playfair Display',serif;font-size:30px;font-weight:900;color:var(--gold);line-height:1;}
.stat-chip .lbl{font-size:11px;color:rgba(255,255,255,.55);margin-top:4px;line-height:1.4;}
.hero-photo{position:relative;z-index:2;}
.hero-photo-frame{border-radius:20px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.5);border:2px solid rgba(255,255,255,.12);aspect-ratio:3/4;min-height:420px;}
.hero-photo-frame img{width:100%;height:100%;object-fit:cover;object-position:center top;display:block;}
.hero-photo-caption{margin-top:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.partner-badge{background:rgba(255,255,255,.08);color:rgba(255,255,255,.85);padding:6px 12px;border-radius:20px;font-size:11px;font-weight:500;border:1px solid rgba(255,255,255,.12);display:flex;align-items:center;gap:6px;}
.partner-badge img{width:20px;height:20px;border-radius:50%;object-fit:contain;background:white;padding:1px;}

/* ── SECTIONS ── */
.section{padding:80px 40px;max-width:1400px;margin:auto;}
.sec-label{display:inline-flex;align-items:center;gap:8px;background:rgba(181,52,26,.1);border-left:3px solid var(--terra);color:var(--terra);font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:700;padding:6px 12px;margin-bottom:16px;}
.sec-title{font-family:'Playfair Display',serif;font-size:clamp(28px,3vw,42px);font-weight:900;line-height:1.2;margin-bottom:12px;}
.sec-sub{color:var(--muted);font-size:15px;line-height:1.7;max-width:640px;margin-bottom:40px;}

/* ── TABLEAU ── */
.dash-section{background:var(--deep);padding:80px 0;}
.dash-inner{max-width:1400px;margin:auto;padding:0 40px;}
.dash-inner .sec-title{color:white;}
.dash-inner .sec-sub{color:rgba(255,255,255,.5);}
.tableau-wrap{background:white;border-radius:18px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.45);}
.tableau-bar{background:var(--terra);padding:13px 22px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}
.tableau-bar span{color:white;font-size:13px;font-weight:600;}
.tableau-bar a{color:rgba(255,255,255,.9);font-size:11px;text-decoration:none;background:rgba(255,255,255,.18);padding:4px 12px;border-radius:20px;transition:background .2s;}
.tableau-bar a:hover{background:rgba(255,255,255,.35);}
.tableau-wrap iframe{width:100%;height:760px;border:none;display:block;}

/* ── INFOGRAFÍAS PDF SECTION ── */
.pdf-section{background:linear-gradient(160deg,#1B1B1B 0%,#2A1810 60%,#1B3A4A 100%);padding:80px 0;}
.pdf-inner{max-width:1400px;margin:auto;padding:0 40px;}
.pdf-inner .sec-title{color:white;}
.pdf-inner .sec-sub{color:rgba(255,255,255,.55);}
.pdf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;}
.pdf-card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:24px;display:flex;flex-direction:column;gap:14px;transition:all .2s;}
.pdf-card:hover{background:rgba(255,255,255,.1);transform:translateY(-3px);box-shadow:0 14px 40px rgba(0,0,0,.3);}
.pdf-card-top{display:flex;align-items:flex-start;gap:14px;}
.pdf-icon-box{width:52px;height:52px;background:var(--terra);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0;box-shadow:0 4px 14px rgba(181,52,26,.4);}
.pdf-card-meta{flex:1;min-width:0;}
.pdf-card-meta h3{font-family:'Playfair Display',serif;color:white;font-size:16px;line-height:1.3;margin-bottom:4px;}
.pdf-card-meta p{color:rgba(255,255,255,.5);font-size:12px;line-height:1.5;}
.pdf-dl-btn{display:flex;align-items:center;justify-content:center;gap:8px;background:var(--terra);color:white;padding:11px 20px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;transition:all .2s;margin-top:auto;}
.pdf-dl-btn:hover{background:#8f2612;box-shadow:0 6px 20px rgba(181,52,26,.4);}
.pdf-all-btn{display:inline-flex;align-items:center;gap:10px;background:rgba(255,255,255,.08);border:1.5px solid rgba(255,255,255,.2);color:white;padding:13px 28px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;transition:all .2s;margin-top:32px;}
.pdf-all-btn:hover{background:rgba(255,255,255,.15);}

/* ── TERRITORIES ── */
.ter-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:24px;}
.ter-card{background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.07);border:1px solid var(--border);transition:transform .2s,box-shadow .2s;cursor:pointer;}
.ter-card:hover{transform:translateY(-5px);box-shadow:0 16px 48px rgba(0,0,0,.15);}
.ter-photo{height:180px;background:linear-gradient(135deg,rgba(181,52,26,.85),rgba(27,27,27,.9));position:relative;overflow:hidden;}
.ter-photo img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .4s;}
.ter-card:hover .ter-photo img{transform:scale(1.06);}
.ter-icon-fallback{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:64px;opacity:.3;}
.ter-overlay{position:absolute;inset:0;background:linear-gradient(to bottom,transparent 30%,rgba(0,0,0,.7));}
.ter-name{position:absolute;bottom:12px;left:16px;color:white;font-family:'Playfair Display',serif;font-size:20px;font-weight:700;text-shadow:0 2px 8px rgba(0,0,0,.5);}
.ter-region{position:absolute;bottom:12px;right:12px;background:rgba(201,129,10,.85);color:white;font-size:10px;font-weight:700;padding:3px 8px;border-radius:10px;letter-spacing:.5px;}
.ter-body{padding:20px;}
.ter-desc{font-size:12px;color:var(--muted);margin-bottom:14px;line-height:1.5;}
.ter-key-fact{background:rgba(181,52,26,.08);border-left:3px solid var(--terra);padding:8px 12px;border-radius:0 6px 6px 0;font-size:12px;color:var(--terra);font-weight:500;margin-bottom:14px;}
.sr{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid rgba(0,0,0,.05);font-size:13px;}
.sr:last-child{border:none;}
.sr .k{color:var(--muted);}
.sr .v{font-weight:700;color:var(--terra);}
.sr .vg{font-weight:700;color:#2E7D32;}
.sr .vw{font-weight:700;color:var(--gold);}
.ter-cta{display:flex;align-items:center;justify-content:center;gap:8px;background:var(--deep);color:white;padding:10px;font-size:13px;font-weight:600;margin-top:16px;border-radius:8px;transition:background .2s;}
.ter-card:hover .ter-cta{background:var(--terra);}

/* ── TERRITORY DETAIL MODAL ── */
.ter-modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:700;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px);}
.ter-modal-overlay.open{display:flex;}
.ter-modal{background:white;border-radius:20px;max-width:800px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 40px 100px rgba(0,0,0,.5);}
.ter-modal-hero{height:260px;position:relative;overflow:hidden;border-radius:20px 20px 0 0;}
.ter-modal-hero img{width:100%;height:100%;object-fit:cover;}
.ter-modal-hero-fallback{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:80px;}
.ter-modal-hero::after{content:'';position:absolute;inset:0;background:linear-gradient(to bottom,transparent 30%,rgba(27,27,27,.85));}
.ter-modal-hero-info{position:absolute;bottom:20px;left:24px;z-index:2;}
.ter-modal-hero-info h2{font-family:'Playfair Display',serif;color:white;font-size:32px;font-weight:900;text-shadow:0 2px 12px rgba(0,0,0,.5);}
.ter-modal-hero-info p{color:rgba(255,255,255,.8);font-size:13px;margin-top:4px;}
.ter-modal-close{position:absolute;top:16px;right:16px;z-index:10;background:rgba(255,255,255,.15);border:none;color:white;width:36px;height:36px;border-radius:50%;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);transition:background .2s;}
.ter-modal-close:hover{background:var(--terra);}
.ter-modal-body{padding:28px;}
.ter-modal-tabs{display:flex;gap:8px;margin-bottom:24px;border-bottom:2px solid rgba(0,0,0,.07);padding-bottom:0;}
.ter-modal-tab{padding:10px 18px;font-size:13px;font-weight:600;cursor:pointer;border:none;background:none;border-bottom:3px solid transparent;margin-bottom:-2px;color:var(--muted);transition:all .2s;font-family:'DM Sans',sans-serif;}
.ter-modal-tab.active{color:var(--terra);border-bottom-color:var(--terra);}
.ter-modal-panel{display:none;}
.ter-modal-panel.active{display:block;}
/* Stats grid in modal */
.ter-stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px;}
.ter-stat-card{background:var(--cream);border-radius:12px;padding:16px;text-align:center;border:1px solid var(--border);}
.ter-stat-card .tsv{font-family:'Playfair Display',serif;font-size:28px;font-weight:900;line-height:1;}
.ter-stat-card .tsk{font-size:11px;color:var(--muted);margin-top:4px;line-height:1.4;}
.ter-stat-card.red .tsv{color:var(--terra);}
.ter-stat-card.gold .tsv{color:var(--gold);}
.ter-stat-card.green .tsv{color:var(--green);}
/* Bar charts */
.ter-bar-group{margin-bottom:16px;}
.ter-bar-label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px;}
.ter-bar-label span:first-child{color:var(--muted);}
.ter-bar-label span:last-child{font-weight:700;}
.ter-bar-track{background:rgba(0,0,0,.07);border-radius:6px;height:10px;overflow:hidden;}
.ter-bar-fill{height:100%;border-radius:6px;transition:width 0.8s ease;}
.ter-bar-fill.red{background:linear-gradient(90deg,var(--terra),#e05a3a);}
.ter-bar-fill.gold{background:linear-gradient(90deg,var(--gold),#e8a02a);}
.ter-bar-fill.green{background:linear-gradient(90deg,var(--green),#4a9a72);}
.ter-bar-fill.sky{background:linear-gradient(90deg,var(--sky),#2a7fa0);}
/* Lists in modal */
.ter-list{list-style:none;}
.ter-list li{padding:10px 0;border-bottom:1px solid rgba(0,0,0,.06);font-size:14px;display:flex;align-items:flex-start;gap:10px;line-height:1.5;}
.ter-list li:last-child{border:none;}
.ter-list li::before{content:'•';color:var(--terra);font-size:18px;line-height:1;flex-shrink:0;}
/* History text */
.ter-history-text{font-size:15px;line-height:1.8;color:var(--deep);margin-bottom:20px;}

/* ── MEDIA GALLERY ── */
.gal-section{background:#EFE7DA;padding:80px 0;}
.gal-inner{max-width:1400px;margin:auto;padding:0 40px;}
.media-tabs{display:flex;gap:10px;margin-bottom:28px;flex-wrap:wrap;}
.mtab{background:white;border:2px solid var(--border);color:var(--muted);padding:9px 20px;border-radius:30px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;display:flex;align-items:center;gap:7px;}
.mtab:hover{border-color:var(--terra);color:var(--terra);}
.mtab.active{background:var(--terra);border-color:var(--terra);color:white;}
.mtab .count{background:rgba(255,255,255,.25);border-radius:20px;padding:2px 7px;font-size:11px;}
.mtab:not(.active) .count{background:rgba(181,52,26,.12);color:var(--terra);}
.upload-zone{border:2px dashed rgba(181,52,26,.4);border-radius:14px;padding:28px;text-align:center;cursor:pointer;transition:all .2s;background:rgba(181,52,26,.04);margin-bottom:28px;}
.upload-zone:hover{border-color:var(--terra);background:rgba(181,52,26,.09);}
.upload-zone .uz-icon{font-size:32px;margin-bottom:8px;}
.upload-zone strong{font-size:15px;color:var(--terra);display:block;margin-bottom:4px;}
.upload-zone p{color:var(--muted);font-size:12px;line-height:1.5;}
#mediaInput{display:none;}
.photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;}
.gal-item{aspect-ratio:1;border-radius:10px;overflow:hidden;cursor:pointer;position:relative;background:rgba(181,52,26,.12);}
.gal-item img{width:100%;height:100%;object-fit:cover;transition:transform .35s;display:block;}
.gal-item:hover img{transform:scale(1.07);}
.gal-item .ov{position:absolute;inset:0;background:rgba(0,0,0,0);transition:background .3s;display:flex;align-items:center;justify-content:center;}
.gal-item:hover .ov{background:rgba(181,52,26,.4);}
.gal-item .ov span{color:white;font-size:28px;opacity:0;transition:opacity .3s;}
.gal-item:hover .ov span{opacity:1;}
.video-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:24px;}
.video-card{background:white;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08);border:1px solid var(--border);}
.video-card video{width:100%;display:block;max-height:220px;background:#000;object-fit:contain;}
.video-card .vc-info{padding:14px 16px;}
.video-card .vc-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.video-card .vc-meta{font-size:11px;color:var(--muted);margin-top:3px;display:flex;align-items:center;gap:6px;}
.vc-badge{background:rgba(27,94,122,.1);color:var(--sky);border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700;text-transform:uppercase;}
.audio-grid{display:flex;flex-direction:column;gap:16px;}
.audio-card{background:white;border-radius:14px;padding:20px 24px;box-shadow:0 4px 20px rgba(0,0,0,.07);border:1px solid var(--border);display:flex;align-items:center;gap:20px;transition:transform .2s;}
.audio-card:hover{transform:translateY(-2px);}
.audio-thumb{width:58px;height:58px;border-radius:50%;background:linear-gradient(135deg,var(--terra),var(--gold));flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:22px;box-shadow:0 4px 14px rgba(181,52,26,.3);}
.audio-info{flex:1;min-width:0;}
.audio-title{font-family:'Playfair Display',serif;font-size:15px;font-weight:700;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.audio-meta{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px;margin-bottom:8px;}
.audio-badge{background:rgba(181,52,26,.1);color:var(--terra);border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700;text-transform:uppercase;}
.waveform{display:flex;align-items:center;gap:2px;height:20px;margin-bottom:8px;}
.waveform span{display:block;width:3px;border-radius:2px;background:var(--terra);opacity:.55;animation:wave 1.2s ease-in-out infinite;}
.waveform span:nth-child(1){height:7px;animation-delay:0s;}.waveform span:nth-child(2){height:14px;animation-delay:.1s;}.waveform span:nth-child(3){height:20px;animation-delay:.2s;}.waveform span:nth-child(4){height:10px;animation-delay:.3s;}.waveform span:nth-child(5){height:18px;animation-delay:.4s;}.waveform span:nth-child(6){height:7px;animation-delay:.5s;}.waveform span:nth-child(7){height:13px;animation-delay:.6s;}.waveform span:nth-child(8){height:16px;animation-delay:.2s;}
@keyframes wave{0%,100%{transform:scaleY(1);}50%{transform:scaleY(.35);}}
.audio-card:not(:hover) .waveform span{animation-play-state:paused;}
audio{width:100%;accent-color:var(--terra);}
.empty-state{text-align:center;padding:56px 20px;color:var(--muted);}
.empty-state .es-icon{font-size:48px;margin-bottom:14px;opacity:.45;}
.empty-state h3{font-family:'Playfair Display',serif;font-size:18px;margin-bottom:6px;color:var(--deep);}
.empty-state p{font-size:13px;line-height:1.6;}

/* ── NEWS ── */
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:28px;}
.nc{background:white;border-radius:14px;overflow:hidden;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.06);transition:transform .2s;}
.nc:hover{transform:translateY(-3px);}
.nc{transition:transform .2s,box-shadow .2s;overflow:hidden;}
.nc:hover{transform:translateY(-4px);box-shadow:0 16px 48px rgba(0,0,0,.14);}
.nc-top{height:200px;position:relative;overflow:hidden;}
.nc-top img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .4s;}
.nc:hover .nc-top img{transform:scale(1.05);}
.nc-top-overlay{position:absolute;inset:0;background:linear-gradient(to bottom,transparent 40%,rgba(0,0,0,.6));}
.ntag{position:absolute;top:14px;left:14px;background:var(--terra);color:white;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;padding:5px 12px;border-radius:20px;box-shadow:0 2px 8px rgba(0,0,0,.25);}
.nc-body{padding:22px;}
.nc-body h3{font-family:'Playfair Display',serif;font-size:17px;margin-bottom:8px;line-height:1.4;}
.nc-body p{color:var(--muted);font-size:13px;line-height:1.6;}
.nc-foot{padding:14px 22px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.nc-foot a{color:var(--terra);font-size:13px;font-weight:600;text-decoration:none;transition:color .2s;}
.nc-foot a:hover{color:#8f2612;}
.nc-meta{color:var(--muted);font-size:12px;}

/* ── METHODOLOGY ── */
.meth-section{background:var(--deep);padding:80px 0;}
.meth-inner{max-width:1400px;margin:auto;padding:0 40px;}
.meth-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px;margin-top:40px;}
.mc{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:28px;}
.mc-link{text-decoration:none;display:block;position:relative;cursor:pointer;transition:all .25s;overflow:hidden;}
.mc-link:hover{background:rgba(255,255,255,.1);border-color:var(--gold);transform:translateY(-4px);box-shadow:0 16px 40px rgba(0,0,0,.35);}
.mc-link .mc-arrow{position:absolute;top:16px;right:16px;color:var(--gold);font-size:20px;opacity:0;transform:translateX(-8px);transition:all .25s;}
.mc-link:hover .mc-arrow{opacity:1;transform:translateX(0);}
.mc-link h3{color:white;}
.mc-link p{color:rgba(255,255,255,.55);font-size:13px;line-height:1.6;}
.mc-goto{margin-top:14px;font-size:12px;font-weight:700;color:var(--gold);letter-spacing:.5px;opacity:0;transition:opacity .25s;}
.mc-link:hover .mc-goto{opacity:1;}
.mc .ico{font-size:30px;margin-bottom:12px;}
.mc h3{color:white;font-family:'Playfair Display',serif;font-size:18px;margin-bottom:8px;}
.mc p{color:rgba(255,255,255,.55);font-size:13px;line-height:1.6;}

/* ── WHATSAPP GROUP BUTTONS ── */
.wa-group-btn{display:inline-flex;align-items:center;gap:7px;background:var(--wa);color:white;padding:9px 16px;border-radius:20px;font-size:13px;font-weight:600;text-decoration:none;transition:background .2s;}
.wa-group-btn:hover{background:var(--wa-dark);}

/* ── WHATSAPP-LIKE COMMUNITY MODULE ── */
.wa-section{background:#f0f2f5;padding:80px 0;}
.wa-inner{max-width:1400px;margin:auto;padding:0 40px;}
.wa-container{background:white;border-radius:20px;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.12);border:1px solid rgba(0,0,0,.07);display:grid;grid-template-columns:320px 1fr;height:640px;}
/* Sidebar */
.wa-sidebar{border-right:1px solid rgba(0,0,0,.07);display:flex;flex-direction:column;background:#fff;}
.wa-sidebar-header{background:var(--green);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;}
.wa-sidebar-header h3{color:white;font-size:16px;font-weight:700;}
.wa-sidebar-header-btns{display:flex;gap:8px;}
.wa-sidebar-header-btns button{background:rgba(255,255,255,.15);border:none;color:white;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:background .2s;}
.wa-sidebar-header-btns button:hover{background:rgba(255,255,255,.3);}
.wa-search{padding:10px 14px;border-bottom:1px solid rgba(0,0,0,.06);}
.wa-search input{width:100%;background:#f0f2f5;border:none;border-radius:20px;padding:8px 16px;font-size:13px;outline:none;font-family:'DM Sans',sans-serif;}
.wa-contacts{flex:1;overflow-y:auto;}
.wa-contact{display:flex;align-items:center;gap:12px;padding:12px 16px;cursor:pointer;border-bottom:1px solid rgba(0,0,0,.04);transition:background .15s;}
.wa-contact:hover{background:#f5f5f5;}
.wa-contact.active{background:#e8f5e9;}
.wa-avatar{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;background:linear-gradient(135deg,var(--terra),var(--gold));}
.wa-contact-info{flex:1;min-width:0;}
.wa-contact-name{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.wa-contact-last{font-size:12px;color:#667781;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.wa-contact-meta{display:flex;flex-direction:column;align-items:flex-end;gap:4px;}
.wa-time{font-size:11px;color:#667781;}
.wa-badge{background:var(--wa);color:white;border-radius:50%;width:18px;height:18px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;}
.wa-online{width:10px;height:10px;border-radius:50%;background:var(--wa);flex-shrink:0;}
/* Chat area */
.wa-chat{display:flex;flex-direction:column;background:#e5ddd5;}
.wa-chat-header{background:var(--green);padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}
.wa-chat-header-left{display:flex;align-items:center;gap:12px;}
.wa-chat-avatar{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--terra),var(--gold));display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.wa-chat-name{color:white;font-size:15px;font-weight:600;}
.wa-chat-status{color:rgba(255,255,255,.7);font-size:11px;}
.wa-chat-actions{display:flex;gap:4px;}
.wa-chat-actions button{background:rgba(255,255,255,.15);border:none;color:white;width:36px;height:36px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s;font-size:14px;}
.wa-chat-actions button:hover{background:rgba(255,255,255,.3);}
.wa-messages{flex:1;overflow-y:auto;padding:20px 16px;display:flex;flex-direction:column;gap:10px;}
.wa-msg{max-width:72%;display:flex;flex-direction:column;}
.wa-msg.sent{align-self:flex-end;}
.wa-msg.recv{align-self:flex-start;}
.wa-bubble{padding:8px 14px 6px;border-radius:8px;font-size:14px;line-height:1.5;position:relative;box-shadow:0 1px 3px rgba(0,0,0,.12);}
.wa-msg.sent .wa-bubble{background:#dcf8c6;border-radius:8px 8px 2px 8px;}
.wa-msg.recv .wa-bubble{background:white;border-radius:8px 8px 8px 2px;}
.wa-bubble-time{font-size:10px;color:#667781;margin-top:2px;text-align:right;}
.wa-date-separator{text-align:center;margin:10px 0;}
.wa-date-separator span{background:rgba(255,255,255,.85);padding:4px 12px;border-radius:10px;font-size:12px;color:#667781;box-shadow:0 1px 3px rgba(0,0,0,.1);}
.wa-input-bar{background:white;padding:10px 14px;display:flex;align-items:center;gap:10px;border-top:1px solid rgba(0,0,0,.07);}
.wa-input-bar button.wa-attach{background:none;border:none;color:#667781;cursor:pointer;width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;transition:background .2s;font-size:18px;}
.wa-input-bar button.wa-attach:hover{background:#f0f2f5;}
.wa-input-bar input{flex:1;background:#f0f2f5;border:none;border-radius:20px;padding:10px 16px;font-size:14px;outline:none;font-family:'DM Sans',sans-serif;}
.wa-input-bar button.wa-mic{background:var(--wa);border:none;color:white;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:background .2s;font-size:16px;flex-shrink:0;}
.wa-input-bar button.wa-mic:hover{background:var(--wa-dark);}
/* Call buttons */
.wa-call-bar{background:rgba(37,211,102,.08);border:1px solid rgba(37,211,102,.2);border-radius:12px;padding:12px 16px;margin:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
.wa-call-bar-text{flex:1;font-size:13px;color:var(--green);font-weight:500;}
.wa-call-btn{display:flex;align-items:center;gap:6px;background:var(--wa);color:white;border:none;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:background .2s;}
.wa-call-btn:hover{background:var(--wa-dark);}
.wa-call-btn.video{background:var(--sky);}
.wa-call-btn.video:hover{background:#144d63;}

/* ── CHATBOT ── */
.fab{position:fixed;bottom:32px;right:32px;z-index:400;width:56px;height:56px;background:var(--terra);border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 8px 28px rgba(181,52,26,.45);transition:transform .2s;border:none;color:white;font-size:22px;}
.fab:hover{transform:scale(1.1);}
.chat-panel{position:fixed;bottom:100px;right:32px;z-index:400;width:360px;background:white;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.22);border:1px solid var(--border);display:none;flex-direction:column;overflow:hidden;}
.chat-panel.open{display:flex;}
.chat-hd{background:var(--terra);color:white;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;}
.chat-hd h4{font-size:15px;font-weight:600;}
.chat-hd p{font-size:11px;opacity:.75;margin-top:2px;}
.chat-msgs{padding:18px;min-height:200px;max-height:300px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;font-size:14px;line-height:1.5;}
.mbot{background:#F5EDE5;border-radius:12px 12px 12px 4px;padding:10px 14px;max-width:86%;align-self:flex-start;}
.musr{background:var(--terra);color:white;border-radius:12px 12px 4px 12px;padding:10px 14px;max-width:86%;align-self:flex-end;}
.chat-in{display:flex;border-top:1px solid var(--border);}
.chat-in input{flex:1;border:none;padding:14px 16px;font-family:'DM Sans',sans-serif;font-size:14px;outline:none;color:var(--deep);}
.chat-in button{background:var(--terra);color:white;border:none;padding:0 20px;cursor:pointer;font-size:16px;}

/* ── FOOTER ── */
footer{background:var(--deep);color:rgba(255,255,255,.65);padding:60px 40px 28px;}
.ft-grid{max-width:1400px;margin:auto;display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:48px;margin-bottom:48px;}
.ft-brand h3{font-family:'Playfair Display',serif;color:white;font-size:22px;margin-bottom:10px;}
.ft-brand p{font-size:13px;line-height:1.7;max-width:280px;}
.ft-logo{display:flex;align-items:center;gap:12px;margin-top:16px;}
.ft-logo img{width:42px;height:42px;border-radius:50%;object-fit:contain;background:white;padding:3px;}
.ft-social{display:flex;gap:10px;margin-top:16px;}
.ft-social a{width:36px;height:36px;border-radius:8px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;transition:background .2s;}
.ft-social a:hover{background:var(--terra);}
.ft-col h4{color:white;font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:14px;}
.ft-col ul{list-style:none;display:flex;flex-direction:column;gap:10px;}
.ft-col a{color:rgba(255,255,255,.5);text-decoration:none;font-size:13px;transition:color .2s;display:flex;align-items:center;gap:7px;}
.ft-col a:hover{color:var(--gold);}
.ft-bot{max-width:1400px;margin:auto;padding-top:24px;border-top:1px solid rgba(255,255,255,.1);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;font-size:12px;color:rgba(255,255,255,.3);}

/* ── LIGHTBOX ── */
.lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:800;align-items:center;justify-content:center;padding:20px;}
.lb.open{display:flex;}
.lb img{max-width:90vw;max-height:85vh;border-radius:10px;object-fit:contain;}
.lb-x{position:absolute;top:20px;right:24px;color:white;font-size:36px;cursor:pointer;background:none;border:none;line-height:1;}

/* ── RESPONSIVE ── */
@media(max-width:960px){
  .hero{grid-template-columns:1fr;padding:60px 24px;min-height:auto;}
  .hero-photo{display:none;}
  .section,.gal-inner,.dash-inner,.meth-inner,.pdf-inner,.wa-inner{padding-left:24px;padding-right:24px;}
  .ft-grid{grid-template-columns:1fr 1fr;}
  .audio-card{flex-direction:column;align-items:flex-start;}
  .wa-container{grid-template-columns:1fr;height:auto;}
  .wa-sidebar{display:none;}
  .ter-stats-grid{grid-template-columns:1fr 1fr;}
}
@media(max-width:600px){
  nav{display:none;}
  .ft-grid{grid-template-columns:1fr;}
  .chat-panel{width:calc(100vw - 40px);right:20px;}
  .video-grid{grid-template-columns:1fr;}
  .ter-stats-grid{grid-template-columns:1fr;}
  .ter-modal-tabs{overflow-x:auto;}
}

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.hero-content>*{animation:fadeUp .55s both;}
.hero-eyebrow{animation-delay:.1s;}.hero h2{animation-delay:.2s;}.hero-desc{animation-delay:.3s;}.hero-btns{animation-delay:.4s;}.hero-stats{animation-delay:.5s;}

/* ── PWA INSTALL BANNER ── */
.pwa-banner{position:fixed;bottom:0;left:0;right:0;z-index:500;background:var(--deep);border-top:3px solid var(--terra);padding:16px 24px;display:none;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;box-shadow:0 -8px 32px rgba(0,0,0,.3);}
.pwa-banner.show{display:flex;}
.pwa-banner-left{display:flex;align-items:center;gap:14px;}
.pwa-banner-icon{width:48px;height:48px;border-radius:12px;overflow:hidden;flex-shrink:0;}
.pwa-banner-icon img{width:100%;height:100%;object-fit:cover;}
.pwa-banner-text h4{color:white;font-size:15px;font-weight:600;margin-bottom:2px;}
.pwa-banner-text p{color:rgba(255,255,255,.55);font-size:12px;}
.pwa-banner-btns{display:flex;gap:10px;align-items:center;}
.pwa-install-btn{background:var(--terra);color:white;border:none;padding:10px 22px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:background .2s;}
.pwa-install-btn:hover{background:#8f2612;}
.pwa-dismiss-btn{background:none;border:1px solid rgba(255,255,255,.2);color:rgba(255,255,255,.6);padding:10px 16px;border-radius:8px;font-size:13px;cursor:pointer;font-family:'DM Sans',sans-serif;transition:all .2s;}
.pwa-dismiss-btn:hover{border-color:rgba(255,255,255,.5);color:white;}
.pwa-status{position:fixed;top:80px;right:20px;z-index:600;background:var(--deep);border:1px solid rgba(255,255,255,.12);border-left:3px solid var(--gold);color:white;padding:12px 18px;border-radius:10px;font-size:13px;display:none;box-shadow:0 8px 24px rgba(0,0,0,.3);}
.pwa-status.show{display:block;}
@media(max-width:600px){.fab{bottom:90px;}}

/* ── DARK MODE ── */
body.dark{--cream:#1A1A1A;--deep:#F7F1E8;--muted:#A89B8E;--border:rgba(181,52,26,0.3);background:#1A1A1A;color:#F7F1E8;}
body.dark .ter-card{background:#2A2A2A;border-color:rgba(255,255,255,.1);}
body.dark .ter-card .ter-body{background:#2A2A2A;}
body.dark .ter-key-fact{background:rgba(181,52,26,.15);}
body.dark .nc{background:#2A2A2A;}
body.dark .audio-card,.body.dark .video-card{background:#2A2A2A;}
body.dark .wa-sidebar,.body.dark .wa-chat{background:#1A1A1A;}
body.dark header{background:#0D0D0D;}
.dark-toggle{background:none;border:1.5px solid rgba(255,255,255,.25);color:rgba(255,255,255,.75);padding:6px 12px;border-radius:20px;cursor:pointer;font-size:12px;font-family:'DM Sans',sans-serif;transition:all .2s;display:flex;align-items:center;gap:6px;}
.dark-toggle:hover{background:rgba(255,255,255,.1);}

/* ── SEARCH BAR ── */
.search-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:900;align-items:flex-start;justify-content:center;padding:80px 20px;backdrop-filter:blur(4px);}
.search-overlay.open{display:flex;}
.search-box{background:white;border-radius:16px;width:100%;max-width:640px;overflow:hidden;box-shadow:0 40px 100px rgba(0,0,0,.5);}
.search-box-top{display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid rgba(0,0,0,.08);}
.search-box-top input{flex:1;border:none;font-size:18px;outline:none;font-family:'DM Sans',sans-serif;color:var(--deep);}
.search-box-top button{background:none;border:none;font-size:22px;cursor:pointer;color:var(--muted);padding:0 8px;}
.search-results{max-height:420px;overflow-y:auto;}
.search-result-item{display:flex;align-items:center;gap:14px;padding:14px 20px;border-bottom:1px solid rgba(0,0,0,.05);cursor:pointer;transition:background .15s;text-decoration:none;color:var(--deep);}
.search-result-item:hover{background:rgba(181,52,26,.06);}
.search-result-icon{width:38px;height:38px;border-radius:10px;background:rgba(181,52,26,.1);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}
.search-result-title{font-size:14px;font-weight:600;}
.search-result-desc{font-size:12px;color:var(--muted);margin-top:2px;}
.search-result-type{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;padding:2px 7px;border-radius:10px;background:rgba(181,52,26,.12);color:var(--terra);}
.search-empty{padding:32px;text-align:center;color:var(--muted);font-size:14px;}

/* ── COMPARE TOOL ── */
.compare-section{background:linear-gradient(160deg,#1B3A4A,#1B1B1B);padding:80px 0;}
.compare-inner{max-width:1400px;margin:auto;padding:0 40px;}
.compare-inner .sec-title{color:white;}
.compare-inner .sec-sub{color:rgba(255,255,255,.5);}
.compare-selects{display:flex;gap:16px;align-items:center;margin-bottom:32px;flex-wrap:wrap;}
.compare-selects select{flex:1;min-width:200px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:white;padding:12px 16px;border-radius:10px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;cursor:pointer;}
.compare-selects select option{background:#1B1B1B;color:white;}
.compare-btn{background:var(--terra);color:white;border:none;padding:12px 28px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:background .2s;}
.compare-btn:hover{background:#8f2612;}
.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;}
.compare-card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:24px;}
.compare-card h3{color:white;font-family:'Playfair Display',serif;font-size:20px;margin-bottom:20px;}
.compare-bar-group{margin-bottom:14px;}
.compare-bar-label{display:flex;justify-content:space-between;font-size:12px;color:rgba(255,255,255,.65);margin-bottom:5px;}
.compare-bar-track{background:rgba(255,255,255,.1);border-radius:6px;height:10px;overflow:hidden;}
.compare-bar-fill{height:100%;border-radius:6px;transition:width 0.8s ease;}
@media(max-width:600px){.compare-grid{grid-template-columns:1fr;}}

/* ── EVENTS SECTION ── */
.events-section{background:var(--cream);padding:80px 0;}
.events-inner{max-width:1400px;margin:auto;padding:0 40px;}
.events-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;}
.event-card{background:white;border-radius:14px;padding:22px;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.06);transition:transform .2s,box-shadow .2s;display:flex;gap:16px;}
.event-card:hover{transform:translateY(-3px);box-shadow:0 8px 28px rgba(0,0,0,.12);}
.event-date-box{background:var(--terra);color:white;border-radius:10px;padding:10px 14px;text-align:center;flex-shrink:0;min-width:58px;}
.event-date-box .ev-day{font-family:'Playfair Display',serif;font-size:24px;font-weight:900;line-height:1;}
.event-date-box .ev-mon{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;opacity:.85;}
.event-info h4{font-family:'Playfair Display',serif;font-size:16px;margin-bottom:6px;line-height:1.3;}
.event-info p{font-size:12px;color:var(--muted);margin-bottom:8px;line-height:1.5;}
.event-meta{display:flex;gap:8px;flex-wrap:wrap;}
.event-tag{background:rgba(181,52,26,.1);color:var(--terra);font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;text-transform:uppercase;}
.event-link{display:inline-flex;align-items:center;gap:5px;background:var(--wa);color:white;font-size:11px;font-weight:600;padding:4px 10px;border-radius:10px;text-decoration:none;margin-top:8px;transition:background .2s;}
.event-link:hover{background:var(--wa-dark);}

/* ── TESTIMONIALS ── */
.test-section{background:#EFE7DA;padding:80px 0;}
.test-inner{max-width:1400px;margin:auto;padding:0 40px;}
.test-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:24px;margin-bottom:40px;}
.test-card{background:white;border-radius:14px;padding:24px;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.06);}
.test-card-top{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.test-avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,var(--terra),var(--gold));display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.test-name{font-weight:700;font-size:14px;}
.test-territory{font-size:11px;color:var(--muted);}
.test-text{font-size:14px;line-height:1.7;color:var(--deep);font-style:italic;}
.test-ts{font-size:11px;color:var(--muted);margin-top:10px;}
.test-form{background:white;border-radius:16px;padding:32px;border:1px solid var(--border);box-shadow:0 4px 20px rgba(0,0,0,.07);}
.test-form h3{font-family:'Playfair Display',serif;font-size:22px;margin-bottom:8px;}
.test-form p{color:var(--muted);font-size:13px;margin-bottom:24px;}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
.form-field{display:flex;flex-direction:column;gap:6px;}
.form-field label{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px;}
.form-field input,.form-field select,.form-field textarea{border:1.5px solid var(--border);border-radius:8px;padding:10px 14px;font-family:'DM Sans',sans-serif;font-size:14px;outline:none;transition:border-color .2s;color:var(--deep);}
.form-field input:focus,.form-field select:focus,.form-field textarea:focus{border-color:var(--terra);}
.form-field textarea{resize:vertical;min-height:100px;}
.form-submit{background:var(--terra);color:white;border:none;padding:13px 32px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:all .2s;display:inline-flex;align-items:center;gap:8px;}
.form-submit:hover{background:#8f2612;transform:translateY(-2px);}
.form-success{display:none;background:rgba(45,106,79,.1);border:1px solid rgba(45,106,79,.3);border-radius:10px;padding:14px 20px;color:var(--green);font-size:14px;font-weight:600;margin-top:16px;}

/* ── VISITOR COUNTER ── */
.visitor-bar{background:var(--deep);padding:12px 40px;display:flex;align-items:center;justify-content:center;gap:24px;flex-wrap:wrap;font-size:12px;color:rgba(255,255,255,.45);}
.visitor-bar span{display:flex;align-items:center;gap:6px;}
.visitor-count{color:var(--gold);font-weight:700;font-size:16px;font-family:'Playfair Display',serif;}

/* ── SCROLL TO TOP ── */
.scroll-top{position:fixed;bottom:32px;left:32px;z-index:400;width:44px;height:44px;background:var(--deep);border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.25);transition:all .2s;border:none;color:white;font-size:18px;opacity:0;pointer-events:none;}
.scroll-top.visible{opacity:1;pointer-events:auto;}
.scroll-top:hover{background:var(--terra);transform:translateY(-3px);}

/* ── MOBILE BOTTOM NAV ── */
.mobile-nav{display:none;position:fixed;bottom:0;left:0;right:0;background:var(--deep);border-top:2px solid var(--terra);z-index:350;padding:6px 0 env(safe-area-inset-bottom);}
.mobile-nav-inner{display:flex;justify-content:space-around;align-items:center;}
.mob-nav-btn{display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 10px;color:rgba(255,255,255,.5);text-decoration:none;font-size:10px;font-weight:600;transition:color .2s;border:none;background:none;cursor:pointer;font-family:'DM Sans',sans-serif;}
.mob-nav-btn:hover,.mob-nav-btn.active{color:var(--gold);}
.mob-nav-btn span:first-child{font-size:20px;}
@media(max-width:600px){
  .mobile-nav{display:block;}
  body{padding-bottom:70px;}
  .fab{bottom:90px;}
  .scroll-top{bottom:90px;}
}

/* ── SPLASH SCREEN ── */
.splash{position:fixed;inset:0;background:var(--deep);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;transition:opacity .5s,visibility .5s;}
.splash.hidden{opacity:0;visibility:hidden;pointer-events:none;}
.splash-logo{font-size:72px;animation:splashPulse 1.5s ease-in-out infinite;display:flex;align-items:center;justify-content:center;}
.splash-title{font-family:'Playfair Display',serif;color:white;font-size:28px;font-weight:900;}
.splash-sub{color:rgba(255,255,255,.5);font-size:13px;letter-spacing:2px;text-transform:uppercase;}
.splash-bar{width:200px;height:3px;background:rgba(255,255,255,.1);border-radius:3px;overflow:hidden;margin-top:10px;}
.splash-progress{height:100%;background:linear-gradient(90deg,var(--terra),var(--gold));border-radius:3px;animation:splashLoad 1.8s ease forwards;}
@keyframes splashPulse{0%,100%{transform:scale(1);}50%{transform:scale(1.08);}}
@keyframes splashLoad{from{width:0}to{width:100%}}

/* ── INTERACTIVE MAP ── */
.map-section{background:var(--cream);padding:80px 0;}
.map-inner{max-width:1400px;margin:auto;padding:0 40px;}
.colombia-map{position:relative;width:100%;max-width:700px;margin:0 auto;}
.colombia-map svg{width:100%;height:auto;}
.map-pin{position:absolute;transform:translate(-50%,-100%);cursor:pointer;z-index:10;transition:transform .2s;}
.map-pin:hover{transform:translate(-50%,-100%) scale(1.2);}
.map-pin .pin-dot{width:28px;height:28px;border-radius:50%;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center;font-size:14px;}
.map-pin .pin-label{background:var(--deep);color:white;font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;white-space:nowrap;margin-top:3px;text-align:center;}
.map-tooltip{display:none;position:absolute;background:var(--deep);color:white;border-radius:10px;padding:12px 16px;font-size:12px;z-index:20;min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,.3);pointer-events:none;}
.map-tooltip.visible{display:block;}

/* ── ACCESSIBILITY ── */
.acc-bar{position:fixed;top:0;left:0;right:0;height:36px;background:#000;display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:0 20px;z-index:1000;font-size:11px;}
.acc-btn{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:white;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;font-family:'DM Sans',sans-serif;transition:background .2s;}
.acc-btn:hover{background:rgba(255,255,255,.25);}
body.high-contrast{filter:contrast(1.5) grayscale(0.1);}
body.large-font{font-size:18px!important;}
body.large-font .hero h2{font-size:clamp(44px,5vw,72px)!important;}
.skip-link{position:absolute;top:-50px;left:10px;background:var(--terra);color:white;padding:8px 16px;border-radius:0 0 8px 8px;text-decoration:none;font-weight:700;z-index:9999;transition:top .2s;}
.skip-link:focus{top:0;}

/* ── KPI STRIP ── */
.kpi-strip{background:linear-gradient(135deg,var(--terra) 0%,#8f2612 100%);padding:24px 40px;}
.kpi-inner{max-width:1400px;margin:auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0;}
.kpi-item{text-align:center;padding:16px 24px;border-right:1px solid rgba(255,255,255,.15);}
.kpi-item:last-child{border:none;}
.kpi-num{font-family:'Playfair Display',serif;font-size:38px;font-weight:900;color:white;line-height:1;}
.kpi-lbl{font-size:11px;color:rgba(255,255,255,.7);margin-top:4px;letter-spacing:.5px;text-transform:uppercase;}
.kpi-sub{font-size:10px;color:rgba(255,255,255,.45);margin-top:2px;}
@media(max-width:600px){.kpi-strip{padding:16px 20px;}.kpi-item{padding:12px 10px;border-right:none;border-bottom:1px solid rgba(255,255,255,.1);}}

/* ── ABOUT / RESEARCH SECTION ── */
.about-section{background:var(--cream);padding:80px 0;}
.about-inner{max-width:1400px;margin:auto;padding:0 40px;}
.about-grid{display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:start;}
.about-objectives{display:flex;flex-direction:column;gap:14px;margin-top:24px;}
.obj-item{display:flex;align-items:flex-start;gap:14px;padding:16px;background:white;border-radius:12px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.05);}
.obj-num{width:32px;height:32px;border-radius:50%;background:var(--terra);color:white;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;}
.obj-text h4{font-size:14px;font-weight:700;margin-bottom:3px;}
.obj-text p{font-size:12px;color:var(--muted);line-height:1.5;}
.about-team{display:flex;flex-direction:column;gap:16px;}
.team-card{display:flex;align-items:center;gap:16px;padding:18px;background:white;border-radius:12px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.05);}
.team-avatar{width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,var(--terra),var(--gold));display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.team-info h4{font-size:15px;font-weight:700;margin-bottom:2px;}
.team-info p{font-size:12px;color:var(--muted);}
.team-role{display:inline-block;background:rgba(181,52,26,.1);color:var(--terra);font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;margin-top:4px;text-transform:uppercase;letter-spacing:.5px;}
.sources-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-top:24px;}
.source-card{background:white;border-radius:12px;padding:16px;border:1px solid var(--border);border-left:4px solid var(--terra);box-shadow:0 2px 8px rgba(0,0,0,.05);}
.source-card h4{font-size:13px;font-weight:700;margin-bottom:4px;}
.source-card p{font-size:11px;color:var(--muted);line-height:1.5;}
.source-tag{display:inline-block;background:rgba(27,94,122,.1);color:var(--sky);font-size:10px;font-weight:700;padding:2px 7px;border-radius:8px;margin-top:6px;}
@media(max-width:900px){.about-grid{grid-template-columns:1fr;gap:32px;}}

/* ── IMPACT DASHBOARD ── */
.impact-section{background:var(--deep);padding:60px 0;}
.impact-inner{max-width:1400px;margin:auto;padding:0 40px;}
.impact-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-top:32px;}
.impact-card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:24px;text-align:center;transition:background .2s;}
.impact-card:hover{background:rgba(255,255,255,.1);}
.impact-icon{font-size:28px;margin-bottom:10px;}
.impact-num{font-family:'Playfair Display',serif;font-size:36px;font-weight:900;color:var(--gold);line-height:1;}
.impact-label{font-size:11px;color:rgba(255,255,255,.5);margin-top:5px;text-transform:uppercase;letter-spacing:1px;}

/* ── DOWNLOAD CENTER ── */
.dl-section{background:#EFE7DA;padding:80px 0;}
.dl-inner{max-width:1400px;margin:auto;padding:0 40px;}
.dl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;}
.dl-card{background:white;border-radius:14px;padding:22px;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.06);display:flex;flex-direction:column;gap:12px;transition:transform .2s;}
.dl-card:hover{transform:translateY(-3px);}
.dl-card-top{display:flex;align-items:center;gap:12px;}
.dl-type-icon{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.dl-type-icon.pdf{background:rgba(181,52,26,.12);}
.dl-type-icon.csv{background:rgba(45,106,79,.12);}
.dl-type-icon.doc{background:rgba(27,94,122,.12);}
.dl-card-info h4{font-size:14px;font-weight:700;margin-bottom:2px;}
.dl-card-info p{font-size:11px;color:var(--muted);}
.dl-card-size{font-size:10px;color:var(--muted);display:flex;align-items:center;gap:6px;}
.dl-btn{display:flex;align-items:center;justify-content:center;gap:7px;padding:10px;border-radius:8px;font-size:12px;font-weight:700;text-decoration:none;transition:all .2s;margin-top:auto;}
.dl-btn.primary{background:var(--terra);color:white;}
.dl-btn.primary:hover{background:#8f2612;}
.dl-btn.secondary{background:rgba(181,52,26,.1);color:var(--terra);}
.dl-btn.secondary:hover{background:rgba(181,52,26,.2);}

/* ── AUTH MODAL ── */
.auth-modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:800;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px);}
.auth-modal-overlay.open{display:flex;}
.auth-modal{background:white;border-radius:20px;width:100%;max-width:420px;padding:36px;box-shadow:0 40px 100px rgba(0,0,0,.4);}
.auth-modal h2{font-family:'Playfair Display',serif;font-size:24px;margin-bottom:6px;}
.auth-modal p{color:var(--muted);font-size:13px;margin-bottom:24px;}
.auth-tabs{display:flex;border-bottom:2px solid var(--border);margin-bottom:24px;}
.auth-tab{padding:8px 20px;font-size:13px;font-weight:600;cursor:pointer;border:none;background:none;border-bottom:3px solid transparent;margin-bottom:-2px;color:var(--muted);transition:all .2s;font-family:'DM Sans',sans-serif;}
.auth-tab.active{color:var(--terra);border-bottom-color:var(--terra);}
.auth-field{margin-bottom:16px;}
.auth-field label{display:block;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;}
.auth-field input{width:100%;border:1.5px solid var(--border);border-radius:8px;padding:10px 14px;font-family:'DM Sans',sans-serif;font-size:14px;outline:none;transition:border-color .2s;}
.auth-field input:focus{border-color:var(--terra);}
.auth-submit{width:100%;background:var(--terra);color:white;border:none;padding:13px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;transition:background .2s;margin-top:8px;}
.auth-submit:hover{background:#8f2612;}
.auth-error{background:rgba(181,52,26,.1);border:1px solid rgba(181,52,26,.3);color:var(--terra);padding:10px 14px;border-radius:8px;font-size:13px;margin-top:12px;display:none;}
.auth-success{background:rgba(45,106,79,.1);border:1px solid rgba(45,106,79,.3);color:var(--green);padding:10px 14px;border-radius:8px;font-size:13px;margin-top:12px;display:none;}
.user-chip{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);padding:5px 12px 5px 6px;border-radius:20px;cursor:pointer;transition:background .2s;}
.user-chip:hover{background:rgba(255,255,255,.2);}
.user-chip-avatar{width:26px;height:26px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--deep);}
.user-chip-name{color:white;font-size:12px;font-weight:600;}

/* ── STORYTELLING ── */
.story-section{background:var(--deep);padding:80px 0;}
.story-inner{max-width:1400px;margin:auto;padding:0 40px;}
.story-timeline{position:relative;padding-left:32px;margin-top:40px;}
.story-timeline::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(to bottom,var(--terra),var(--gold),var(--green));}
.story-item{position:relative;margin-bottom:40px;padding-left:28px;}
.story-item::before{content:'';position:absolute;left:-37px;top:8px;width:14px;height:14px;border-radius:50%;background:var(--gold);border:3px solid var(--deep);box-shadow:0 0 0 3px var(--gold);}
.story-item-tag{display:inline-block;background:rgba(201,129,10,.2);color:var(--gold);font-size:10px;font-weight:700;padding:3px 10px;border-radius:10px;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;}
.story-item h3{font-family:'Playfair Display',serif;color:white;font-size:20px;margin-bottom:8px;line-height:1.3;}
.story-item p{color:rgba(255,255,255,.6);font-size:14px;line-height:1.7;max-width:640px;}
.story-item-media{margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;}
.story-media-chip{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);color:rgba(255,255,255,.7);padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;transition:background .2s;display:inline-flex;align-items:center;gap:6px;}
.story-media-chip:hover{background:rgba(181,52,26,.3);color:white;}

/* ── IMPROVED FOOTER ── */
.ft-legal{max-width:1400px;margin:auto;padding:16px 40px 0;border-top:1px solid rgba(255,255,255,.07);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:11px;color:rgba(255,255,255,.25);}
.ft-legal a{color:rgba(255,255,255,.35);text-decoration:none;transition:color .2s;}
.ft-legal a:hover{color:var(--gold);}

/* ── PRIVACY MODAL ── */
.privacy-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:900;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px);}
.privacy-modal.open{display:flex;}
.privacy-box{background:white;border-radius:16px;max-width:640px;width:100%;max-height:80vh;overflow-y:auto;padding:36px;box-shadow:0 40px 100px rgba(0,0,0,.4);}
.privacy-box h2{font-family:'Playfair Display',serif;font-size:24px;margin-bottom:16px;}
.privacy-box h3{font-size:15px;font-weight:700;margin:20px 0 8px;color:var(--terra);}
.privacy-box p{font-size:13px;color:var(--muted);line-height:1.7;margin-bottom:10px;}

/* ── RESEARCH QUESTION HERO BANNER ── */
.rq-banner{background:linear-gradient(135deg,#1B1B1B 0%,#2A1810 50%,#1B3A4A 100%);border-left:6px solid var(--gold);border-radius:16px;padding:36px 40px;margin:40px 0 0;position:relative;overflow:hidden;}
.rq-banner::before{content:'"';position:absolute;top:-20px;left:20px;font-size:180px;color:rgba(201,129,10,.08);font-family:'Playfair Display',serif;line-height:1;pointer-events:none;}
.rq-banner .rq-label{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--gold);margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.rq-banner .rq-text{font-family:'Playfair Display',serif;font-size:clamp(16px,2vw,22px);color:white;line-height:1.6;font-style:italic;margin-bottom:16px;}
.rq-banner .rq-source{font-size:11px;color:rgba(255,255,255,.4);letter-spacing:.5px;}

/* ── METHODOLOGY VISUAL PIPELINE ── */
.pipeline-wrap{margin-top:40px;overflow-x:auto;padding-bottom:10px;}
.pipeline{display:flex;align-items:center;gap:0;min-width:700px;}
.pipe-step{flex:1;text-align:center;position:relative;}
.pipe-step:not(:last-child)::after{content:'→';position:absolute;right:-18px;top:50%;transform:translateY(-50%);color:var(--gold);font-size:22px;font-weight:700;z-index:2;}
.pipe-box{background:rgba(255,255,255,.06);border:1.5px solid rgba(255,255,255,.12);border-radius:12px;padding:18px 12px;margin:0 8px;transition:all .2s;cursor:default;}
.pipe-step:hover .pipe-box{background:rgba(201,129,10,.15);border-color:var(--gold);}
.pipe-icon{font-size:28px;margin-bottom:8px;}
.pipe-title{color:white;font-size:12px;font-weight:700;margin-bottom:4px;line-height:1.3;}
.pipe-desc{color:rgba(255,255,255,.45);font-size:10px;line-height:1.4;}
.pipe-source{display:inline-block;background:rgba(181,52,26,.2);color:var(--gold);font-size:9px;font-weight:700;padding:2px 6px;border-radius:6px;margin-top:5px;letter-spacing:.5px;}

/* ── DATA PROVENANCE / CITATIONS on territory cards ── */
.ter-provenance{background:rgba(27,94,122,.06);border-top:1px solid rgba(27,94,122,.15);padding:10px 16px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;}
.prov-tag{display:inline-flex;align-items:center;gap:4px;background:rgba(27,94,122,.12);color:var(--sky);font-size:9px;font-weight:700;padding:3px 8px;border-radius:8px;text-transform:uppercase;letter-spacing:.5px;}

/* ── OPEN DATA DOWNLOAD CENTER (CSV section) ── */
.csv-section{background:var(--cream);padding:60px 0;}
.csv-inner{max-width:1400px;margin:auto;padding:0 40px;}
.csv-tree{background:white;border-radius:14px;padding:28px;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.06);font-family:'DM Sans',monospace;font-size:13px;line-height:1.9;}
.csv-tree .tree-root{color:var(--terra);font-weight:700;font-size:15px;margin-bottom:4px;}
.csv-tree .tree-item{display:flex;align-items:center;gap:10px;padding:6px 0 6px 24px;border-bottom:1px solid rgba(0,0,0,.04);color:var(--deep);}
.csv-tree .tree-item:last-child{border:none;}
.csv-tree .tree-icon{font-size:16px;flex-shrink:0;}
.csv-tree .tree-name{flex:1;font-weight:600;}
.csv-tree .tree-meta{font-size:11px;color:var(--muted);}
.csv-tree .tree-badge{background:rgba(45,106,79,.1);color:var(--green);font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;white-space:nowrap;}
.csv-dl-btn{display:inline-flex;align-items:center;gap:5px;background:var(--terra);color:white;padding:4px 12px;border-radius:6px;font-size:11px;font-weight:700;text-decoration:none;transition:background .2s;white-space:nowrap;}
.csv-dl-btn:hover{background:#8f2612;}
.csv-dl-btn.json{background:var(--sky);}
.csv-dl-btn.json:hover{background:#144d63;}

/* ── COMMUNITY PARTICIPATION UPGRADE ── */
.part-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;margin-top:28px;}
.part-card{background:white;border-radius:14px;padding:22px;border:1px solid var(--border);box-shadow:0 2px 12px rgba(0,0,0,.05);border-top:4px solid var(--terra);}
.part-card h4{font-family:'Playfair Display',serif;font-size:16px;margin-bottom:6px;}
.part-card p{font-size:12px;color:var(--muted);line-height:1.6;margin-bottom:14px;}
.part-flow{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;flex-wrap:wrap;}
.part-flow .pf-node{background:rgba(181,52,26,.1);color:var(--terra);padding:4px 10px;border-radius:10px;}
.part-flow .pf-arrow{color:var(--muted);}
.part-flow.bidirectional .pf-arrow{color:var(--green);font-weight:900;}

/* ── CITATIONS SECTION ── */
.cit-section{background:linear-gradient(160deg,#2A1810,#1B1B1B);padding:60px 0;}
.cit-inner{max-width:1400px;margin:auto;padding:0 40px;}
.cit-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:28px;}
.cit-card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:18px;transition:background .2s;}
.cit-card:hover{background:rgba(255,255,255,.09);}
.cit-author{color:var(--gold);font-size:12px;font-weight:700;margin-bottom:4px;}
.cit-title{color:white;font-size:13px;font-weight:600;line-height:1.4;margin-bottom:6px;}
.cit-meta{color:rgba(255,255,255,.4);font-size:11px;line-height:1.5;}
.cit-tag{display:inline-block;background:rgba(181,52,26,.2);color:rgba(255,255,255,.6);font-size:9px;font-weight:700;padding:2px 7px;border-radius:6px;margin-top:6px;text-transform:uppercase;letter-spacing:.5px;}
</style>
</head>
<body>

<!-- ══ TERRITORY DATA (JSON for JS) ══ -->
<script>
const TERRITORIES_DATA = {{ territories_json|safe }};
</script>

<!-- ══ HEADER ══ -->
<header style="margin-top:36px;">
  <div class="header-inner">
    <a class="brand" href="/">
      <div class="brand-logo"><img src="/static/logo_usta.png" alt="Universidad Santo Tomás"></div>
      <div class="brand-text"><h1>OnLife Afro</h1><span>CAEDI · Universidad Santo Tomás</span></div>
    </a>

    <nav>
      <a href="/">🏠 Inicio</a>

      <!-- Territorios dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">📍 Territorios <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">7 Territorios Afrocolombianos</div>
          {% for t in territories %}
          <a href="#territorios" onclick="openTerritoryModal('{{t.slug}}');return false;">
            <span class="di">{{ t.icon }}</span>
            <span class="dm">{{ t.name }}<small>{{ t.desc }}</small></span>
            <span class="stat-badge">{{ t.poverty }}% pobreza</span>
          </a>
          {% endfor %}
          <a href="#territorios"><span class="di">📊</span><span class="dm">Ver todos los territorios<small>Tarjetas con estadísticas completas</small></span></a>
        </div>
      </div>

      <!-- Dashboards dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">{{ icons.tableau|safe }} Dashboards <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Visualización de Datos</div>
          {% for d in dashboards %}
          <a href="{{ d.url }}" target="_blank">
            <span class="di">{{ icons.tableau|safe }}</span>
            <span class="dm">{{ d.label }}<small>Tableau Public · AfroData Colombia</small></span>
          </a>
          {% endfor %}
          <a href="#dashboard"><span class="di">📊</span><span class="dm">Dashboard Embebido<small>Ver directamente en la plataforma</small></span></a>
        </div>
      </div>

      <!-- Infografías dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">{{ icons.pdf|safe }} Infografías <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Documentos Descargables</div>
          {% for p in pdfs %}
          <a href="{{ p.url }}" download="{{ p.file }}">
            <span class="di" style="font-size:20px;">{{ p.icon }}</span>
            <span class="dm">{{ p.title }}<small>{{ p.desc }}</small></span>
            <span class="pdf-badge">PDF</span>
          </a>
          {% endfor %}
          <a href="#infografias"><span class="di">{{ icons.download|safe }}</span><span class="dm">Ver todas las infografías<small>Sección completa de descarga</small></span></a>
        </div>
      </div>

      <!-- Galería dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">🎬 Galería <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Testimonios & Memoria</div>
          <a href="#galeria" onclick="switchGalTab('image',null)"><span class="di">📷</span><span class="dm">Fotografías Comunitarias<small>{{ media|selectattr('type','eq','image')|list|length }} imágenes disponibles</small></span></a>
          <a href="#galeria" onclick="switchGalTab('video',null)"><span class="di">🎬</span><span class="dm">Videos Testimoniales<small>{{ media|selectattr('type','eq','video')|list|length }} videos disponibles</small></span></a>
          <a href="#galeria" onclick="switchGalTab('audio',null)"><span class="di">🎵</span><span class="dm">Audios & Relatos<small>{{ media|selectattr('type','eq','audio')|list|length }} audios disponibles</small></span></a>
          <a href="#galeria"><span class="di">📂</span><span class="dm">Cargar archivos locales<small>Sin subida a servidor · 100% local</small></span></a>
        </div>
      </div>

      <!-- Comunidad dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">{{ icons.whatsapp|safe }} Comunidad <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Red Afrocolombiana</div>
          <a href="#comunidad"><span class="di">💬</span><span class="dm">Mensajes<small>Chat con líderes territoriales</small></span></a>
          <a href="#comunidad" onclick="initiateCall('voice')"><span class="di">📞</span><span class="dm">Llamada de Voz<small>Conectar con la red comunitaria</small></span></a>
          <a href="#comunidad" onclick="initiateCall('video')"><span class="di">📹</span><span class="dm">Videollamada<small>Reuniones y asambleas digitales</small></span></a>
          <a href="https://web.facebook.com/centro.afro.942" target="_blank"><span class="di">{{ icons.facebook|safe }}</span><span class="dm">Facebook CAEDI<small>5.1K seguidores</small></span></a>
          <a href="https://centroafrobogota.com/" target="_blank"><span class="di">🌐</span><span class="dm">centroafrobogota.com<small>Sitio oficial del CAEDI</small></span></a>
        </div>
      </div>

      <!-- Metodología dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">🔬 Metodología <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Marco Investigativo</div>
          <a href="#metodologia"><span class="di">📊</span><span class="dm">Fase Cuantitativa<small>Python + Pandas + DANE GEIH + Censo 2018</small></span></a>
          <a href="#metodologia"><span class="di">🗺️</span><span class="dm">Visualización Territorial<small>Tableau + Folium + GIS</small></span></a>
          <a href="#metodologia"><span class="di">🎙️</span><span class="dm">Testimonios Comunitarios<small>Audio, video y fotografías</small></span></a>
          <a href="#metodologia"><span class="di">🔍</span><span class="dm">Vigilancia Epistemológica<small>Verificación anti-sub-registro</small></span></a>
          <a href="#metodologia"><span class="di">🤖</span><span class="dm">IA Conversacional<small>Chatbot con contexto afrocolombiano</small></span></a>
        </div>
      </div>

      <!-- Noticias dropdown -->
      <div class="dropdown">
        <button class="drop-trigger">📰 Noticias <span class="drop-caret">▼</span></button>
        <div class="drop-menu">
          <div class="drop-header">Comunidad & Actualidad</div>
          {% for n in news %}
          <a href="#noticias"><span class="di" style="font-size:16px;">{{ n.tag[:2] }}</span><span class="dm">{{ n.title[:45] }}…<small>{{ n.tag }} · {{ n.meta }}</small></span></a>
          {% endfor %}
          <a href="#noticias"><span class="di">📰</span><span class="dm">Ver todas las noticias<small>CAEDI · Centro Afrocolombiano</small></span></a>
        </div>
      </div>
    </nav>

    <div style="display:flex;align-items:center;gap:8px;">
      <button class="dark-toggle" onclick="toggleDark()" id="darkBtn">🌙 Oscuro</button>
      <button class="dark-toggle" onclick="openSearch()" style="background:rgba(255,255,255,.08);">🔍 Buscar</button>
      <div id="authChip">
        <button class="dark-toggle" onclick="openAuth()" style="background:rgba(255,255,255,.08);">👤 Ingresar</button>
      </div>
    </div>
  </div>
</header>

<!-- ══ LINKS BAR ══ -->
<div class="links-bar">
  <a href="https://centroafrobogota.com/" target="_blank">{{ icons.web|safe }} centroafrobogota.com</a>
  <div class="div"></div>
  <a href="https://web.facebook.com/centro.afro.942" target="_blank">{{ icons.facebook|safe }} 5.1K seguidores · CAEDI</a>
  <div class="div"></div>
  <a href="https://public.tableau.com/app/profile/ambrose.mackmot/viz/AfroDataColombiaPlataformaOnLifeAfro/" target="_blank">{{ icons.tableau|safe }} AfroData Colombia</a>
  <div class="div"></div>
  <a href="#infografias">{{ icons.pdf|safe }} Descargar Infografías</a>
  <div class="div"></div>
  <a href="#comunidad">{{ icons.whatsapp|safe }} Red Comunitaria</a>
</div>

<!-- ══ KPI STRIP ══ -->
<div class="kpi-strip" role="region" aria-label="Indicadores clave">
  <div class="kpi-inner">
    <div class="kpi-item"><div class="kpi-num">7</div><div class="kpi-lbl">Territorios</div><div class="kpi-sub">Afrocolombianos</div></div>
    <div class="kpi-item"><div class="kpi-num">4.7M</div><div class="kpi-lbl">Población</div><div class="kpi-sub">Afro en Colombia</div></div>
    <div class="kpi-item"><div class="kpi-num">43%</div><div class="kpi-lbl">Pobreza</div><div class="kpi-sub">Monetaria afro</div></div>
    <div class="kpi-item"><div class="kpi-num">26%</div><div class="kpi-lbl">Desempleo</div><div class="kpi-sub">Juvenil afro</div></div>
    <div class="kpi-item"><div class="kpi-num">39%</div><div class="kpi-lbl">Conectividad</div><div class="kpi-sub">Hogares con internet</div></div>
    <div class="kpi-item"><div class="kpi-num">35%</div><div class="kpi-lbl">Educación</div><div class="kpi-sub">Acceso superior</div></div>
    <div class="kpi-item"><div class="kpi-num" id="kpiVisitors">...</div><div class="kpi-lbl">Visitantes</div><div class="kpi-sub">Plataforma OnLife</div></div>
  </div>
</div>

<!-- ══ VISITOR COUNTER BAR ══ -->
<div class="visitor-bar">
  <span>👁️ Visitantes hoy: <span class="visitor-count" id="visitorCount">...</span></span>
  <span>·</span>
  <span>🌍 7 territorios afrocolombianos</span>
  <span>·</span>
  <span>📊 Datos DANE · Censo 2018</span>
  <span>·</span>
  <span>🏛️ CAEDI · Universidad Santo Tomás · 2026</span>
</div>

<!-- ══ HERO ══ -->
<section class="hero">
  <div class="hero-bg"><img src="{{ hero_photo }}" alt="Comunidades afrocolombianas"></div>
  <div class="hero-content">
    <div class="hero-eyebrow">🌍 Humanidades Digitales Afrocolombianas</div>
    <h2>Bienestar<br><em>Afrocolombiano.</em></h2>
    <p class="hero-tagline">Justicia Epistémica y Visualización de Datos<br>en la Era OnLife</p>
    <p class="hero-desc">Datos, historias y voces de nuestros territorios. Una plataforma que integra datos abiertos, narrativas comunitarias y visualización digital para fortalecer la visibilidad y participación afrocolombiana.</p>
    <div class="hero-btns">
      <a class="btn-primary" href="#dashboard">{{ icons.tableau|safe }} Dashboard</a>
      <a class="btn-sky" href="#territorios">📍 Territorios</a>
      <a class="btn-primary" href="#infografias" style="background:var(--gold);">{{ icons.download|safe }} Infografías</a>
    </div>
    <div class="hero-stats">
      <div class="stat-chip"><div class="num">43%</div><div class="lbl">Pobreza monetaria población afro</div></div>
      <div class="stat-chip"><div class="num">26%</div><div class="lbl">Desempleo juvenil afro (18–28 años)</div></div>
      <div class="stat-chip"><div class="num">35%</div><div class="lbl">Acceso a educación superior</div></div>
      <div class="stat-chip"><div class="num">39%</div><div class="lbl">Hogares afro con internet</div></div>
    </div>
  </div>
  <div class="hero-photo">
    <div class="hero-photo-frame"><img src="{{ hero_photo }}" alt="Comunidad afrocolombiana"></div>
    <div class="hero-photo-caption">
      <div class="partner-badge"><img src="/static/logo_usta.png" alt="USTA"> Univ. Santo Tomás</div>
      <div class="partner-badge">{{ icons.tableau|safe }} Tableau</div>
      <div class="partner-badge">{{ icons.community|safe }} CAEDI</div>
    </div>
  </div>
</section>

<!-- ══ ABOUT / RESEARCH ══ -->
<div class="about-section" id="investigacion" role="region" aria-label="Sobre la investigación">
  <div class="about-inner">
    <div class="sec-label">🎓 Proyecto de Investigación</div>
    <h2 class="sec-title">Bienestar Afrocolombiano: Justicia Epistémica y Visualización de Datos en la Era OnLife</h2>
    <p class="sec-sub">Tesis de Maestría en Comunicación · Universidad Santo Tomás · CAEDI · 2026. Una investigación mixta que combina datos cuantitativos del DANE con metodologías cualitativas y participativas.</p>
    <div class="about-grid">
      <div>
        <div class="sec-label" style="margin-bottom:16px;">🎯 Objetivos de Investigación</div>
        <div class="about-objectives">
          <div class="obj-item"><div class="obj-num">1</div><div class="obj-text"><h4>Visibilidad de datos afrocolombianos</h4><p>Integrar datos del DANE, GEIH y Censo 2018 en dashboards interactivos accesibles a comunidades y tomadores de decisión.</p></div></div>
          <div class="obj-item"><div class="obj-num">2</div><div class="obj-text"><h4>Vigilancia epistemológica</h4><p>Detectar sub-registro, sesgos y cambios de categoría que distorsionan la realidad de la población NARP en fuentes oficiales.</p></div></div>
          <div class="obj-item"><div class="obj-num">3</div><div class="obj-text"><h4>Soberanía digital comunitaria</h4><p>Fortalecer la ciudadanía digital afrocolombiana a través de herramientas tecnológicas co-diseñadas con las comunidades.</p></div></div>
          <div class="obj-item"><div class="obj-num">4</div><div class="obj-text"><h4>Narrativas territoriales</h4><p>Combinar testimonios, audio, video y fotografía con datos cuantitativos para construir un relato integral de cada territorio.</p></div></div>
        </div>
        <div class="sec-label" style="margin-top:32px;margin-bottom:16px;">📚 Fuentes de Datos</div>
        <div class="sources-grid">
          <div class="source-card"><h4>DANE · GEIH</h4><p>Gran Encuesta Integrada de Hogares. Variables étnico-raciales. 2018–2024.</p><span class="source-tag">Cuantitativa</span></div>
          <div class="source-card"><h4>Censo Nacional 2018</h4><p>Autodeclaración étnica NARP. 4.7M afrocolombianos registrados.</p><span class="source-tag">Censal</span></div>
          <div class="source-card"><h4>Ley 70 de 1993</h4><p>Marco legal de territorios colectivos y derechos étnicos afrocolombianos.</p><span class="source-tag">Legal</span></div>
          <div class="source-card"><h4>CAEDI Fieldwork</h4><p>Testimonios, entrevistas y observación participante en 7 territorios.</p><span class="source-tag">Cualitativa</span></div>
          <div class="source-card"><h4>Datos Abiertos</h4><p>datos.gov.co · DNP · Ministerio de Salud · Ministerio de Educación.</p><span class="source-tag">Abiertos</span></div>
          <div class="source-card"><h4>Marco Teórico</h4><p>Bachelard (epistemología), Bourdieu (campo), Floridi (OnLife), Mignolo (colonialidad).</p><span class="source-tag">Epistémico</span></div>
        </div>
      </div>
      <div>
        <div class="sec-label" style="margin-bottom:16px;">👥 Equipo de Investigación</div>
        <div class="about-team">
          <div class="team-card"><div class="team-avatar">👨🏾‍🔬</div><div class="team-info"><h4>Mackmot Pachotto Ambrose</h4><p>Investigador Principal · CAEDI</p><span class="team-role">Director</span></div></div>
          <div class="team-card"><div class="team-avatar">🏛️</div><div class="team-info"><h4>Universidad Santo Tomás</h4><p>Facultad de Comunicación Social · Bogotá</p><span class="team-role">Institución</span></div></div>
          <div class="team-card"><div class="team-avatar">🌍</div><div class="team-info"><h4>CAEDI</h4><p>Centro Afrocolombiano de Espiritualidad y Desarrollo Integral · Calle 42 #13-50</p><span class="team-role">Centro Comunitario</span></div></div>
          <div class="team-card"><div class="team-avatar">📊</div><div class="team-info"><h4>Red de Consejos Comunitarios</h4><p>7 territorios · Chocó, Buenaventura, Tumaco, San Andrés, Cali, Cartagena, Pacífico Sur</p><span class="team-role">Comunidades</span></div></div>
        </div>
        <div style="margin-top:28px;padding:20px;background:white;border-radius:14px;border:1px solid var(--border);border-left:4px solid var(--terra);">
          <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;">📋 Resumen Metodológico</div>
          <p style="font-size:13px;line-height:1.7;color:var(--deep);">La investigación utiliza un diseño mixto secuencial: <strong>Fase 1</strong> análisis cuantitativo (Python, Pandas, DANE); <strong>Fase 2</strong> visualización territorial (Tableau, Folium); <strong>Fase 3</strong> testimonios comunitarios (audio, video, fotografía); <strong>Fase 4</strong> vigilancia epistemológica en 3 etapas contra sub-registro NARP.</p>
          <a href="#metodologia" style="display:inline-flex;align-items:center;gap:6px;margin-top:12px;color:var(--terra);font-size:13px;font-weight:700;text-decoration:none;">Ver metodología completa →</a>
        </div>
      </div>
    </div>

    <!-- ── RESEARCH QUESTION BANNER ─────────────────────────── -->
    <div class="rq-banner" role="note" aria-label="Pregunta de investigación">
      <div class="rq-label">❓ Pregunta de Investigación · Maestría en Comunicación USTA · 2026</div>
      <div class="rq-text">¿De qué manera el diseño de una plataforma de visualización de datos con enfoque étnico-racial, construida a partir de datos abiertos del DANE y evidencias cualitativas de organizaciones afrocolombianas en siete territorios estratégicos de Colombia, puede contribuir a reducir la brecha entre la producción institucional de información estadística sobre estas comunidades y su capacidad de apropiación, resignificación e incidencia política?</div>
      <div class="rq-source">Bienestar Afrocolombiano · M. Pachotto Ambrose · USTA · 2026 &nbsp;·&nbsp; Marco: Floridi (OnLife) · Mignolo (decolonialidad) · D'Ignazio & Klein (Data Feminism) · Santos (epistemologías del Sur)</div>
    </div>

    <!-- ── OBJECTIVES + FRAMEWORK ROW ──────────────────────── -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:24px;">
      <div style="background:rgba(181,52,26,.08);border-radius:12px;padding:18px;border-left:4px solid var(--terra);">
        <div style="font-size:10px;font-weight:700;color:var(--terra);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;">🎯 Objetivo General</div>
        <div style="font-size:13px;line-height:1.6;color:var(--deep);">Construir una plataforma de visualización que reduzca la brecha epistémica entre producción estadística institucional y apropiación comunitaria afrocolombiana.</div>
      </div>
      <div style="background:rgba(27,94,122,.08);border-radius:12px;padding:18px;border-left:4px solid var(--sky);">
        <div style="font-size:10px;font-weight:700;color:var(--sky);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;">📚 Marco Teórico</div>
        <div style="font-size:12px;line-height:1.6;color:var(--muted);">Floridi · Mignolo · Bachelard · Bourdieu · D'Ignazio & Klein · Santos · Noble · Castells · García Canclini · Urrea-Giraldo & Viáfara</div>
      </div>
      <div style="background:rgba(45,106,79,.08);border-radius:12px;padding:18px;border-left:4px solid var(--green);">
        <div style="font-size:10px;font-weight:700;color:var(--green);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;">🌐 ¿Por qué "OnLife"?</div>
        <div style="font-size:12px;line-height:1.6;color:var(--muted);">Floridi (2015): vida simultánea en lo físico y digital. Para comunidades NARP implica doble exclusión — territorial <em>y</em> epistémica — que la plataforma busca revertir.</div>
      </div>
      <div style="background:rgba(201,129,10,.08);border-radius:12px;padding:18px;border-left:4px solid var(--gold);">
        <div style="font-size:10px;font-weight:700;color:var(--gold);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;">📊 Fuentes de Datos</div>
        <div style="font-size:12px;line-height:1.6;color:var(--muted);">DANE CNPV 2018 · GEIH 2020–2024 · datos.gov.co · Ley 70/1993 · CAEDI Trabajo de Campo 2026 · PCN · CNA</div>
      </div>
    </div>

  </div>
</div>

<!-- ══ TABLEAU DASHBOARD ══ -->
<div class="dash-section" id="dashboard">
  <div class="dash-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">{{ icons.tableau|safe }} Visualización de datos</div>
    <h2 class="sec-title">AfroData Colombia</h2>
    <p class="sec-sub">La Hoja de Ruta — Dashboard interactivo con datos del Censo 2018, GEIH y fuentes abiertas del DANE.</p>
    <div class="tableau-wrap">
      <div class="tableau-bar">
        <span>{{ icons.tableau|safe }} &nbsp;AfroData Colombia · OnLife Afro · La Hoja de Ruta</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          {% for d in dashboards %}<a href="{{ d.url }}" target="_blank">{{ d.label }} ↗</a>{% endfor %}
        </div>
      </div>
      <iframe src="{{ dashboards[0].embed }}" allowfullscreen title="AfroData Colombia"></iframe>
    </div>
  </div>
</div>

<!-- ══ INTERACTIVE MAP (Leaflet + OpenStreetMap) ══ -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<div class="map-section" id="mapa">
  <div class="map-inner">
    <div class="sec-label">🗺️ Mapa territorial</div>
    <h2 class="sec-title">Colombia Afrocolombiana</h2>
    <p class="sec-sub">Mapa interactivo real. Haz clic en cada marcador para explorar estadísticas del territorio. Los colores indican el índice de pobreza.</p>
    <div id="colombiaMap" style="width:100%;height:520px;border-radius:16px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.18);border:2px solid var(--border);"></div>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--muted);align-items:center;">
      <span style="display:flex;align-items:center;gap:6px;"><span style="width:14px;height:14px;border-radius:50%;background:#B5341A;display:inline-block;"></span>Pobreza alta (&gt;60%)</span>
      <span style="display:flex;align-items:center;gap:6px;"><span style="width:14px;height:14px;border-radius:50%;background:#C9810A;display:inline-block;"></span>Pobreza media (40-60%)</span>
      <span style="display:flex;align-items:center;gap:6px;"><span style="width:14px;height:14px;border-radius:50%;background:#2D6A4F;display:inline-block;"></span>Pobreza baja (&lt;40%)</span>
      <span style="margin-left:auto;">🗺️ OpenStreetMap · Tiles © OSM contributors</span>
    </div>
  </div>
</div>
<script>
// ── REAL LEAFLET MAP ────────────────────────────────────────────────
(function initMap(){
  const map = L.map('colombiaMap', {
    center: [4.5, -74.0],
    zoom: 6,
    zoomControl: true,
    scrollWheelZoom: false
  });

  // OpenStreetMap tiles (free, no API key)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  const territories = [
    {slug:'choco',       name:'Chocó',        icon:'🌿', lat:5.70,  lng:-76.65, poverty:62, pop:'540,000 hab.', unemployment:18.4, connectivity:31,  color:'#B5341A'},
    {slug:'buenaventura',name:'Buenaventura', icon:'⚓', lat:3.88,  lng:-77.03, poverty:55, pop:'440,000 hab.', unemployment:16.1, connectivity:45,  color:'#B5341A'},
    {slug:'tumaco',      name:'Tumaco',       icon:'🌊', lat:1.82,  lng:-78.76, poverty:67, pop:'220,000 hab.', unemployment:19.3, connectivity:28,  color:'#B5341A'},
    {slug:'sanandres',   name:'San Andrés',   icon:'🏝️', lat:12.55, lng:-81.70, poverty:22, pop:'80,000 hab.',  unemployment:11.7, connectivity:72,  color:'#2D6A4F'},
    {slug:'cali',        name:'Cali',         icon:'🏙️', lat:3.43,  lng:-76.52, poverty:38, pop:'2.2M hab.',    unemployment:14.8, connectivity:58,  color:'#C9810A'},
    {slug:'cartagena',   name:'Cartagena',    icon:'🏰', lat:10.39, lng:-75.48, poverty:44, pop:'1.1M hab.',    unemployment:15.2, connectivity:51,  color:'#C9810A'},
    {slug:'pacificosur', name:'Pacífico Sur', icon:'🌺', lat:2.50,  lng:-77.50, poverty:71, pop:'180,000 hab.', unemployment:20.1, connectivity:22,  color:'#B5341A'},
  ];

  territories.forEach(t => {
    const radius = 18000 + (t.poverty * 500);
    const circle = L.circle([t.lat, t.lng], {
      color: t.color,
      fillColor: t.color,
      fillOpacity: 0.35,
      weight: 2.5,
      radius: radius
    }).addTo(map);

    const marker = L.marker([t.lat, t.lng], {
      icon: L.divIcon({
        html: `<div style="background:${t.color};color:white;border-radius:50%;width:38px;height:38px;display:flex;align-items:center;justify-content:center;font-size:18px;border:3px solid white;box-shadow:0 3px 12px rgba(0,0,0,.35);cursor:pointer;">${t.icon}</div>`,
        iconSize: [38,38],
        iconAnchor: [19,19],
        className: ''
      })
    }).addTo(map);

    const popup = `<div style="font-family:'DM Sans',sans-serif;min-width:200px;">
      <div style="font-size:16px;font-weight:700;margin-bottom:6px;">${t.icon} ${t.name}</div>
      <div style="font-size:12px;color:#666;margin-bottom:10px;">${t.pop}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;">
        <div style="background:#fef3f0;border-radius:6px;padding:6px;text-align:center;">
          <div style="color:#B5341A;font-weight:800;font-size:16px;">${t.poverty}%</div>
          <div style="color:#666;">Pobreza</div>
        </div>
        <div style="background:#f0f4fe;border-radius:6px;padding:6px;text-align:center;">
          <div style="color:#1B5E7A;font-weight:800;font-size:16px;">${t.connectivity}%</div>
          <div style="color:#666;">Conectividad</div>
        </div>
      </div>
      <button onclick="openTerritoryModal('${t.slug}')" style="margin-top:10px;width:100%;background:#B5341A;color:white;border:none;padding:8px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;">Ver estadísticas completas →</button>
    </div>`;

    marker.bindPopup(popup, {maxWidth:240});
    circle.bindPopup(popup, {maxWidth:240});
    marker.on('click', () => marker.openPopup());
  });
})();
</script>

<!-- ══ TERRITORIES ══ -->
<div id="territorios">
  <div class="section">
    <div class="sec-label">📍 Territorios estratégicos</div>
    <h2 class="sec-title">7 Territorios Afrocolombianos</h2>
    <p class="sec-sub">Haz clic en cualquier territorio para ver estadísticas detalladas, historia, desafíos y fortalezas de cada comunidad.</p>
    <div class="ter-grid">
      {% for t in territories %}
      {% set pc = 'v' if t.poverty>60 else ('vw' if t.poverty>40 else 'vg') %}
      {% set cc = 'v' if t.connectivity<40 else 'vg' %}
      <div class="ter-card" onclick="openTerritoryModal('{{t.slug}}')">
        <div class="ter-photo">
          {% if t.photo %}
          <img src="{{ t.photo }}" alt="{{ t.name }}" loading="lazy">
          {% else %}
          <div style="width:100%;height:100%;background:linear-gradient(135deg,rgba(181,52,26,.85),rgba(27,27,27,.9));"></div>
          <div class="ter-icon-fallback">{{ t.icon }}</div>
          {% endif %}
          <div class="ter-overlay"></div>
          <div class="ter-name">{{ t.name }}</div>
          <div class="ter-region">{{ t.region }}</div>
        </div>
        <div class="ter-body">
          <p class="ter-desc">{{ t.desc }}</p>
          <div class="ter-key-fact">💡 {{ t.key_fact }}</div>
          <div class="sr"><span class="k">Desempleo</span><span class="v">{{ t.unemployment }}%</span></div>
          <div class="sr"><span class="k">Conectividad</span><span class="{{ cc }}">{{ t.connectivity }}%</span></div>
          <div class="sr"><span class="k">Educación (años)</span><span class="vw">{{ t.education }}</span></div>
          <div class="sr"><span class="k">Índice de pobreza</span><span class="{{ pc }}">{{ t.poverty }}%</span></div>
          <div class="ter-cta">📊 Ver estadísticas detalladas →</div>
          <!-- Data Provenance -->
          <div class="ter-provenance">
            <span class="prov-tag">📊 DANE CNPV 2018</span>
            <span class="prov-tag">📈 GEIH 2024</span>
            <span class="prov-tag">🏛️ CAEDI 2026</span>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
</div>

<!-- ══ COMPARE TOOL ══ -->
<div class="compare-section" id="comparar">
  <div class="compare-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">⚖️ Comparador</div>
    <h2 class="sec-title">Comparar Territorios</h2>
    <p class="sec-sub">Selecciona dos territorios para comparar sus indicadores socioeconómicos lado a lado.</p>
    <div class="compare-selects">
      <select id="compareA" onchange="runCompare()">
        <option value="">— Territorio A —</option>
        <option value="choco">🌿 Chocó</option>
        <option value="buenaventura">⚓ Buenaventura</option>
        <option value="tumaco">🌊 Tumaco</option>
        <option value="sanandres">🏝️ San Andrés</option>
        <option value="cali">🏙️ Cali</option>
        <option value="cartagena">🏰 Cartagena</option>
        <option value="pacificosur">🌺 Pacífico Sur</option>
      </select>
      <span style="color:rgba(255,255,255,.4);font-size:24px;">vs</span>
      <select id="compareB" onchange="runCompare()">
        <option value="">— Territorio B —</option>
        <option value="choco">🌿 Chocó</option>
        <option value="buenaventura">⚓ Buenaventura</option>
        <option value="tumaco">🌊 Tumaco</option>
        <option value="sanandres">🏝️ San Andrés</option>
        <option value="cali">🏙️ Cali</option>
        <option value="cartagena">🏰 Cartagena</option>
        <option value="pacificosur">🌺 Pacífico Sur</option>
      </select>
    </div>
    <div class="compare-grid" id="compareGrid" style="display:none;"></div>
    <div id="compareEmpty" style="color:rgba(255,255,255,.4);font-size:14px;text-align:center;padding:40px;">Selecciona dos territorios arriba para ver la comparación</div>
  </div>
</div>

<!-- ══ INFOGRAFÍAS PDF SECTION ══ -->
<div class="pdf-section" id="infografias">
  <div class="pdf-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">{{ icons.pdf|safe }} Infografías & Descargables</div>
    <h2 class="sec-title">Infografías Afrocolombianas</h2>
    <p class="sec-sub">Descarga infografías en PDF sobre las condiciones de vida, brechas de desigualdad y metodología de investigación de las comunidades afrocolombianas.</p>
    <div class="pdf-grid">
      {% for p in pdfs %}
      <div class="pdf-card">
        <div class="pdf-card-top">
          <div class="pdf-icon-box">{{ p.icon }}</div>
          <div class="pdf-card-meta"><h3>{{ p.title }}</h3><p>{{ p.desc }}</p></div>
        </div>
        <a class="pdf-dl-btn" href="{{ p.url }}" download="{{ p.file }}">{{ icons.download|safe }} Descargar PDF</a>
      </div>
      {% endfor %}
    </div>
    <a class="pdf-all-btn" href="/api/pdfs" target="_blank">{{ icons.pdf|safe }} Ver todos los archivos disponibles (API)</a>
  </div>
</div>

<!-- ══ MEDIA GALLERY ══ -->
<div class="gal-section" id="galeria">
  <div class="gal-inner">
    <div class="sec-label">🎬 Testimonios & Memoria</div>
    <h2 class="sec-title">Galería Comunitaria</h2>
    <p class="sec-sub">Fotografías, videos y audios de las comunidades afrocolombianas. Coloca archivos en <strong>static/gallery/</strong> o cárgalos desde el navegador.</p>
    <div class="upload-zone" onclick="document.getElementById('mediaInput').click()">
      <div class="uz-icon">📂</div>
      <strong>Seleccionar fotos, videos o audios desde tu computador</strong>
      <p>📷 JPG/PNG &nbsp;·&nbsp; 🎬 MP4/MOV &nbsp;·&nbsp; 🎵 MP3/WAV/OGG &nbsp;·&nbsp; Sin subida a servidor</p>
    </div>
    <input type="file" id="mediaInput" multiple accept="image/*,video/*,audio/*,.mp4,.webm,.mov,.mp3,.wav,.ogg,.m4a,.flac">
    <div class="media-tabs">
      <button class="mtab active" id="mtab-all" onclick="switchTab('all',this)">🗂️ Todo <span class="count" id="cnt-all">{{ media|length }}</span></button>
      <button class="mtab" id="mtab-image" onclick="switchTab('image',this)">📷 Fotos <span class="count" id="cnt-image">{{ media|selectattr('type','eq','image')|list|length }}</span></button>
      <button class="mtab" id="mtab-video" onclick="switchTab('video',this)">🎬 Videos <span class="count" id="cnt-video">{{ media|selectattr('type','eq','video')|list|length }}</span></button>
      <button class="mtab" id="mtab-audio" onclick="switchTab('audio',this)">🎵 Audios <span class="count" id="cnt-audio">{{ media|selectattr('type','eq','audio')|list|length }}</span></button>
    </div>
    <!-- Photos -->
    <div id="tab-image" class="media-pane">
      <div class="photo-grid" id="photoGrid">
        {% set images = media|selectattr('type','eq','image')|list %}
        {% if images %}
          {% for m in images %}
          <div class="gal-item" onclick="openLb('{{ m.url }}')">
            <img src="{{ m.url }}" alt="{{ m.name }}" loading="lazy">
            <div class="ov"><span>🔍</span></div>
          </div>
          {% endfor %}
        {% else %}
          <div class="empty-state" style="grid-column:1/-1;"><div class="es-icon">📷</div><h3>No hay fotos aún</h3><p>Copia JPG/PNG en <strong>static/gallery/</strong> o usa el botón de carga.</p></div>
        {% endif %}
      </div>
    </div>
    <!-- Videos -->
    <div id="tab-video" class="media-pane" style="display:none;">
      <div class="video-grid" id="videoGrid">
        {% set videos = media|selectattr('type','eq','video')|list %}
        {% if videos %}
          {% for m in videos %}
          <div class="video-card">
            <video controls preload="metadata"><source src="{{ m.url }}" type="video/mp4">Tu navegador no soporta video.</video>
            <div class="vc-info"><div class="vc-name">{{ m.name }}</div><div class="vc-meta"><span class="vc-badge">VIDEO</span> Testimonio comunitario</div></div>
          </div>
          {% endfor %}
        {% else %}
          <div class="empty-state"><div class="es-icon">🎬</div><h3>No hay videos aún</h3><p>Copia MP4/MOV en <strong>static/gallery/</strong></p></div>
        {% endif %}
      </div>
    </div>
    <!-- Audio -->
    <div id="tab-audio" class="media-pane" style="display:none;">
      <div class="audio-grid" id="audioGrid">
        {% set audios = media|selectattr('type','eq','audio')|list %}
        {% if audios %}
          {% for m in audios %}
          <div class="audio-card">
            <div class="audio-thumb">🎵</div>
            <div class="audio-info">
              <div class="audio-title">{{ m.name|replace('_',' ')|replace('-',' ') }}</div>
              <div class="audio-meta"><span class="audio-badge">AUDIO</span> Testimonio · CAEDI OnLife Afro</div>
              <div class="waveform"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
              <audio controls preload="metadata"><source src="{{ m.url }}"></audio>
            </div>
          </div>
          {% endfor %}
        {% else %}
          <div class="empty-state"><div class="es-icon">🎵</div><h3>No hay audios aún</h3><p>Copia MP3/WAV/OGG en <strong>static/gallery/</strong></p></div>
        {% endif %}
      </div>
    </div>
  </div>
</div>

<!-- ══ COMMUNITY / WHATSAPP MODULE ══ -->
<div class="wa-section" id="comunidad">
  <div class="wa-inner">
    <div class="sec-label" style="color:var(--green);border-color:var(--green);background:rgba(45,106,79,.1);">{{ icons.whatsapp|safe }} Red Comunitaria</div>
    <h2 class="sec-title">Comunidad OnLife Afro</h2>
    <p class="sec-sub">Mensajes en tiempo real dentro de la plataforma, o únete directamente al grupo de WhatsApp de cada territorio.</p>

    <!-- OPTION 1: Real WhatsApp Group Buttons -->
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:32px;padding:20px;background:rgba(37,211,102,.08);border:1px solid rgba(37,211,102,.2);border-radius:14px;">
      <div style="width:100%;font-size:13px;font-weight:700;color:var(--green);margin-bottom:8px;">{{ icons.whatsapp|safe }} &nbsp;Grupos de WhatsApp por territorio — toca para unirte:</div>
      <a href="{{ wa_groups.general }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} CAEDI General</a>
      <a href="{{ wa_groups.choco }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} Chocó 🌿</a>
      <a href="{{ wa_groups.buenaventura }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} Buenaventura ⚓</a>
      <a href="{{ wa_groups.tumaco }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} Tumaco 🌊</a>
      <a href="{{ wa_groups.investigadores }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} Investigadores 🔬</a>
      <a href="{{ wa_groups.sanandres }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} San Andrés 🏝️</a>
      <a href="{{ wa_groups.pacificosur }}" target="_blank" class="wa-group-btn">{{ icons.whatsapp|safe }} Pacífico Sur 🌺</a>
    </div>

    <!-- OPTION 2: Real-time in-platform chat with SQLite -->
    <div style="font-size:13px;font-weight:700;color:var(--deep);margin-bottom:12px;display:flex;align-items:center;gap:8px;">
      💬 Chat en tiempo real · OnLife Afro Platform
      <span style="background:rgba(37,211,102,.15);color:var(--green);font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;">EN VIVO</span>
    </div>
    <!-- Name input -->
    <div id="waNameBar" style="display:flex;gap:10px;align-items:center;margin-bottom:14px;padding:14px;background:rgba(181,52,26,.06);border-radius:10px;border:1px solid var(--border);">
      <span style="font-size:13px;font-weight:600;">Tu nombre:</span>
      <input id="waSenderName" type="text" placeholder="Escribe tu nombre..." style="flex:1;border:1.5px solid var(--border);border-radius:8px;padding:8px 14px;font-family:'DM Sans',sans-serif;font-size:13px;outline:none;" value="Visitante">
      <button onclick="saveName()" style="background:var(--terra);color:white;border:none;padding:8px 18px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;">Guardar</button>
    </div>
    <div class="wa-container">
      <!-- Sidebar -->
      <div class="wa-sidebar">
        <div class="wa-sidebar-header">
          <h3>💬 Salas</h3>
          <div class="wa-sidebar-header-btns">
            <button title="Actualizar" onclick="loadMessages()">🔄</button>
          </div>
        </div>
        <div class="wa-search">
          <input type="text" placeholder="🔍 Buscar sala..." oninput="filterContacts(this.value)">
        </div>
        <div class="wa-contacts" id="waContacts">
          <div class="wa-contact active" onclick="openChat('general')" data-name="CAEDI General">
            <div class="wa-avatar">🌍</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">CAEDI General</div>
              <div class="wa-contact-last" id="last-general">Canal principal</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('choco')" data-name="Chocó">
            <div class="wa-avatar">🌿</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Líderes del Chocó</div>
              <div class="wa-contact-last" id="last-choco">Canal territorial</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('buenaventura')" data-name="Buenaventura">
            <div class="wa-avatar">⚓</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Consejo Buenaventura</div>
              <div class="wa-contact-last" id="last-buenaventura">Canal territorial</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('tumaco')" data-name="Tumaco">
            <div class="wa-avatar">🌊</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Comunidad Tumaco</div>
              <div class="wa-contact-last" id="last-tumaco">Canal territorial</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('investigadores')" data-name="Investigadores">
            <div class="wa-avatar">🔬</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Investigadores USTA</div>
              <div class="wa-contact-last" id="last-investigadores">Canal académico</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('sanandres')" data-name="San Andrés">
            <div class="wa-avatar">🏝️</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Comunidad Raizal</div>
              <div class="wa-contact-last" id="last-sanandres">San Andrés</div>
            </div>
          </div>
          <div class="wa-contact" onclick="openChat('pacificosur')" data-name="Pacífico Sur">
            <div class="wa-avatar">🌺</div>
            <div class="wa-contact-info">
              <div class="wa-contact-name">Pacífico Sur</div>
              <div class="wa-contact-last" id="last-pacificosur">Consejos comunitarios</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Chat area -->
      <div class="wa-chat">
        <div class="wa-chat-header">
          <div class="wa-chat-header-left">
            <div class="wa-chat-avatar" id="waChatAvatar">🌍</div>
            <div>
              <div class="wa-chat-name" id="waChatName">CAEDI General</div>
              <div class="wa-chat-status" id="waChatStatus">Canal principal · OnLife Afro</div>
            </div>
          </div>
          <div class="wa-chat-actions">
            <button onclick="initiateCall('video')" title="Videollamada">📹</button>
            <button onclick="initiateCall('voice')" title="Llamada de voz">📞</button>
            <button onclick="loadMessages()" title="Actualizar mensajes">🔄</button>
            <button id="waGroupLink" onclick="openWaGroup()" title="Abrir grupo WhatsApp real" style="background:rgba(37,211,102,.2);">{{ icons.whatsapp|safe }}</button>
          </div>
        </div>

        <!-- Call bar -->
        <div class="wa-call-bar" id="waCallBar" style="display:none;">
          <div class="wa-call-bar-text" id="waCallBarText">Llamada en curso...</div>
          <button class="wa-call-btn" onclick="joinCall('voice')">📞 Unirse</button>
          <button class="wa-call-btn video" onclick="joinCall('video')">📹 Con video</button>
          <button onclick="endCall()" style="background:var(--terra);color:white;border:none;padding:8px 16px;border-radius:20px;cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;">❌ Rechazar</button>
        </div>

        <div class="wa-messages" id="waMessages">
          <div class="wa-date-separator"><span>Cargando mensajes...</span></div>
        </div>

        <div class="wa-input-bar">
          <button class="wa-attach" title="Adjuntar">📎</button>
          <input type="text" id="waInput" placeholder="Escribe un mensaje..." onkeydown="if(event.key==='Enter')sendWaMsg()">
          <button class="wa-mic" onclick="sendWaMsg()" title="Enviar">➤</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ EVENTS ══ -->
<div class="events-section" id="eventos">
  <div class="events-inner">
    <div class="sec-label">📅 Próximos Eventos</div>
    <h2 class="sec-title">Agenda Comunitaria</h2>
    <p class="sec-sub">Asambleas territoriales, talleres de datos, foros y reuniones de la red afrocolombiana.</p>
    <div class="events-grid" id="eventsGrid">
      <div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted);">Cargando eventos... 📅</div>
    </div>
  </div>
</div>

<!-- ══ NEWS ══ -->
<div class="section" id="noticias">
  <div class="sec-label">📰 Comunidad & Noticias</div>
  <h2 class="sec-title">CAEDI · Centro Afrocolombiano</h2>
  <p class="sec-sub">Noticias, eventos y publicaciones del Centro Afrocolombiano de Espiritualidad y Desarrollo Integral.</p>
  <div class="news-grid">
    {% for n in news %}
    <div class="nc">
      <div class="nc-top">
        <img src="{{n.photo}}" alt="{{n.photo_alt}}" loading="lazy">
        <div class="nc-top-overlay"></div>
        <span class="ntag">{{n.tag}}</span>
      </div>
      <div class="nc-body"><h3>{{n.title}}</h3><p>{{n.body}}</p></div>
      <div class="nc-foot"><a href="{{n.link}}" target="_blank">{{n.link_text}}</a><span class="nc-meta">{{n.meta}}</span></div>
    </div>
    {% endfor %}
  </div>
</div>

<!-- ══ TESTIMONIALS ══ -->
<div class="test-section" id="testimonios">
  <div class="test-inner">
    <div class="sec-label">🗣️ Voces de la Comunidad</div>
    <h2 class="sec-title">Testimonios Territoriales</h2>
    <p class="sec-sub">Las voces de líderes, investigadores y comunidades afrocolombianas son datos válidos. Comparte tu experiencia.</p>
    <div class="test-grid" id="testimonialsGrid">
      <!-- Loaded by JS -->
      <div class="test-card">
        <div class="test-card-top"><div class="test-avatar">🌿</div><div><div class="test-name">Líder Comunitario</div><div class="test-territory">Chocó · Región Pacífica</div></div></div>
        <div class="test-text">"La plataforma OnLife Afro nos da por primera vez una herramienta para mostrar con datos lo que vivimos. Los números confirman lo que sabemos: hay una deuda histórica con el Chocó."</div>
        <div class="test-ts">Mayo 2026</div>
      </div>
      <div class="test-card">
        <div class="test-card-top"><div class="test-avatar">⚓</div><div><div class="test-name">Consejo Comunitario</div><div class="test-territory">Buenaventura · Valle del Cauca</div></div></div>
        <div class="test-text">"Buenaventura mueve el 60% del comercio del país, pero nuestra gente vive en pobreza. OnLife Afro hace visible esa contradicción con datos irrefutables."</div>
        <div class="test-ts">Abril 2026</div>
      </div>
      <div class="test-card">
        <div class="test-card-top"><div class="test-avatar">🔬</div><div><div class="test-name">Mackmot P. Ambrose</div><div class="test-territory">CAEDI · Universidad Santo Tomás</div></div></div>
        <div class="test-text">"La vigilancia epistemológica no es solo un concepto académico — es la diferencia entre datos que visibilizan y datos que borran. OnLife Afro elige visibilizar."</div>
        <div class="test-ts">Mayo 2026</div>
      </div>
    </div>
    <!-- Submission form -->
    <div class="test-form">
      <h3>Comparte tu testimonio</h3>
      <p>Tu voz es un dato. Los testimonios verificados aparecen en la plataforma.</p>
      <div class="form-row">
        <div class="form-field">
          <label>Tu nombre</label>
          <input type="text" id="testName" placeholder="Nombre o alias...">
        </div>
        <div class="form-field">
          <label>Territorio</label>
          <select id="testTerritory">
            <option value="general">CAEDI General</option>
            <option value="choco">Chocó</option>
            <option value="buenaventura">Buenaventura</option>
            <option value="tumaco">Tumaco</option>
            <option value="sanandres">San Andrés</option>
            <option value="cali">Cali</option>
            <option value="cartagena">Cartagena</option>
            <option value="pacificosur">Pacífico Sur</option>
          </select>
        </div>
      </div>
      <div class="form-field" style="margin-bottom:20px;">
        <label>Tu testimonio</label>
        <textarea id="testMessage" placeholder="Comparte tu experiencia, reflexión o mensaje sobre los datos de tu territorio..."></textarea>
      </div>
      <button class="form-submit" onclick="submitTestimonial()">🗣️ Enviar Testimonio</button>
      <div class="form-success" id="testSuccess">✅ ¡Testimonio recibido! Gracias por compartir tu voz.</div>
    </div>
  </div>
</div>

<!-- ══ METHODOLOGY ══ -->
<div class="meth-section" id="metodologia">
  <div class="meth-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">🔬 Metodología</div>
    <h2 class="sec-title" style="color:white;">Investigación mixta & Vigilancia Epistemológica</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">Inspirada en Bachelard y Bourdieu, la plataforma articula fases cuantitativas, cualitativas y de verificación epistémica para proteger las realidades comunitarias de sesgos institucionales.</p>
    <div class="meth-grid">

      <a class="mc mc-link" href="#dashboard" title="Ir a Dashboards Tableau">
        <div class="mc-arrow">→</div>
        <div class="ico">📊</div>
        <h3>Fase Cuantitativa</h3>
        <p>Python + Pandas + DANE GEIH + Censo 2018. Análisis estadístico riguroso con visualización Tableau.</p>
        <div class="mc-goto">Ver Dashboards ↗</div>
      </a>

      <a class="mc mc-link" href="#mapa" title="Ir al mapa territorial">
        <div class="mc-arrow">→</div>
        <div class="ico">🗺️</div>
        <h3>Visualización Territorial</h3>
        <p>Tableau Public, mapas de calor, GIS territorial con Folium. Datos geoespaciales afrocolombianos.</p>
        <div class="mc-goto">Ver Mapa Interactivo ↗</div>
      </a>

      <a class="mc mc-link" href="#galeria" title="Ir a la galería de testimonios">
        <div class="mc-arrow">→</div>
        <div class="ico">🎙️</div>
        <h3>Testimonios</h3>
        <p>Entrevistas en audio y video, fotografías comunitarias. La voz de los territorios como dato válido.</p>
        <div class="mc-goto">Ver Galería Comunitaria ↗</div>
      </a>

      <a class="mc mc-link" href="#graficas" title="Ir a gráficas de datos">
        <div class="mc-arrow">→</div>
        <div class="ico">🔍</div>
        <h3>Vigilancia Epistemológica</h3>
        <p>Pipeline en 3 etapas que detecta sub-registro, sesgos y cambios de categoría en datos del DANE.</p>
        <div class="mc-goto">Ver Gráficas de Datos ↗</div>
      </a>

      <a class="mc mc-link" href="#comunidad" title="Ir al chat comunitario" onclick="toggleChat();return false;">
        <div class="mc-arrow">→</div>
        <div class="ico">🤖</div>
        <h3>IA Conversacional</h3>
        <p>Chatbot con contexto afrocolombiano. Responde preguntas sobre territorios, datos e infografías.</p>
        <div class="mc-goto">Abrir Asistente IA ↗</div>
      </a>

      <a class="mc mc-link" href="#infografias" title="Ir a infografías descargables">
        <div class="mc-arrow">→</div>
        <div class="ico">⚖️</div>
        <h3>Soberanía de Datos</h3>
        <p>Tres niveles de protección legal: patente SIC, derechos de autor DNDA, marcas e IP registradas.</p>
        <div class="mc-goto">Ver Infografías PDF ↗</div>
      </a>

    </div>
  </div>
</div>

<!-- ══ DATA CHARTS ══ -->
<div style="background:var(--deep);padding:80px 0;" id="graficas">
  <div style="max-width:1400px;margin:auto;padding:0 40px;">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">📈 Visualización automática</div>
    <h2 class="sec-title" style="color:white;">Gráficas de Datos Afrocolombianos</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">Generadas automáticamente desde los datos de los 7 territorios. Actualizan en tiempo real al comparar o explorar.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:8px;">
      <!-- Bar chart -->
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:28px;">
        <div style="color:white;font-family:'Playfair Display',serif;font-size:18px;font-weight:700;margin-bottom:6px;">Índice de Pobreza por Territorio</div>
        <div style="color:rgba(255,255,255,.4);font-size:12px;margin-bottom:20px;">Porcentaje · Fuente: DANE · Censo 2018</div>
        <canvas id="barChart" height="280"></canvas>
      </div>
      <!-- Pie chart -->
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:28px;">
        <div style="color:white;font-family:'Playfair Display',serif;font-size:18px;font-weight:700;margin-bottom:6px;">Distribución de Conectividad</div>
        <div style="color:rgba(255,255,255,.4);font-size:12px;margin-bottom:20px;">% hogares con internet por territorio</div>
        <canvas id="pieChart" height="280"></canvas>
      </div>
      <!-- Line chart -->
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:28px;">
        <div style="color:white;font-family:'Playfair Display',serif;font-size:18px;font-weight:700;margin-bottom:6px;">Desempleo vs Pobreza</div>
        <div style="color:rgba(255,255,255,.4);font-size:12px;margin-bottom:20px;">Correlación por territorio · GEIH 2024</div>
        <canvas id="lineChart" height="280"></canvas>
      </div>
      <!-- Radar / spider chart -->
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:28px;">
        <div style="color:white;font-family:'Playfair Display',serif;font-size:18px;font-weight:700;margin-bottom:6px;">Perfil Multidimensional</div>
        <div style="color:rgba(255,255,255,.4);font-size:12px;margin-bottom:20px;">Radar comparativo — todos los territorios</div>
        <canvas id="radarChart" height="280"></canvas>
      </div>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
// ── AUTO-GENERATED CHARTS FROM TERRITORY DATA ──────────────────────
(function buildCharts(){
  const T = TERRITORIES_DATA;
  const names  = T.map(t=>t.name);
  const poverty = T.map(t=>t.poverty);
  const conn   = T.map(t=>t.connectivity);
  const unemp  = T.map(t=>t.unemployment);
  const edu    = T.map(t=>t.education);
  const health = T.map(t=>t.healthcare);

  const COLORS = ['#B5341A','#C9810A','#1B5E7A','#2D6A4F','#8B1A1A','#7A5E1B','#1A3A4A'];
  const ALPHA  = COLORS.map(c=>c+'BB');

  Chart.defaults.color = 'rgba(255,255,255,0.6)';
  Chart.defaults.font.family = "'DM Sans', sans-serif";

  const gridOpts = {
    color: 'rgba(255,255,255,0.08)',
    borderColor: 'rgba(255,255,255,0.15)'
  };

  // ── BAR CHART: Poverty ──────────────────────────────────────────
  new Chart(document.getElementById('barChart'), {
    type: 'bar',
    data: {
      labels: names,
      datasets: [{
        label: 'Pobreza (%)',
        data: poverty,
        backgroundColor: ALPHA,
        borderColor: COLORS,
        borderWidth: 2,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: {display:false},
        tooltip: {callbacks:{label: ctx=>`${ctx.parsed.y}% pobreza`}}
      },
      scales: {
        x: {grid:gridOpts, ticks:{color:'rgba(255,255,255,0.6)',maxRotation:30}},
        y: {grid:gridOpts, ticks:{color:'rgba(255,255,255,0.6)',callback:v=>v+'%'}, max:100, min:0}
      }
    }
  });

  // ── PIE CHART: Connectivity ─────────────────────────────────────
  new Chart(document.getElementById('pieChart'), {
    type: 'doughnut',
    data: {
      labels: names,
      datasets: [{
        data: conn,
        backgroundColor: ALPHA,
        borderColor: COLORS,
        borderWidth: 2,
        hoverOffset: 10
      }]
    },
    options: {
      responsive: true,
      cutout: '55%',
      plugins: {
        legend: {
          position:'bottom',
          labels:{color:'rgba(255,255,255,0.65)',padding:12,font:{size:11}}
        },
        tooltip: {callbacks:{label: ctx=>`${ctx.label}: ${ctx.parsed}% conectividad`}}
      }
    }
  });

  // ── LINE CHART: Unemployment vs Poverty ─────────────────────────
  new Chart(document.getElementById('lineChart'), {
    type: 'line',
    data: {
      labels: names,
      datasets: [
        {
          label: 'Desempleo (%)',
          data: unemp,
          borderColor: '#C9810A',
          backgroundColor: 'rgba(201,129,10,0.15)',
          borderWidth: 2.5,
          pointBackgroundColor: '#C9810A',
          pointRadius: 5,
          tension: 0.4,
          fill: true,
          yAxisID: 'y'
        },
        {
          label: 'Pobreza (%)',
          data: poverty,
          borderColor: '#B5341A',
          backgroundColor: 'rgba(181,52,26,0.12)',
          borderWidth: 2.5,
          pointBackgroundColor: '#B5341A',
          pointRadius: 5,
          tension: 0.4,
          fill: true,
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      interaction: {mode:'index', intersect:false},
      plugins: {
        legend: {labels:{color:'rgba(255,255,255,0.7)',padding:16}}
      },
      scales: {
        x: {grid:gridOpts, ticks:{color:'rgba(255,255,255,0.6)',maxRotation:30}},
        y:  {grid:gridOpts, ticks:{color:'#C9810A',callback:v=>v+'%'}, position:'left',  max:35, min:0, title:{display:true,text:'Desempleo',color:'#C9810A'}},
        y1: {grid:{display:false}, ticks:{color:'#B5341A',callback:v=>v+'%'}, position:'right', max:100, min:0, title:{display:true,text:'Pobreza',color:'#B5341A'}}
      }
    }
  });

  // ── RADAR CHART: Multidimensional ───────────────────────────────
  // Normalize all metrics 0-100 (higher = better)
  const norm = T.map(t=>([
    100 - t.poverty,
    100 - t.unemployment * 2.5,
    t.connectivity,
    (t.education / 15) * 100,
    t.healthcare,
    100 - t.youth_unemployment * 2
  ]));

  new Chart(document.getElementById('radarChart'), {
    type: 'radar',
    data: {
      labels: ['Nivel de vida','Empleo','Conectividad','Educación','Salud','Juventud'],
      datasets: T.map((t,i)=>({
        label: t.name,
        data: norm[i],
        borderColor: COLORS[i],
        backgroundColor: COLORS[i]+'25',
        borderWidth: 1.8,
        pointRadius: 3,
        pointBackgroundColor: COLORS[i]
      }))
    },
    options: {
      responsive: true,
      plugins: {
        legend: {position:'bottom', labels:{color:'rgba(255,255,255,0.65)',padding:10,font:{size:10}}}
      },
      scales: {
        r: {
          grid:   {color:'rgba(255,255,255,0.12)'},
          angleLines:{color:'rgba(255,255,255,0.12)'},
          pointLabels:{color:'rgba(255,255,255,0.7)',font:{size:11}},
          ticks:  {display:false},
          min:0, max:100
        }
      }
    }
  });
})();
</script>

<!-- ══ STORYTELLING ══ -->
<div class="story-section" id="voces" role="region" aria-label="Voces de los territorios">
  <div class="story-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">🗺️ Narrativas Territoriales</div>
    <h2 class="sec-title" style="color:white;">Voces de los Territorios</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">Cada territorio tiene una historia que los datos solos no pueden contar. Aquí, testimonios, audio, video y visualizaciones se combinan en una sola narrativa.</p>
    <div class="story-timeline" role="list">
      <div class="story-item" role="listitem">
        <span class="story-item-tag">Chocó · Pacífico</span>
        <h3>"Solo 1 médico por cada 4,200 habitantes"</h3>
        <p>El Chocó es el departamento con mayor biodiversidad del mundo y simultáneamente el de mayor exclusión histórica. Su 62% de pobreza no es accidente — es producto de décadas de abandono estatal.</p>
        <div class="story-item-media">
          <a class="story-media-chip" href="#mapa">🗺️ Ver en el mapa</a>
          <a class="story-media-chip" href="#galeria" onclick="switchGalTab('audio')">🎵 Escuchar testimonios</a>
          <a class="story-media-chip" href="#territorios" onclick="openTerritoryModal('choco')">📊 Ver datos completos</a>
        </div>
      </div>
      <div class="story-item" role="listitem">
        <span class="story-item-tag">Buenaventura · Valle</span>
        <h3>"El 60% del comercio exterior, el 55% en pobreza"</h3>
        <p>Buenaventura es la paradoja colombiana: mueve miles de millones en exportaciones, pero sus habitantes afrocolombianos viven en condiciones de marginalidad estructural en los barrios palafíticos.</p>
        <div class="story-item-media">
          <a class="story-media-chip" href="#mapa">🗺️ Ver en el mapa</a>
          <a class="story-media-chip" href="#graficas">📈 Ver gráficas</a>
          <a class="story-media-chip" href="#territorios" onclick="openTerritoryModal('buenaventura')">📊 Ver datos</a>
        </div>
      </div>
      <div class="story-item" role="listitem">
        <span class="story-item-tag">San Andrés · Caribe</span>
        <h3>"Raizal: el único pueblo con lengua propia del Caribe colombiano"</h3>
        <p>El archipiélago de San Andrés alberga al pueblo Raizal — con idioma Creole inglés, cosmovisión propia y los mejores indicadores de conectividad de todos los territorios analizados (72%).</p>
        <div class="story-item-media">
          <a class="story-media-chip" href="#mapa">🗺️ Ver en el mapa</a>
          <a class="story-media-chip" href="#comparar">⚖️ Comparar territorios</a>
          <a class="story-media-chip" href="#testimonios">🗣️ Leer testimonios</a>
        </div>
      </div>
      <div class="story-item" role="listitem">
        <span class="story-item-tag">Plataforma · CAEDI</span>
        <h3>"Los datos sin comunidad son estadística vacía"</h3>
        <p>La vigilancia epistemológica de OnLife Afro detecta que el DANE sub-registra consistentemente población NARP en zonas rurales dispersas. La corrección metodológica revela brechas aún mayores.</p>
        <div class="story-item-media">
          <a class="story-media-chip" href="#metodologia">🔬 Ver metodología</a>
          <a class="story-media-chip" href="#graficas">📈 Ver datos corregidos</a>
          <a class="story-media-chip" href="#investigacion">🎓 Marco teórico</a>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ IMPACT DASHBOARD ══ -->
<div class="impact-section" id="impacto" role="region" aria-label="Impacto de la investigación">
  <div class="impact-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">📈 Impacto de la Investigación</div>
    <h2 class="sec-title" style="color:white;">Métricas de Impacto</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">Indicadores en tiempo real de uso, participación comunitaria y alcance de la plataforma.</p>
    <div class="impact-grid">
      <div class="impact-card"><div class="impact-icon">👁️</div><div class="impact-num" id="impactVisitors">...</div><div class="impact-label">Visitantes totales</div></div>
      <div class="impact-card"><div class="impact-icon">💬</div><div class="impact-num" id="impactMessages">...</div><div class="impact-label">Mensajes comunidad</div></div>
      <div class="impact-card"><div class="impact-icon">🗣️</div><div class="impact-num" id="impactTestimonials">...</div><div class="impact-label">Testimonios</div></div>
      <div class="impact-card"><div class="impact-icon">📍</div><div class="impact-num">7</div><div class="impact-label">Territorios</div></div>
      <div class="impact-card"><div class="impact-icon">📄</div><div class="impact-num" id="impactPdfs">...</div><div class="impact-label">Infografías</div></div>
      <div class="impact-card"><div class="impact-icon">🎬</div><div class="impact-num" id="impactMedia">...</div><div class="impact-label">Archivos multimedia</div></div>
    </div>
  </div>
</div>

<!-- ══ DOWNLOAD CENTER ══ -->
<div class="dl-section" id="descargas" role="region" aria-label="Centro de descargas">
  <div class="dl-inner">
    <div class="sec-label">📥 Centro de Descargas</div>
    <h2 class="sec-title">Repositorio Académico</h2>
    <p class="sec-sub">Informes, infografías, datasets y documentación metodológica de libre acceso. Toda la investigación es abierta.</p>
    <div class="dl-grid">
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon pdf">📊</div><div class="dl-card-info"><h4>Infografías Territoriales</h4><p>Serie completa de infografías PDF sobre los 7 territorios</p></div></div>
        <div class="dl-card-size">📁 PDF · CAEDI 2026</div>
        <a class="dl-btn primary" href="#infografias">📥 Ver infografías</a>
      </div>
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon csv">📈</div><div class="dl-card-info"><h4>Datos DANE procesados</h4><p>Variables GEIH étnico-raciales · Censo 2018 · CSV limpio</p></div></div>
        <div class="dl-card-size">📁 CSV · DANE · 2024</div>
        <a class="dl-btn primary" href="/api/stats" target="_blank">📥 API de datos</a>
      </div>
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon doc">📖</div><div class="dl-card-info"><h4>Metodología OnLife Afro</h4><p>Documento completo: diseño mixto, fases, vigilancia epistemológica</p></div></div>
        <div class="dl-card-size">📁 PDF · Metodología</div>
        <a class="dl-btn secondary" href="#metodologia">📖 Ver metodología</a>
      </div>
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon pdf">🗺️</div><div class="dl-card-info"><h4>Territorios API JSON</h4><p>Datos completos de los 7 territorios en formato JSON abierto</p></div></div>
        <div class="dl-card-size">📁 JSON · REST API</div>
        <a class="dl-btn primary" href="/api/territories" target="_blank">📥 Descargar JSON</a>
      </div>
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon doc">🎓</div><div class="dl-card-info"><h4>Marco Teórico</h4><p>Bachelard · Bourdieu · Floridi · Mignolo · Referencias completas</p></div></div>
        <div class="dl-card-size">📁 Académico · USTA</div>
        <a class="dl-btn secondary" href="#investigacion">📖 Ver referencias</a>
      </div>
      <div class="dl-card">
        <div class="dl-card-top"><div class="dl-type-icon csv">💬</div><div class="dl-card-info"><h4>Testimonios Comunidad</h4><p>Archivo de voces territoriales recopiladas por CAEDI</p></div></div>
        <div class="dl-card-size">📁 SQLite · Abierto</div>
        <a class="dl-btn primary" href="/api/testimonials" target="_blank">📥 Ver testimonios API</a>
      </div>
    </div>
  </div>
</div>

<!-- ══ AUTH MODAL ══ -->
<div class="auth-modal-overlay" id="authModal" onclick="closeAuthOnOverlay(event)">
  <div class="auth-modal">
    <h2>🌍 Comunidad OnLife Afro</h2>
    <p>Accede con tu cuenta para participar en el chat comunitario y enviar testimonios.</p>
    <div class="auth-tabs">
      <button class="auth-tab active" onclick="switchAuthTab('login',this)">Ingresar</button>
      <button class="auth-tab" onclick="switchAuthTab('register',this)">Registrarse</button>
    </div>
    <div id="auth-login">
      <div class="auth-field"><label>Usuario</label><input type="text" id="loginUser" placeholder="Tu nombre de usuario..." autocomplete="username"></div>
      <div class="auth-field"><label>Contraseña</label><input type="password" id="loginPass" placeholder="Tu contraseña..." autocomplete="current-password"></div>
      <button class="auth-submit" onclick="doLogin()">Ingresar →</button>
    </div>
    <div id="auth-register" style="display:none;">
      <div class="auth-field"><label>Nombre completo</label><input type="text" id="regName" placeholder="Tu nombre..."></div>
      <div class="auth-field"><label>Usuario</label><input type="text" id="regUser" placeholder="Elige un nombre de usuario..." autocomplete="username"></div>
      <div class="auth-field"><label>Contraseña</label><input type="password" id="regPass" placeholder="Elige una contraseña..." autocomplete="new-password"></div>
      <button class="auth-submit" onclick="doRegister()">Crear cuenta →</button>
    </div>
    <div class="auth-error" id="authError"></div>
    <div class="auth-success" id="authSuccess"></div>
    <button onclick="closeAuth()" style="width:100%;margin-top:14px;background:none;border:1px solid var(--border);color:var(--muted);padding:10px;border-radius:8px;cursor:pointer;font-family:'DM Sans',sans-serif;font-size:13px;">Cancelar</button>
  </div>
</div>

<!-- ══ PRIVACY MODAL ══ -->
<div class="privacy-modal" id="privacyModal" onclick="closePrivacyOnOverlay(event)">
  <div class="privacy-box">
    <h2>🔒 Política de Privacidad</h2>
    <h3>Datos que recopilamos</h3>
    <p>OnLife Afro recopila únicamente: nombre de usuario, mensajes enviados en el chat comunitario, y testimonios voluntariamente enviados. No recopilamos datos personales sensibles sin consentimiento explícito.</p>
    <h3>Uso de los datos</h3>
    <p>Los datos se usan exclusivamente para investigación académica en el marco de la Maestría en Comunicación de la Universidad Santo Tomás y para el funcionamiento de la red comunitaria CAEDI.</p>
    <h3>Almacenamiento</h3>
    <p>Los datos se almacenan localmente en una base de datos SQLite en el servidor de la plataforma. No se comparten con terceros ni se usan para publicidad.</p>
    <h3>Tus derechos</h3>
    <p>Tienes derecho a solicitar la eliminación de tus datos en cualquier momento contactando a CAEDI: centroafrobogota.com · Calle 42 #13-50, Bogotá.</p>
    <h3>Propiedad intelectual</h3>
    <p>© 2026 Mackmot Pachotto Ambrose · CAEDI · Universidad Santo Tomás. Plataforma protegida bajo derechos de autor DNDA. Los datos del DANE se usan bajo licencia de datos abiertos del Estado colombiano.</p>
    <button onclick="closePrivacy()" style="margin-top:20px;background:var(--terra);color:white;border:none;padding:12px 28px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:700;font-family:'DM Sans',sans-serif;">Entendido ✓</button>
  </div>
</div>

<!-- ══ OPEN DATA / CSV REPOSITORY ══ -->
<div class="csv-section" id="datos-abiertos" role="region" aria-label="Repositorio de datos abiertos">
  <div class="csv-inner">
    <div class="sec-label">📂 Datos Abiertos · Transparencia</div>
    <h2 class="sec-title">Repositorio de Datos AfroData Colombia</h2>
    <p class="sec-sub">Todos los datasets usados en la investigación son públicos y descargables. Transparencia metodológica total — cada cifra tiene fuente verificable.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:start;">
      <div class="csv-tree" role="tree" aria-label="Estructura de datos">
        <div class="tree-root">📁 afrodata_colombia_v4/</div>
        <div class="tree-item"><span class="tree-icon">📊</span><span class="tree-name">01_indicadores_TD_TGP_TO.csv</span><span class="tree-meta">Tasa desocupación por sexo y grupo étnico</span><a class="csv-dl-btn" href="/api/territories">API</a></div>
        <div class="tree-item"><span class="tree-icon">📈</span><span class="tree-name">02_tendencia_historica_2021_2025.csv</span><span class="tree-meta">Serie histórica GEIH 2021–2025</span><a class="csv-dl-btn" href="/api/stats" target="_blank">API</a></div>
        <div class="tree-item"><span class="tree-icon">🗺️</span><span class="tree-name">06_departamentos_narp.csv</span><span class="tree-meta">Concentración NARP por departamento</span><a class="csv-dl-btn" href="/api/territories" target="_blank">API</a></div>
        <div class="tree-item"><span class="tree-icon">🌐</span><span class="tree-name">07_comparacion_latam.csv</span><span class="tree-meta">Comparación desempleo afro en LATAM</span><a class="csv-dl-btn json" href="/api/territories">JSON</a></div>
        <div class="tree-item"><span class="tree-icon">🏙️</span><span class="tree-name">09_ciudades_td_narp.csv</span><span class="tree-meta">TD NARP por municipio · lat/lon</span><a class="csv-dl-btn json" href="/api/territories">JSON</a></div>
        <div class="tree-item"><span class="tree-icon">⚖️</span><span class="tree-name">11_brechas_multidimensionales.csv</span><span class="tree-meta">Empleo · Salud · Educación · Pobreza</span><a class="csv-dl-btn" href="/api/stats" target="_blank">API</a></div>
        <div class="tree-item"><span class="tree-icon">📋</span><span class="tree-name">15_scorecard_brechas_sinteticas.csv</span><span class="tree-meta">KPI scorecard completo</span><a class="csv-dl-btn" href="/api/stats" target="_blank">API</a></div>
        <div class="tree-item"><span class="tree-icon">🔬</span><span class="tree-name">metodologia_onlife_afro.pdf</span><span class="tree-meta">Documento metodológico completo · APA 7ª</span><a class="csv-dl-btn" href="#infografias">PDF</a></div>
      </div>
      <div>
        <div style="background:white;border-radius:14px;padding:24px;border:1px solid var(--border);margin-bottom:20px;">
          <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;">🔒 Licencia & Propiedad</div>
          <p style="font-size:13px;line-height:1.7;color:var(--deep);margin-bottom:10px;">Los datos del DANE se usan bajo la política de datos abiertos del Estado colombiano (Ley 1712 de 2014). Los análisis, visualizaciones y narrativas son propiedad intelectual registrada de M. Pachotto Ambrose / CAEDI (DNDA, SIC).</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">
            <span style="background:rgba(45,106,79,.1);color:var(--green);font-size:10px;font-weight:700;padding:4px 10px;border-radius:8px;">✅ Open Data DANE</span>
            <span style="background:rgba(27,94,122,.1);color:var(--sky);font-size:10px;font-weight:700;padding:4px 10px;border-radius:8px;">🎓 Uso Académico</span>
            <span style="background:rgba(181,52,26,.1);color:var(--terra);font-size:10px;font-weight:700;padding:4px 10px;border-radius:8px;">©️ DNDA 2026</span>
            <span style="background:rgba(201,129,10,.1);color:var(--gold);font-size:10px;font-weight:700;padding:4px 10px;border-radius:8px;">🏛️ SIC Colombia</span>
          </div>
        </div>
        <div style="background:white;border-radius:14px;padding:24px;border:1px solid var(--border);">
          <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;">📡 APIs Disponibles</div>
          <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--cream);border-radius:8px;"><code style="color:var(--terra);">GET /api/territories</code><span style="color:var(--muted);">JSON completo 7 territorios</span></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--cream);border-radius:8px;"><code style="color:var(--terra);">GET /api/stats</code><span style="color:var(--muted);">Estadísticas de la plataforma</span></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--cream);border-radius:8px;"><code style="color:var(--terra);">GET /api/compare?a=&b=</code><span style="color:var(--muted);">Comparar dos territorios</span></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--cream);border-radius:8px;"><code style="color:var(--terra);">GET /api/search?q=</code><span style="color:var(--muted);">Búsqueda global</span></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--cream);border-radius:8px;"><code style="color:var(--terra);">GET /api/testimonials</code><span style="color:var(--muted);">Testimonios comunitarios</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ COMMUNITY PARTICIPATION (bidirectional) ══ -->
<div style="background:var(--deep);padding:60px 0;" id="participacion" role="region" aria-label="Participación comunitaria">
  <div style="max-width:1400px;margin:auto;padding:0 40px;">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">🤝 Participación Comunitaria</div>
    <h2 class="sec-title" style="color:white;">Investigación ↔ Comunidad</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">La plataforma opera en modelo bidireccional: no solo <em>hacia</em> la comunidad — la comunidad co-produce el conocimiento. Principios OCAP (First Nations Information Governance Centre, 2019).</p>
    <div class="part-grid">
      <div class="part-card">
        <h4>📤 Investigador → Comunidad</h4>
        <p>Datos del DANE procesados, visualizados y devueltos a los territorios en formatos accesibles para usuarios no técnicos.</p>
        <div class="part-flow">
          <span class="pf-node">DANE</span><span class="pf-arrow">→</span>
          <span class="pf-node">Python</span><span class="pf-arrow">→</span>
          <span class="pf-node">Tableau</span><span class="pf-arrow">→</span>
          <span class="pf-node">Comunidad</span>
        </div>
      </div>
      <div class="part-card" style="border-top-color:var(--green);">
        <h4>🔄 Comunidad ↔ Plataforma</h4>
        <p>Las comunidades envían testimonios, validan datos, corrigen errores y co-diseñan las visualizaciones desde sus propias categorías.</p>
        <div class="part-flow bidirectional">
          <span class="pf-node" style="background:rgba(45,106,79,.1);color:var(--green);">Territorio</span>
          <span class="pf-arrow">⇄</span>
          <span class="pf-node" style="background:rgba(45,106,79,.1);color:var(--green);">Plataforma</span>
          <span class="pf-arrow">⇄</span>
          <span class="pf-node" style="background:rgba(45,106,79,.1);color:var(--green);">Datos</span>
        </div>
      </div>
      <div class="part-card" style="border-top-color:var(--sky);">
        <h4>🎙️ Voces como Datos</h4>
        <p>Los testimonios orales, fotografías y relatos comunitarios son tratados como datos válidos — no como "ilustraciones" de cifras.</p>
        <div class="part-flow">
          <span class="pf-node">Testimonio</span><span class="pf-arrow">→</span>
          <span class="pf-node">Dato Válido</span><span class="pf-arrow">→</span>
          <span class="pf-node">Dashboard</span>
        </div>
      </div>
      <div class="part-card" style="border-top-color:var(--gold);">
        <h4>📋 Principios OCAP</h4>
        <p>Propiedad · Control · Acceso · Posesión. Las comunidades NARP tienen soberanía sobre los datos que las describen.</p>
        <div class="part-flow">
          <span class="pf-node">Propiedad</span>
          <span class="pf-node">Control</span>
          <span class="pf-node">Acceso</span>
          <span class="pf-node">Posesión</span>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ KEY CITATIONS ══ -->
<div class="cit-section" id="referencias" role="region" aria-label="Referencias bibliográficas clave">
  <div class="cit-inner">
    <div class="sec-label" style="color:var(--gold);border-color:var(--gold);background:rgba(201,129,10,.1);">📚 Referencias Bibliográficas</div>
    <h2 class="sec-title" style="color:white;">Marco Teórico · 44 fuentes APA 7ª</h2>
    <p class="sec-sub" style="color:rgba(255,255,255,.5);">Fuentes clave del proyecto. Bibliografía completa disponible en <em>Bienestar Afrocolombiano</em> · M. Pachotto Ambrose · USTA · 2026.</p>
    <div class="cit-grid">
      <div class="cit-card"><div class="cit-author">Floridi, L. (Ed.) · 2015</div><div class="cit-title">The OnLife Manifesto: Being Human in a Hyperconnected Era</div><div class="cit-meta">Springer Open. Base conceptual del término OnLife — vida simultánea en lo físico y digital.</div><span class="cit-tag">Marco conceptual</span></div>
      <div class="cit-card"><div class="cit-author">D'Ignazio, C. & Klein, L.F. · 2020</div><div class="cit-title">Data Feminism</div><div class="cit-meta">The MIT Press. Principios éticos para visualización de datos con comunidades vulnerables. Epistemología de la visualización comprometida.</div><span class="cit-tag">Metodología</span></div>
      <div class="cit-card"><div class="cit-author">Santos, B. de S. · 2010</div><div class="cit-title">Descolonizar el saber, reinventar el poder</div><div class="cit-meta">Trilce. Epistemologías del Sur — conocimiento producido desde comunidades históricamente excluidas.</div><span class="cit-tag">Epistémico</span></div>
      <div class="cit-card"><div class="cit-author">Mignolo, W.D. · 2009</div><div class="cit-title">Epistemic disobedience, independent thought and decolonial freedom</div><div class="cit-meta">Theory, Culture & Society. Desobediencia epistémica como acto político de las comunidades racializadas.</div><span class="cit-tag">Decolonial</span></div>
      <div class="cit-card"><div class="cit-author">Noble, S.U. · 2018</div><div class="cit-title">Algorithms of Oppression</div><div class="cit-meta">NYU Press. Los motores de búsqueda refuerzan el racismo estructural. Impacto en comunidades afrocolombianas digitales.</div><span class="cit-tag">Algoritmos</span></div>
      <div class="cit-card"><div class="cit-author">DANE-GEIH · 2023</div><div class="cit-title">Gran Encuesta Integrada de Hogares: Módulo étnico-racial</div><div class="cit-meta">Fuente estadística primaria. TD NARP +4.8pp · Salud −22% · Educación −2.3 años vs. media nacional.</div><span class="cit-tag">Fuente de datos</span></div>
      <div class="cit-card"><div class="cit-author">Urrea-Giraldo & Viáfara · 2007</div><div class="cit-title">Desigualdades sociodemográficas y socioeconómicas en Colombia</div><div class="cit-meta">Revista Colombiana de Sociología. Primer análisis estadístico sistemático de brechas étnico-raciales en Colombia.</div><span class="cit-tag">Antecedente</span></div>
      <div class="cit-card"><div class="cit-author">García Canclini, N. · 2019</div><div class="cit-title">Ciudadanos reemplazados por algoritmos</div><div class="cit-meta">CALAS. Los algoritmos reemplazan la ciudadanía — impacto específico en comunidades afrocolombianas urbanas.</div><span class="cit-tag">Comunicación digital</span></div>
      <div class="cit-card"><div class="cit-author">First Nations Info. Governance Centre · 2019</div><div class="cit-title">The First Nations Principles of OCAP</div><div class="cit-meta">fnigc.ca. Propiedad · Control · Acceso · Posesión. Horizonte ético para soberanía de datos comunitarios.</div><span class="cit-tag">Soberanía de datos</span></div>
    </div>
    <div style="margin-top:24px;padding:16px 20px;background:rgba(255,255,255,.05);border-radius:10px;border:1px solid rgba(255,255,255,.1);font-size:12px;color:rgba(255,255,255,.4);line-height:1.7;">
      📖 Bibliografía completa (44 entradas APA 7ª): Bateman et al. (2010) · Bertin (1967) · Bolter & Grusin (2000) · Bonilla-Silva (2003) · Bravo et al. (2010) · Caicedo Ortiz (2018) · Cairo (2012) · Carmichael & Hamilton (1967) · Castells (2009) · DANE (2019, 2023) · Duncan & Duncan (1955) · Dwork (2006) · Dykes (2019) · Figueiredo & Lima (2021) · Hepp (2013) · Lupton (2016) · Martín-Barbero (2003) · Nussbaumer (2015) · ONU-HABITAT (2021) · Perea (2021) · Scheuerman et al. (2021) · Serna (2011) · Sibilia (2005) · Tufte (1983) · Vargas (2025a–g) · Viáfara et al. (2010) · Wong (2011)
    </div>
  </div>
</div>

<!-- ══ FOOTER ══ -->
<footer>
  <div class="ft-grid">
    <div class="ft-brand">
      <h3>OnLife Afro</h3>
      <p>Plataforma de Humanidades Digitales Afrocolombianas. CAEDI · Universidad Santo Tomás · Bogotá · 2026.</p>
      <p style="margin-top:10px;color:rgba(255,255,255,.35);font-size:12px;">Mackmot Pachotto Ambrose · Investigador Principal</p>
      <div class="ft-logo"><img src="/static/logo_usta.png" alt="USTA"><span style="color:rgba(255,255,255,.5);font-size:12px;">Universidad Santo Tomás</span></div>
      <div class="ft-social">
        <a href="https://web.facebook.com/centro.afro.942" target="_blank" title="Facebook">{{ icons.facebook|safe }}</a>
        <a href="https://public.tableau.com/app/profile/ambrose.mackmot/" target="_blank" title="Tableau">{{ icons.tableau|safe }}</a>
        <a href="https://centroafrobogota.com/" target="_blank" title="Web">{{ icons.web|safe }}</a>
        <a href="#comunidad" title="Comunidad">{{ icons.whatsapp|safe }}</a>
      </div>
    </div>
    <div class="ft-col">
      <h4>Plataforma</h4>
      <ul>
        <li><a href="#dashboard">{{ icons.tableau|safe }} Dashboard Tableau</a></li>
        <li><a href="#territorios">📍 7 Territorios</a></li>
        <li><a href="#infografias">{{ icons.pdf|safe }} Infografías PDF</a></li>
        <li><a href="#galeria">🎬 Galería · Video · Audio</a></li>
        <li><a href="#metodologia">🔬 Metodología</a></li>
      </ul>
    </div>
    <div class="ft-col">
      <h4>Comunidad</h4>
      <ul>
        <li><a href="#comunidad">{{ icons.whatsapp|safe }} Red Comunitaria</a></li>
        <li><a href="https://centroafrobogota.com/" target="_blank">{{ icons.web|safe }} centroafrobogota.com</a></li>
        <li><a href="https://web.facebook.com/centro.afro.942" target="_blank">{{ icons.facebook|safe }} Facebook CAEDI</a></li>
        <li><a href="https://public.tableau.com/app/profile/ambrose.mackmot/" target="_blank">{{ icons.tableau|safe }} Tableau Public</a></li>
      </ul>
    </div>
    <div class="ft-col">
      <h4>Contacto</h4>
      <ul>
        <li><a href="#">📍 Calle 42 #13-50, Bogotá</a></li>
        <li><a href="https://www.usta.edu.co/" target="_blank">🎓 Universidad Santo Tomás</a></li>
        <li><a href="#">{{ icons.community|safe }} CAEDI · Centro Afrocolombiano</a></li>
        <li><a href="#comunidad">📞 Llamar a la red</a></li>
      </ul>
    </div>
  </div>
  <div class="ft-bot">
    <span>© 2026 OnLife Afro Platform v6.0 · CAEDI · Universidad Santo Tomás</span>
    <span>Justicia epistémica · Visibilidad territorial · Ciudadanía digital</span>
  </div>
  <div class="ft-legal">
    <span>📍 Calle 42 #13-50, Bogotá · <a href="https://centroafrobogota.com/" target="_blank">centroafrobogota.com</a></span>
    <span>
      <a href="#" onclick="openPrivacy();return false;">Política de Privacidad</a> &nbsp;·&nbsp;
      <a href="#" onclick="openPrivacy();return false;">Términos de Uso</a> &nbsp;·&nbsp;
      <a href="/api/territories" target="_blank">API Abierta</a> &nbsp;·&nbsp;
      <a href="#investigacion">Sobre la Investigación</a>
    </span>
  </div>
</footer>

<!-- ══ SPLASH SCREEN ══ -->
<div class="splash" id="splash">
  <div class="splash-logo"><img src="/static/icons/icon-192x192.png" onerror="this.style.display='none';this.parentNode.innerHTML='🌍'" style="width:100px;height:100px;border-radius:22px;object-fit:cover;box-shadow:0 8px 32px rgba(181,52,26,.45);border:3px solid rgba(255,255,255,.15);" alt="OnLife Afro"></div>
  <div class="splash-title">OnLife Afro</div>
  <div class="splash-sub">Humanidades Digitales Afrocolombianas</div>
  <div class="splash-bar"><div class="splash-progress"></div></div>
</div>

<!-- ══ SEARCH OVERLAY ══ -->
<div class="search-overlay" id="searchOverlay" onclick="closeSearchOnOverlay(event)">
  <div class="search-box">
    <div class="search-box-top">
      <input type="text" id="searchInput" placeholder="Buscar territorios, infografías, datos..." oninput="doSearch(this.value)" autofocus>
      <button onclick="closeSearch()">✕</button>
    </div>
    <div class="search-results" id="searchResults">
      <div class="search-empty">Escribe para buscar territorios, infografías y más...</div>
    </div>
  </div>
</div>

<!-- ══ SCROLL TO TOP ══ -->
<button class="scroll-top" id="scrollTop" onclick="window.scrollTo({top:0,behavior:'smooth'})" title="Volver arriba">↑</button>

<!-- ══ MOBILE BOTTOM NAV ══ -->
<div class="mobile-nav">
  <div class="mobile-nav-inner">
    <a class="mob-nav-btn" href="/"><span>🏠</span><span>Inicio</span></a>
    <a class="mob-nav-btn" href="#territorios"><span>📍</span><span>Territorios</span></a>
    <a class="mob-nav-btn" href="#dashboard"><span>📊</span><span>Datos</span></a>
    <a class="mob-nav-btn" href="#comunidad"><span>💬</span><span>Comunidad</span></a>
    <a class="mob-nav-btn" href="#galeria"><span>🎬</span><span>Galería</span></a>
  </div>
</div>

<!-- ══ CHATBOT ══ -->
<button class="fab" onclick="toggleChat()" title="Asistente OnLife Afro">💬</button>
<div class="chat-panel" id="chatPanel">
  <div class="chat-hd">
    <div><h4>Asistente OnLife Afro</h4><p>CAEDI · Humanidades Digitales</p></div>
    <button onclick="toggleChat()" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">✕</button>
  </div>
  <div class="chat-msgs" id="chatMsgs">
    <div class="mbot">¡Hola! Soy el asistente de OnLife Afro. Pregúntame sobre territorios, infografías, datos, comunidad o testimonios del CAEDI.</div>
  </div>
  <div class="chat-in">
    <input type="text" id="chatIn" placeholder="Escribe tu pregunta..." onkeydown="if(event.key==='Enter')sendMsg()">
    <button onclick="sendMsg()">➤</button>
  </div>
</div>

<!-- ══ LIGHTBOX ══ -->
<div class="lb" id="lb" onclick="closeLb()">
  <button class="lb-x" onclick="closeLb()">✕</button>
  <img id="lbImg" src="" alt="">
</div>

<!-- ══ TERRITORY DETAIL MODAL ══ -->
<div class="ter-modal-overlay" id="terModal" onclick="closeModalOnOverlay(event)">
  <div class="ter-modal" id="terModalContent">
    <div class="ter-modal-hero" id="terModalHero">
      <div class="ter-modal-hero-fallback" id="terModalFallback" style="background:linear-gradient(135deg,#B5341A,#1B1B1B);"></div>
      <div style="position:absolute;inset:0;" id="terModalHeroImg"></div>
      <button class="ter-modal-close" onclick="closeTerritoryModal()">✕</button>
      <div class="ter-modal-hero::after"></div>
      <div class="ter-modal-hero-info">
        <h2 id="terModalName">Chocó</h2>
        <p id="terModalDesc">Pacífico colombiano · Mayor biodiversidad</p>
      </div>
    </div>
    <div class="ter-modal-body">
      <div class="ter-modal-tabs">
        <button class="ter-modal-tab active" onclick="switchModalTab('stats',this)">📊 Estadísticas</button>
        <button class="ter-modal-tab" onclick="switchModalTab('history',this)">📖 Historia</button>
        <button class="ter-modal-tab" onclick="switchModalTab('challenges',this)">⚠️ Desafíos</button>
        <button class="ter-modal-tab" onclick="switchModalTab('strengths',this)">✨ Fortalezas</button>
      </div>

      <!-- Stats Panel -->
      <div id="modal-stats" class="ter-modal-panel active">
        <div class="ter-stats-grid" id="terStatsGrid"></div>
        <div id="terBarCharts"></div>
        <div style="margin-top:20px;padding:14px;background:rgba(181,52,26,.06);border-radius:10px;border-left:3px solid var(--terra);">
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px;">💡 Dato clave</div>
          <div id="terKeyFact" style="font-size:14px;font-weight:600;color:var(--deep);"></div>
        </div>
        <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn-primary" onclick="closeTerritoryModal();document.querySelector('#comunidad').scrollIntoView()">{{ icons.whatsapp|safe }} Contactar comunidad</button>
          <button class="btn-sky" onclick="closeTerritoryModal();document.querySelector('#dashboard').scrollIntoView()">{{ icons.tableau|safe }} Ver en dashboard</button>
        </div>
      </div>

      <!-- History Panel -->
      <div id="modal-history" class="ter-modal-panel">
        <div class="ter-history-text" id="terHistory"></div>
        <div style="display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted);padding:12px;background:rgba(27,94,122,.06);border-radius:10px;">
          <span style="font-size:20px;">📚</span>
          <span>Fuentes: DANE, Censo 2018, GEIH, Ley 70 de 1993, investigación CAEDI.</span>
        </div>
      </div>

      <!-- Challenges Panel -->
      <div id="modal-challenges" class="ter-modal-panel">
        <p style="font-size:14px;color:var(--muted);margin-bottom:16px;">Principales retos estructurales identificados a través de la investigación participativa del CAEDI y datos del DANE.</p>
        <ul class="ter-list" id="terChallengesList"></ul>
      </div>

      <!-- Strengths Panel -->
      <div id="modal-strengths" class="ter-modal-panel">
        <p style="font-size:14px;color:var(--muted);margin-bottom:16px;">Recursos, capacidades y activos territoriales reconocidos por las propias comunidades como base de la soberanía.</p>
        <ul class="ter-list" id="terStrengthsList"></ul>
      </div>
    </div>
  </div>
</div>

<!-- ══ PWA INSTALL BANNER ══ -->
<div class="pwa-banner" id="pwaBanner">
  <div class="pwa-banner-left">
    <div class="pwa-banner-icon"><img src="/static/icons/icon-192x192.png" alt="OnLife Afro"></div>
    <div class="pwa-banner-text">
      <h4>Instalar OnLife Afro</h4>
      <p>Accede sin internet · Instala como app en tu dispositivo</p>
    </div>
  </div>
  <div class="pwa-banner-btns">
    <button class="pwa-install-btn" id="pwaInstallBtn">📲 Instalar App</button>
    <button class="pwa-dismiss-btn" id="pwaDismissBtn">Ahora no</button>
  </div>
</div>
<div class="pwa-status" id="pwaStatus"></div>

<script>
// ── TERRITORY MODAL ──────────────────────────────────────────────────
function openTerritoryModal(slug){
  const t = TERRITORIES_DATA.find(t=>t.slug===slug);
  if(!t) return;

  // Hero
  const heroImg = document.getElementById('terModalHeroImg');
  const fallback = document.getElementById('terModalFallback');
  if(t.photo){
    heroImg.innerHTML = `<img src="${t.photo}" style="width:100%;height:100%;object-fit:cover;" alt="${t.name}">`;
    heroImg.style.display='block';
    fallback.style.display='none';
  } else {
    heroImg.innerHTML='';
    heroImg.style.display='none';
    fallback.style.display='flex';
    fallback.textContent = t.icon;
    fallback.style.fontSize='80px';
    fallback.style.background='linear-gradient(135deg,rgba(181,52,26,.85),rgba(27,27,27,.9))';
  }
  // Hero overlay style
  document.getElementById('terModalHero').style.background = t.photo ? 'transparent' : 'transparent';

  document.getElementById('terModalName').textContent = t.icon+' '+t.name;
  document.getElementById('terModalDesc').textContent = t.region+' · '+t.population;
  document.getElementById('terKeyFact').textContent = t.key_fact;
  document.getElementById('terHistory').textContent = t.history;

  // Stats grid
  const grid = document.getElementById('terStatsGrid');
  const poorClass = t.poverty>60?'red':(t.poverty>40?'gold':'green');
  const connClass = t.connectivity<40?'red':(t.connectivity<60?'gold':'green');
  grid.innerHTML = `
    <div class="ter-stat-card ${poorClass}"><div class="tsv">${t.poverty}%</div><div class="tsk">Índice de pobreza</div></div>
    <div class="ter-stat-card red"><div class="tsv">${t.unemployment}%</div><div class="tsk">Desempleo general</div></div>
    <div class="ter-stat-card gold"><div class="tsv">${t.youth_unemployment}%</div><div class="tsk">Desempleo juvenil</div></div>
    <div class="ter-stat-card ${connClass}"><div class="tsv">${t.connectivity}%</div><div class="tsk">Conectividad internet</div></div>
    <div class="ter-stat-card gold"><div class="tsv">${t.education}</div><div class="tsk">Años de educación</div></div>
    <div class="ter-stat-card green"><div class="tsv">${t.healthcare}%</div><div class="tsk">Acceso a salud</div></div>
  `;

  // Bar charts
  const bars = document.getElementById('terBarCharts');
  bars.innerHTML = `
    <div style="margin-top:20px;">
      ${makeBar('Pobreza',t.poverty,100,'red')}
      ${makeBar('Desempleo',t.unemployment,40,'red')}
      ${makeBar('Conectividad',t.connectivity,100,'sky')}
      ${makeBar('Acceso a salud',t.healthcare,100,'green')}
    </div>
  `;

  // Challenges
  const cl = document.getElementById('terChallengesList');
  cl.innerHTML = t.challenges.map(c=>`<li>${c}</li>`).join('');

  // Strengths
  const sl = document.getElementById('terStrengthsList');
  sl.innerHTML = t.strengths.map(s=>`<li>${s}</li>`).join('');

  // Reset tabs
  document.querySelectorAll('.ter-modal-tab').forEach(tb=>tb.classList.remove('active'));
  document.querySelectorAll('.ter-modal-panel').forEach(p=>p.classList.remove('active'));
  document.querySelector('.ter-modal-tab').classList.add('active');
  document.getElementById('modal-stats').classList.add('active');

  document.getElementById('terModal').classList.add('open');
  document.body.style.overflow='hidden';

  // Animate bars
  setTimeout(()=>{
    document.querySelectorAll('.ter-bar-fill').forEach(b=>{
      b.style.width = b.dataset.w+'%';
    });
  },100);
}

function makeBar(label,val,max,color){
  const pct = Math.round((val/max)*100);
  const display = color==='red'&&val>10 ? val+'%' : val+(color==='sky'?'%':(color==='green'?'%':''));
  const colorCls = color;
  return `<div class="ter-bar-group">
    <div class="ter-bar-label"><span>${label}</span><span>${val}${max===40?'%':'%'}</span></div>
    <div class="ter-bar-track"><div class="ter-bar-fill ${colorCls}" style="width:0%" data-w="${pct}"></div></div>
  </div>`;
}

function closeTerritoryModal(){
  document.getElementById('terModal').classList.remove('open');
  document.body.style.overflow='';
}

function closeModalOnOverlay(e){
  if(e.target===document.getElementById('terModal')) closeTerritoryModal();
}

function switchModalTab(panel,btn){
  document.querySelectorAll('.ter-modal-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.ter-modal-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('modal-'+panel).classList.add('active');
}

// ── GALLERY TABS ────────────────────────────────────────────────────
function switchTab(type,btn){
  document.querySelectorAll('.media-pane').forEach(p=>p.style.display='none');
  document.querySelectorAll('.mtab').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  if(type==='all') document.querySelectorAll('.media-pane').forEach(p=>p.style.display='block');
  else{ const pane=document.getElementById('tab-'+type); if(pane)pane.style.display='block'; }
}

function switchGalTab(type){
  document.querySelectorAll('.media-pane').forEach(p=>p.style.display='none');
  document.querySelectorAll('.mtab').forEach(b=>b.classList.remove('active'));
  const btn=document.getElementById('mtab-'+type);
  if(btn) btn.classList.add('active');
  const pane=document.getElementById('tab-'+type);
  if(pane) pane.style.display='block';
  if(type==='all') document.querySelectorAll('.media-pane').forEach(p=>p.style.display='block');
}

document.getElementById('mediaInput').addEventListener('change',function(e){
  const files=Array.from(e.target.files);
  if(!files.length)return;
  const imgs=files.filter(f=>f.type.startsWith('image/'));
  const vids=files.filter(f=>f.type.startsWith('video/'));
  const auds=files.filter(f=>f.type.startsWith('audio/'));
  document.getElementById('cnt-all').textContent=files.length;
  document.getElementById('cnt-image').textContent=imgs.length;
  document.getElementById('cnt-video').textContent=vids.length;
  document.getElementById('cnt-audio').textContent=auds.length;
  if(imgs.length) document.getElementById('photoGrid').innerHTML='';
  if(vids.length) document.getElementById('videoGrid').innerHTML='';
  if(auds.length) document.getElementById('audioGrid').innerHTML='';
  imgs.forEach(file=>{
    const r=new FileReader();
    r.onload=ev=>{
      const d=document.createElement('div'); d.className='gal-item';
      d.innerHTML='<img src="'+ev.target.result+'" alt="'+file.name+'" loading="lazy"><div class="ov"><span>🔍</span></div>';
      d.addEventListener('click',()=>openLb(ev.target.result));
      document.getElementById('photoGrid').appendChild(d);
    }; r.readAsDataURL(file);
  });
  vids.forEach(file=>{
    const url=URL.createObjectURL(file);
    const c=document.createElement('div'); c.className='video-card';
    c.innerHTML='<video controls preload="metadata"><source src="'+url+'" type="'+file.type+'"></video><div class="vc-info"><div class="vc-name">'+file.name+'</div><div class="vc-meta"><span class="vc-badge">VIDEO</span> Testimonio</div></div>';
    document.getElementById('videoGrid').appendChild(c);
  });
  auds.forEach(file=>{
    const url=URL.createObjectURL(file);
    const c=document.createElement('div'); c.className='audio-card';
    c.innerHTML='<div class="audio-thumb">🎵</div><div class="audio-info"><div class="audio-title">'+file.name.replace(/[_-]/g,' ')+'</div><div class="audio-meta"><span class="audio-badge">AUDIO</span> Testimonio · CAEDI</div><div class="waveform"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><audio controls preload="metadata"><source src="'+url+'" type="'+file.type+'"></audio></div>';
    document.getElementById('audioGrid').appendChild(c);
  });
  const tabs=document.querySelectorAll('.mtab');
  if(imgs.length&&!vids.length&&!auds.length) switchTab('image',tabs[1]);
  else if(vids.length&&!imgs.length&&!auds.length) switchTab('video',tabs[2]);
  else if(auds.length&&!imgs.length&&!vids.length) switchTab('audio',tabs[3]);
  else switchTab('all',tabs[0]);
});

// ── LIGHTBOX ────────────────────────────────────────────────────────
function openLb(src){document.getElementById('lbImg').src=src;document.getElementById('lb').classList.add('open');}
function closeLb(){document.getElementById('lb').classList.remove('open');}

// ── CHATBOT ─────────────────────────────────────────────────────────
function toggleChat(){document.getElementById('chatPanel').classList.toggle('open');}
async function sendMsg(){
  const inp=document.getElementById('chatIn');
  const msgs=document.getElementById('chatMsgs');
  const txt=inp.value.trim(); if(!txt)return;
  msgs.innerHTML+='<div class="musr">'+txt+'</div>'; inp.value=''; msgs.scrollTop=msgs.scrollHeight;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt})});
    const d=await r.json();
    setTimeout(()=>{msgs.innerHTML+='<div class="mbot">'+d.response+'</div>';msgs.scrollTop=msgs.scrollHeight;},320);
  }catch(e){msgs.innerHTML+='<div class="mbot">Error al conectar.</div>';}
}

// ── WHATSAPP / COMMUNITY MODULE (Real SQLite backend) ────────────────
const chatConfigs = {
  general:        {name:'CAEDI General', status:'Canal principal · OnLife Afro', avatar:'🌍'},
  choco:          {name:'Líderes del Chocó', status:'en línea · Consejo comunitario', avatar:'🌿'},
  buenaventura:   {name:'Consejo Buenaventura', status:'en línea · Puerto del Pacífico', avatar:'⚓'},
  tumaco:         {name:'Comunidad Tumaco', status:'en línea · Nariño', avatar:'🌊'},
  investigadores: {name:'Investigadores USTA', status:'en línea · CAEDI · Grupo activo', avatar:'🔬'},
  sanandres:      {name:'Comunidad Raizal San Andrés', status:'en línea · Archipiélago', avatar:'🏝️'},
  pacificosur:    {name:'Pacífico Sur · Consejos Comunitarios', status:'en línea · Territorios colectivos', avatar:'🌺'},
};

const waGroupLinks = {
  general:        document.querySelector('a.wa-group-btn[href*="general"]')?.href || '#',
  choco:          document.querySelectorAll('a.wa-group-btn')[1]?.href || '#',
  buenaventura:   document.querySelectorAll('a.wa-group-btn')[2]?.href || '#',
  tumaco:         document.querySelectorAll('a.wa-group-btn')[3]?.href || '#',
  investigadores: document.querySelectorAll('a.wa-group-btn')[4]?.href || '#',
  sanandres:      document.querySelectorAll('a.wa-group-btn')[5]?.href || '#',
  pacificosur:    document.querySelectorAll('a.wa-group-btn')[6]?.href || '#',
};

let currentRoom = 'general';
let myName = localStorage.getItem('onlife_name') || 'Visitante';
let pollInterval = null;

// Set saved name on load
document.addEventListener('DOMContentLoaded', ()=>{
  const nameInput = document.getElementById('waSenderName');
  if(nameInput) nameInput.value = myName;
});

function saveName(){
  const inp = document.getElementById('waSenderName');
  myName = inp.value.trim() || 'Visitante';
  localStorage.setItem('onlife_name', myName);
  showStatus('✅ Nombre guardado: '+myName);
}

function openChat(room){
  currentRoom = room;
  const cfg = chatConfigs[room] || chatConfigs.general;
  document.querySelectorAll('.wa-contact').forEach(c=>c.classList.remove('active'));
  const el = document.querySelector(`.wa-contact[onclick*="${room}"]`);
  if(el) el.classList.add('active');
  document.getElementById('waChatAvatar').textContent = cfg.avatar;
  document.getElementById('waChatName').textContent = cfg.name;
  document.getElementById('waChatStatus').textContent = cfg.status;
  loadMessages();
}

async function loadMessages(){
  try{
    const r = await fetch('/api/community/messages?room='+currentRoom);
    const data = await r.json();
    const container = document.getElementById('waMessages');
    container.innerHTML = '<div class="wa-date-separator"><span>Hoy</span></div>';
    if(data.messages && data.messages.length){
      data.messages.forEach(m=>{
        const isMine = m.sender === myName;
        container.innerHTML += `<div class="wa-msg ${isMine?'sent':'recv'}">
          <div class="wa-bubble">
            ${!isMine?`<div style="font-size:11px;font-weight:700;color:var(--terra);margin-bottom:3px;">${m.sender}</div>`:''}
            ${m.text}
            <div class="wa-bubble-time">${m.ts} ${isMine?'✓✓':''}</div>
          </div>
        </div>`;
      });
      // Update sidebar preview
      const last = data.messages[data.messages.length-1];
      const preview = document.getElementById('last-'+currentRoom);
      if(preview) preview.textContent = last.sender+': '+last.text.substring(0,30);
    } else {
      container.innerHTML += '<div class="wa-date-separator"><span>Sin mensajes aún — ¡sé el primero!</span></div>';
    }
    container.scrollTop = container.scrollHeight;
  } catch(e){
    console.error('Error loading messages:', e);
  }
}

async function sendWaMsg(){
  const inp = document.getElementById('waInput');
  const txt = inp.value.trim();
  if(!txt) return;
  inp.value = '';
  try{
    await fetch('/api/community/send', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({room: currentRoom, sender: myName, text: txt})
    });
    await loadMessages();
  } catch(e){
    // Optimistic UI fallback
    const container = document.getElementById('waMessages');
    const now = new Date().toLocaleTimeString('es',{hour:'2-digit',minute:'2-digit'});
    container.innerHTML += `<div class="wa-msg sent"><div class="wa-bubble">${txt}<div class="wa-bubble-time">${now} ✓</div></div></div>`;
    container.scrollTop = container.scrollHeight;
  }
}

function openWaGroup(){
  const links = document.querySelectorAll('a.wa-group-btn');
  const rooms = ['general','choco','buenaventura','tumaco','investigadores','sanandres','pacificosur'];
  const idx = rooms.indexOf(currentRoom);
  const link = links[idx]?.href;
  if(link && link !== '#' && link !== window.location.href+'#'){
    window.open(link, '_blank');
  } else {
    showStatus('💡 Añade el enlace de WhatsApp en WHATSAPP_GROUPS en app.py');
  }
}

function filterContacts(query){
  document.querySelectorAll('.wa-contact').forEach(c=>{
    const name = c.dataset.name||'';
    c.style.display = name.toLowerCase().includes(query.toLowerCase()) ? '' : 'none';
  });
}

function initiateCall(type){
  const bar = document.getElementById('waCallBar');
  const text = document.getElementById('waCallBarText');
  const cfg = chatConfigs[currentRoom] || chatConfigs.general;
  text.textContent = `${type==='video'?'📹 Videollamada':'📞 Llamada de voz'} · ${cfg.name}`;
  bar.style.display = 'flex';
  showStatus(type==='video'?'📹 Iniciando videollamada...':'📞 Iniciando llamada de voz...');
}

function joinCall(type){
  document.getElementById('waCallBar').style.display='none';
  showStatus(type==='video'?'📹 En producción: abre cámara vía WebRTC':'📞 En producción: llamada vía WebRTC P2P');
}

function endCall(){
  document.getElementById('waCallBar').style.display='none';
  showStatus('❌ Llamada rechazada');
}

// Auto-refresh messages every 5 seconds
setInterval(loadMessages, 5000);

// Init
loadMessages();

// ── PWA ─────────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' })
      .then(reg => {
        console.log('[PWA] Service Worker registered:', reg.scope);
        reg.addEventListener('updatefound', () => {
          const newWorker = reg.installing;
          newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
              showStatus('🔄 Nueva versión disponible. Recarga la página.');
            }
          });
        });
      })
      .catch(err => console.log('[PWA] SW registration failed:', err));
  });
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data && event.data.type === 'SYNC_COMPLETE') showStatus('✅ Mensajes sincronizados');
  });
}

let deferredPrompt = null;
const banner = document.getElementById('pwaBanner');
const installBtn = document.getElementById('pwaInstallBtn');
const dismissBtn = document.getElementById('pwaDismissBtn');

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  const dismissed = localStorage.getItem('pwa-dismissed');
  if (!dismissed) setTimeout(() => banner.classList.add('show'), 3000);
});

if (installBtn) {
  installBtn.addEventListener('click', async () => {
    if (!deferredPrompt) { showStatus('💡 En Chrome: Menú → Instalar aplicación'); return; }
    banner.classList.remove('show'); deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') showStatus('🎉 ¡OnLife Afro instalada exitosamente!');
    deferredPrompt = null;
  });
}

if (dismissBtn) {
  dismissBtn.addEventListener('click', () => {
    banner.classList.remove('show');
    localStorage.setItem('pwa-dismissed', '1');
  });
}

window.addEventListener('appinstalled', () => {
  banner.classList.remove('show'); deferredPrompt = null;
  showStatus('🎉 ¡App instalada! Búscala en tu escritorio.');
});

function showStatus(msg, duration=4000) {
  const el = document.getElementById('pwaStatus');
  el.textContent = msg; el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), duration);
}

window.addEventListener('offline', () => showStatus('📵 Sin conexión — modo offline activo', 0));
window.addEventListener('online',  () => showStatus('✅ Conexión restaurada'));

// Init community chat
loadMessages();

// ── SPLASH SCREEN ────────────────────────────────────────────────────
window.addEventListener('load', () => {
  setTimeout(() => {
    document.getElementById('splash').classList.add('hidden');
  }, 2000);
});

// ── DARK MODE ────────────────────────────────────────────────────────
function toggleDark(){
  document.body.classList.toggle('dark');
  const isDark = document.body.classList.contains('dark');
  document.getElementById('darkBtn').textContent = isDark ? '☀️ Claro' : '🌙 Oscuro';
  localStorage.setItem('onlife_dark', isDark ? '1' : '0');
}
if(localStorage.getItem('onlife_dark') === '1'){
  document.body.classList.add('dark');
  const btn = document.getElementById('darkBtn');
  if(btn) btn.textContent = '☀️ Claro';
}

// ── SEARCH ───────────────────────────────────────────────────────────
function openSearch(){
  document.getElementById('searchOverlay').classList.add('open');
  setTimeout(()=>document.getElementById('searchInput').focus(), 100);
}
function closeSearch(){
  document.getElementById('searchOverlay').classList.remove('open');
  document.getElementById('searchInput').value = '';
  document.getElementById('searchResults').innerHTML = '<div class="search-empty">Escribe para buscar territorios, infografías y más...</div>';
}
function closeSearchOnOverlay(e){
  if(e.target === document.getElementById('searchOverlay')) closeSearch();
}
document.addEventListener('keydown', e => { if(e.key==='Escape') closeSearch(); });

let searchTimeout;
async function doSearch(q){
  clearTimeout(searchTimeout);
  if(q.length < 2){
    document.getElementById('searchResults').innerHTML = '<div class="search-empty">Escribe al menos 2 caracteres...</div>';
    return;
  }
  searchTimeout = setTimeout(async()=>{
    try{
      const r = await fetch('/api/search?q='+encodeURIComponent(q));
      const data = await r.json();
      const container = document.getElementById('searchResults');
      if(!data.results.length){
        container.innerHTML = '<div class="search-empty">No se encontraron resultados para "'+q+'"</div>';
        return;
      }
      container.innerHTML = data.results.map(res => {
        const action = res.type==='territory'
          ? `onclick="closeSearch();openTerritoryModal('${res.slug}');return false;" href="#"`
          : `href="${res.action}" target="${res.type==='pdf'?'_blank':'_self'}"`;
        return `<a class="search-result-item" ${action}>
          <div class="search-result-icon">${res.icon}</div>
          <div style="flex:1">
            <div class="search-result-title">${res.title}</div>
            <div class="search-result-desc">${res.desc}</div>
          </div>
          <span class="search-result-type">${res.type}</span>
        </a>`;
      }).join('');
    } catch(e){ console.error(e); }
  }, 300);
}

// ── SCROLL TO TOP ─────────────────────────────────────────────────────
window.addEventListener('scroll', ()=>{
  const btn = document.getElementById('scrollTop');
  if(btn) btn.classList.toggle('visible', window.scrollY > 400);
});

// ── VISITOR COUNTER ───────────────────────────────────────────────────
(async()=>{
  try{
    const r = await fetch('/api/visitor', {method:'POST'});
    const d = await r.json();
    const el = document.getElementById('visitorCount');
    if(el) el.textContent = d.total.toLocaleString('es');
  } catch(e){}
})();

// ── EVENTS LOADER ─────────────────────────────────────────────────────
async function loadEvents(){
  try{
    const r = await fetch('/api/events');
    const events = await r.json();
    const grid = document.getElementById('eventsGrid');
    if(!grid) return;
    if(!events.length){
      grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted);">No hay eventos próximos.</div>';
      return;
    }
    grid.innerHTML = events.map(ev => {
      const d = new Date(ev.date);
      const day = d.getDate();
      const mon = d.toLocaleDateString('es',{month:'short'}).toUpperCase();
      const waLink = ev.link ? `<a class="event-link" href="${ev.link}" target="_blank">💬 Unirse al grupo</a>` : '';
      return `<div class="event-card">
        <div class="event-date-box"><div class="ev-day">${day}</div><div class="ev-mon">${mon}</div></div>
        <div class="event-info">
          <h4>${ev.title}</h4>
          <p>🕐 ${ev.time} &nbsp;·&nbsp; 📍 ${ev.location}</p>
          <div class="event-meta"><span class="event-tag">${ev.territory}</span></div>
          ${waLink}
        </div>
      </div>`;
    }).join('');
  } catch(e){ console.error(e); }
}
loadEvents();

// ── TESTIMONIALS ──────────────────────────────────────────────────────
async function submitTestimonial(){
  const name = document.getElementById('testName').value.trim() || 'Anónimo';
  const territory = document.getElementById('testTerritory').value;
  const message = document.getElementById('testMessage').value.trim();
  if(!message){ showStatus('⚠️ Escribe tu testimonio antes de enviar.'); return; }
  try{
    const r = await fetch('/api/testimonials/submit', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, territory, message})
    });
    const d = await r.json();
    document.getElementById('testSuccess').style.display = 'block';
    document.getElementById('testMessage').value = '';
    showStatus('✅ ¡Testimonio enviado! Gracias por compartir.');
    setTimeout(()=>{ document.getElementById('testSuccess').style.display='none'; }, 5000);
  } catch(e){ showStatus('❌ Error al enviar. Intenta de nuevo.'); }
}

// ── ACCESSIBILITY ────────────────────────────────────────────────────
let fontScale = 0;
function adjustFont(dir){
  fontScale = Math.max(-2, Math.min(3, fontScale + dir));
  document.body.style.fontSize = (16 + fontScale * 2) + 'px';
  localStorage.setItem('onlife_font', fontScale);
}
function toggleHighContrast(){
  document.body.classList.toggle('high-contrast');
  localStorage.setItem('onlife_contrast', document.body.classList.contains('high-contrast') ? '1' : '0');
}
function resetAccessibility(){
  fontScale = 0;
  document.body.style.fontSize = '';
  document.body.classList.remove('high-contrast');
  localStorage.removeItem('onlife_font');
  localStorage.removeItem('onlife_contrast');
}
// Restore saved accessibility settings
(()=>{
  const f = localStorage.getItem('onlife_font');
  if(f){ fontScale = parseInt(f); document.body.style.fontSize = (16 + fontScale * 2) + 'px'; }
  if(localStorage.getItem('onlife_contrast')==='1') document.body.classList.add('high-contrast');
})();

// ── AUTH SYSTEM ──────────────────────────────────────────────────────
let currentUser = JSON.parse(localStorage.getItem('onlife_user') || 'null');

function openAuth(){ document.getElementById('authModal').classList.add('open'); }
function closeAuth(){ document.getElementById('authModal').classList.remove('open'); }
function closeAuthOnOverlay(e){ if(e.target===document.getElementById('authModal')) closeAuth(); }
function switchAuthTab(tab, btn){
  document.querySelectorAll('.auth-tab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('auth-login').style.display = tab==='login' ? 'block' : 'none';
  document.getElementById('auth-register').style.display = tab==='register' ? 'block' : 'none';
  document.getElementById('authError').style.display = 'none';
  document.getElementById('authSuccess').style.display = 'none';
}

async function doLogin(){
  const username = document.getElementById('loginUser').value.trim();
  const password = document.getElementById('loginPass').value;
  if(!username||!password){ showAuthError('Completa todos los campos.'); return; }
  try{
    const r = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password})});
    const d = await r.json();
    if(d.error){ showAuthError(d.error); return; }
    currentUser = d.user;
    localStorage.setItem('onlife_user', JSON.stringify(d.user));
    myName = d.user.name;
    document.getElementById('waSenderName').value = myName;
    updateAuthChip();
    closeAuth();
    showStatus('✅ Bienvenido, '+d.user.name+'!');
  } catch(e){ showAuthError('Error de conexión.'); }
}

async function doRegister(){
  const name = document.getElementById('regName').value.trim();
  const username = document.getElementById('regUser').value.trim();
  const password = document.getElementById('regPass').value;
  if(!name||!username||!password){ showAuthError('Completa todos los campos.'); return; }
  if(password.length < 6){ showAuthError('La contraseña debe tener al menos 6 caracteres.'); return; }
  try{
    const r = await fetch('/api/auth/register', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name,username,password})});
    const d = await r.json();
    if(d.error){ showAuthError(d.error); return; }
    document.getElementById('authSuccess').textContent = '✅ Cuenta creada. Ahora ingresa con tus datos.';
    document.getElementById('authSuccess').style.display = 'block';
    setTimeout(()=>switchAuthTab('login', document.querySelectorAll('.auth-tab')[0]), 1500);
  } catch(e){ showAuthError('Error de conexión.'); }
}

function doLogout(){
  currentUser = null;
  localStorage.removeItem('onlife_user');
  updateAuthChip();
  showStatus('👋 Sesión cerrada correctamente.');
}

function showAuthError(msg){
  const el = document.getElementById('authError');
  el.textContent = '⚠️ '+msg;
  el.style.display = 'block';
}

function updateAuthChip(){
  const chip = document.getElementById('authChip');
  if(!chip) return;
  if(currentUser){
    const initials = currentUser.name.split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2);
    chip.innerHTML = `<div class="user-chip" onclick="doLogout()">
      <div class="user-chip-avatar">${initials}</div>
      <span class="user-chip-name">${currentUser.name.split(' ')[0]}</span>
      <span style="color:rgba(255,255,255,.4);font-size:10px;">✕</span>
    </div>`;
  } else {
    chip.innerHTML = '<button class="dark-toggle" onclick="openAuth()" style="background:rgba(255,255,255,.08);">👤 Ingresar</button>';
  }
}

// Restore session
if(currentUser){
  myName = currentUser.name;
  document.addEventListener('DOMContentLoaded', ()=>{
    updateAuthChip();
    const ni = document.getElementById('waSenderName');
    if(ni) ni.value = myName;
  });
}

// ── PRIVACY ──────────────────────────────────────────────────────────
function openPrivacy(){ document.getElementById('privacyModal').classList.add('open'); }
function closePrivacy(){ document.getElementById('privacyModal').classList.remove('open'); }
function closePrivacyOnOverlay(e){ if(e.target===document.getElementById('privacyModal')) closePrivacy(); }

// ── IMPACT STATS LOADER ──────────────────────────────────────────────
async function loadImpactStats(){
  try{
    const [statsR, visR, testR] = await Promise.all([
      fetch('/api/stats'),
      fetch('/api/visitor/count'),
      fetch('/api/testimonials')
    ]);
    const stats = await statsR.json();
    const vis   = await visR.json();
    const tests = await testR.json();

    const set = (id, val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
    set('impactVisitors',    vis.total.toLocaleString('es'));
    set('impactTestimonials', tests.length || '0');
    set('impactPdfs',        stats.total_pdfs || '0');
    set('impactMedia',       (stats.total_photos+stats.total_videos+stats.total_audios) || '0');
    set('kpiVisitors',       vis.total.toLocaleString('es'));

    // Messages count
    const msgR = await fetch('/api/community/messages?room=general');
    const msgD = await msgR.json();
    set('impactMessages', msgD.messages?.length || '0');
  } catch(e){ console.error('Impact stats error:', e); }
}
loadImpactStats();

// ── MOBILE NAV ACTIVE STATE ──────────────────────────────────────────
const sections = ['dashboard','territorios','galeria','comunidad','graficas'];
window.addEventListener('scroll', ()=>{
  const scrollY = window.scrollY;
  sections.forEach(id=>{
    const el = document.getElementById(id);
    if(!el) return;
    const btn = document.querySelector(`.mob-nav-btn[href="#${id}"]`);
    if(!btn) return;
    const top = el.offsetTop - 120;
    const bottom = top + el.offsetHeight;
    btn.classList.toggle('active', scrollY >= top && scrollY < bottom);
  });
});

// ── COMPARE TOOL ──────────────────────────────────────────────────────
const METRIC_LABELS = {
  poverty: 'Pobreza', unemployment: 'Desempleo', connectivity: 'Conectividad',
  education: 'Educación (años)', healthcare: 'Acceso a salud', youth_unemployment: 'Desempleo juvenil'
};
const METRIC_MAX = {
  poverty:100, unemployment:40, connectivity:100,
  education:15, healthcare:100, youth_unemployment:50
};
const METRIC_INVERSE = ['poverty','unemployment','youth_unemployment']; // lower is better

async function runCompare(){
  const a = document.getElementById('compareA').value;
  const b = document.getElementById('compareB').value;
  if(!a || !b || a===b){
    document.getElementById('compareGrid').style.display='none';
    document.getElementById('compareEmpty').style.display='block';
    return;
  }
  try{
    const r = await fetch(`/api/compare?a=${a}&b=${b}`);
    const data = await r.json();
    if(data.error){ showStatus('❌ '+data.error); return; }
    document.getElementById('compareEmpty').style.display='none';
    document.getElementById('compareGrid').style.display='grid';
    const grid = document.getElementById('compareGrid');
    const makeCard = (territory, side) => {
      const bars = Object.entries(data.comparison).map(([metric, vals])=>{
        const val = vals[side];
        const max = METRIC_MAX[metric] || 100;
        const pct = Math.min(Math.round((val/max)*100), 100);
        const isGood = METRIC_INVERSE.includes(metric) ? val < (side==='a'?vals['b']:vals['a']) : val > (side==='a'?vals['b']:vals['a']);
        const color = isGood ? 'var(--green)' : 'var(--terra)';
        const unit = metric==='education' ? ' años' : '%';
        return `<div class="compare-bar-group">
          <div class="compare-bar-label"><span>${METRIC_LABELS[metric]}</span><span style="color:${color};font-weight:700;">${val}${unit}</span></div>
          <div class="compare-bar-track"><div class="compare-bar-fill" style="width:${pct}%;background:${color};"></div></div>
        </div>`;
      }).join('');
      return `<div class="compare-card">
        <h3>${territory.icon} ${territory.name} <small style="font-size:12px;color:rgba(255,255,255,.4);font-family:'DM Sans',sans-serif;">${territory.region}</small></h3>
        ${bars}
      </div>`;
    };
    grid.innerHTML = makeCard(data.a,'a') + makeCard(data.b,'b');
  } catch(e){ showStatus('❌ Error al comparar.'); }
}
</script>
</body>
</html>"""

# =============================================================
# ROUTES
# =============================================================

import json

@app.route("/sw.js")
def service_worker():
    from flask import Response
    sw_path = os.path.join(STATIC_FOLDER, "sw.js")
    with open(sw_path, "r") as f:
        content = f.read()
    return Response(content, mimetype="application/javascript",
                    headers={"Service-Worker-Allowed": "/"})

@app.route("/")
def home():
    # Add photo URL to each territory
    territories_with_photos = []
    for t in TERRITORIES:
        t_copy = dict(t)
        t_copy["photo"] = get_territory_photo(t["slug"])
        territories_with_photos.append(t_copy)

    return render_template_string(
        HTML,
        territories=territories_with_photos,
        territories_json=json.dumps(territories_with_photos),
        dashboards=DASHBOARDS,
        news=NEWS,
        media=get_gallery_media(),
        pdfs=get_pdfs(),
        hero_photo=get_hero_photo(),
        icons=ICONS,
        wa_groups=WHATSAPP_GROUPS,
    )

@app.route("/gallery/<filename>")
def gallery_file(filename):
    return send_from_directory(GALLERY_FOLDER, filename)

@app.route("/pdfs/<filename>")
def pdf_file(filename):
    return send_from_directory(PDF_FOLDER, filename, as_attachment=True)

@app.route("/territories/<filename>")
def territory_file(filename):
    return send_from_directory(TERRITORY_FOLDER, filename)

@app.route("/static/<path:filename>")
def static_file(filename):
    return send_from_directory(STATIC_FOLDER, filename)

@app.route("/api/territories")
def api_territories():
    territories_with_photos = []
    for t in TERRITORIES:
        t_copy = dict(t)
        t_copy["photo"] = get_territory_photo(t["slug"])
        territories_with_photos.append(t_copy)
    return jsonify({
        "project":"OnLife Afro","version":"4.0-pwa",
        "institution":"CAEDI · Universidad Santo Tomás",
        "territories":territories_with_photos
    })

@app.route("/api/pdfs")
def api_pdfs():
    return jsonify({"pdfs": get_pdfs()})

@app.route("/api/media")
def api_media():
    return jsonify(get_gallery_media())

@app.route("/api/chat", methods=["POST"])
def api_chat():
    msg = (request.get_json(force=True) or {}).get("message","").lower()
    reply = CHATBOT["default"]
    for kw, text in CHATBOT.items():
        if kw != "default" and kw in msg:
            reply = text; break
    return jsonify({"response": reply})

@app.route("/api/community/messages")
def api_community_messages():
    room = request.args.get("room", "general")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sender, text, ts FROM messages WHERE room=? ORDER BY id DESC LIMIT 60",
            (room,)
        ).fetchall()
    msgs = [{"sender": r["sender"], "text": r["text"], "ts": r["ts"]} for r in reversed(rows)]
    return jsonify({"room": room, "messages": msgs})

@app.route("/api/community/send", methods=["POST"])
def api_community_send():
    data = request.get_json(force=True) or {}
    room   = data.get("room",   "general")
    sender = data.get("sender", "Visitante")[:40]
    text   = data.get("text",   "").strip()[:500]
    if not text:
        return jsonify({"error": "empty message"}), 400
    ts = datetime.now().strftime("%H:%M")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages(room, sender, text, ts) VALUES(?,?,?,?)",
            (room, sender, text, ts)
        )
        conn.commit()
    return jsonify({"status": "sent", "ts": ts})

@app.route("/api/community/call", methods=["POST"])
def api_community_call():
    data = request.get_json(force=True) or {}
    call_type = data.get("type","voice")
    contact = data.get("contact","general")
    return jsonify({
        "status":"initiated",
        "type":call_type,
        "contact":contact,
        "note":"En producción PWA completa usaría señalización WebRTC para llamadas P2P."
    })

@app.route("/api/stats")
def api_stats():
    n = len(TERRITORIES)
    media = get_gallery_media()
    return jsonify({
        "avg_poverty":      round(sum(t["poverty"]      for t in TERRITORIES)/n,1),
        "avg_unemployment": round(sum(t["unemployment"] for t in TERRITORIES)/n,1),
        "avg_connectivity": round(sum(t["connectivity"] for t in TERRITORIES)/n,1),
        "total_territories": n,
        "total_photos":  sum(1 for m in media if m["type"]=="image"),
        "total_videos":  sum(1 for m in media if m["type"]=="video"),
        "total_audios":  sum(1 for m in media if m["type"]=="audio"),
        "total_pdfs":    len(get_pdfs()),
    })

# ── TESTIMONIALS ────────────────────────────────────────────────────

@app.route("/api/testimonials", methods=["GET"])
def api_get_testimonials():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name, territory, message, ts FROM testimonials WHERE approved=1 ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/testimonials/submit", methods=["POST"])
def api_submit_testimonial():
    data = request.get_json(force=True) or {}
    name      = data.get("name","Anónimo")[:60]
    territory = data.get("territory","general")[:40]
    message   = data.get("message","").strip()[:800]
    if not message:
        return jsonify({"error":"empty message"}), 400
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO testimonials(name,territory,message,approved,ts) VALUES(?,?,?,1,?)",
            (name, territory, message, ts)
        )
        conn.commit()
    return jsonify({"status":"submitted","message":"Testimonio recibido. Gracias!"})

@app.route("/api/events")
def api_events():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, date, time, location, territory, link FROM events ORDER BY date ASC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/visitor", methods=["POST"])
def api_visitor():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        conn.execute("INSERT INTO visitors(ts) VALUES(?)", (ts,))
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
    return jsonify({"total": total})

@app.route("/api/visitor/count")
def api_visitor_count():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
    return jsonify({"total": total})

@app.route("/api/search")
def api_search():
    q = request.args.get("q","").lower().strip()
    if not q or len(q) < 2:
        return jsonify({"results":[]})
    results = []
    for t in TERRITORIES:
        if q in t["name"].lower() or q in t["desc"].lower() or q in t.get("history","").lower():
            results.append({"type":"territory","icon":t["icon"],"title":t["name"],"desc":t["desc"],"action":"#territorios","slug":t["slug"]})
    for p in get_pdfs():
        if q in p["title"].lower() or q in p["desc"].lower():
            results.append({"type":"pdf","icon":"📄","title":p["title"],"desc":p["desc"],"action":p["url"]})
    return jsonify({"query":q,"results":results[:8]})

@app.route("/api/compare")
def api_compare():
    a = request.args.get("a","")
    b = request.args.get("b","")
    ta = next((t for t in TERRITORIES if t["slug"]==a), None)
    tb = next((t for t in TERRITORIES if t["slug"]==b), None)
    if not ta or not tb:
        return jsonify({"error":"Territory not found"}), 404
    metrics = ["poverty","unemployment","connectivity","education","healthcare","youth_unemployment"]
    comparison = {m: {"a": ta.get(m,0), "b": tb.get(m,0)} for m in metrics}
    return jsonify({
        "a": {"name":ta["name"],"icon":ta["icon"],"region":ta["region"]},
        "b": {"name":tb["name"],"icon":tb["icon"],"region":tb["region"]},
        "comparison": comparison
    })

# ── AUTH ROUTES ─────────────────────────────────────────────────────
import hashlib

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True) or {}
    name     = data.get("name","").strip()[:60]
    username = data.get("username","").strip()[:40].lower()
    password = data.get("password","")
    if not name or not username or not password:
        return jsonify({"error":"Completa todos los campos"}), 400
    if len(password) < 6:
        return jsonify({"error":"Contraseña muy corta"}), 400
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users(username,password,name,role,created) VALUES(?,?,?,?,?)",
                (username, hash_pw(password), name, "community", ts)
            )
            conn.commit()
        return jsonify({"status":"created","message":"Cuenta creada exitosamente"})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"error":"Ese nombre de usuario ya existe"}), 409
        return jsonify({"error":"Error al crear cuenta"}), 500

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    username = data.get("username","").strip().lower()
    password = data.get("password","")
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, username, role FROM users WHERE username=? AND password=?",
            (username, hash_pw(password))
        ).fetchone()
        if not row:
            return jsonify({"error":"Usuario o contraseña incorrectos"}), 401
        conn.execute("UPDATE users SET last_seen=? WHERE id=?",
                     (datetime.now().strftime("%Y-%m-%d %H:%M"), row["id"]))
        conn.commit()
    return jsonify({"status":"ok","user":{"id":row["id"],"name":row["name"],"username":row["username"],"role":row["role"]}})

# =============================================================
# ENTRY POINT
# =============================================================

if __name__ == "__main__":
    print("="*62)
    print("  ONLIFE AFRO PLATFORM v6.0 PWA")
    print("  CAEDI · Universidad Santo Tomás · 2026")
    print("="*62)
    print("  ▶  http://127.0.0.1:5000")
    print()
    print("  Media      → static/gallery/     (jpg, mp4, mp3 ...)")
    print("  PDFs       → static/pdfs/        (auto-served for download)")
    print("  Territories → static/territories/ (e.g. choco.jpg)")
    print("="*62)
    app.run(debug=True, port=5000)
