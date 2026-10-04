# ══════════════════════════════════════════════════════════════
#  OnLife Afro — archivo WSGI para PythonAnywhere
# ══════════════════════════════════════════════════════════════
#
#  QUÉ ES ESTE ARCHIVO
#  Es lo primero que PythonAnywhere ejecuta cuando alguien abre el sitio.
#  Su único trabajo es preparar el entorno y entregar la aplicación.
#
#  DÓNDE VA
#  No se sube junto a app.py. Se pega dentro del archivo que ya existe en el
#  servidor: pestaña Web → sección Code → «WSGI configuration file»
#  (algo como /var/www/tuusuario_pythonanywhere_com_wsgi.py).
#  Abre ese archivo, borra todo lo que tenga y pega esto.
#
#  QUÉ HAY QUE CAMBIAR
#  Solo las dos líneas marcadas con  ← CAMBIAR.
#  Todo lo demás puede quedarse tal cual.
#
#  DESPUÉS
#  Guardar (Ctrl+S) y pulsar el botón verde «Reload» de la pestaña Web.
# ══════════════════════════════════════════════════════════════

import os
import sys

# ── 1. Dónde vive tu proyecto ─────────────────────────────────
# Es la carpeta donde subiste app.py. Míralo en la pestaña «Files»:
# la ruta aparece arriba. Suele ser /home/TU_USUARIO/algo.
RUTA_PROYECTO = "/home/TU_USUARIO/onlifeafro"        # ← CAMBIAR

if RUTA_PROYECTO not in sys.path:
    sys.path.insert(0, RUTA_PROYECTO)
os.chdir(RUTA_PROYECTO)   # para que la base de datos y data/ se encuentren


# ── 2. Ajustes que no deben estar escritos dentro del código ──
# Una «variable de entorno» es un valor que la aplicación lee al arrancar.
# Se ponen aquí, y no en app.py, porque son secretos: quien vea el código no
# debe poder entrar como administrador.

# Firma las sesiones de quien inicia sesión. Si cambia, todo el mundo tiene
# que volver a entrar; no pasa nada más. Esta ya es aleatoria: sirve tal cual.
os.environ["SECRET_KEY"] = "w3mSYYwDmo11IPeYJOOgQdm6z38noE3QVujd0CNS95Us0QWSEPjqnZQjByyk98H1"

# Tu cuenta de administración de la plataforma. Elige el usuario que quieras;
# la contraseña ya es aleatoria y puedes dejarla o poner la tuya.
# IMPORTANTE: si no declaras estas dos, la aplicación se inventa una
# contraseña y LA ESCRIBE en onlife_afro.log, donde queda a la vista.
os.environ["ADMIN_USERNAME"] = "comboni_admin"       # ← CAMBIAR si quieres otro
os.environ["ADMIN_PASSWORD"] = "3xjoSJ3brlNypf8r"

# Marca el sitio como producción: activa cookies seguras y desactiva el modo
# de depuración. PythonAnywhere ya lo detecta solo, pero declararlo no sobra.
os.environ["PRODUCTION"] = "1"


# ── 3. Sala de voz: NADA QUE HACER AQUÍ ───────────────────────
# Las llamadas funcionan sin configurar nada. Estas líneas están comentadas
# a propósito y solo se activan si algún día montas tu propio servidor de
# retransmisión (coturn), que sirve para que dos teléfonos con datos móviles
# puedan conectarse cuando el operador lo impide.
# Si no tienes ese servidor —lo normal hoy— DÉJALAS COMENTADAS.
#
# os.environ["TURN_URL"]  = "turn:mi-servidor.org:3478"
# os.environ["TURN_USER"] = "usuario"
# os.environ["TURN_PASS"] = "clave"
# os.environ["STUN_URL"]  = "stun:mi-servidor.org:3478"


# ── 4. Entregar la aplicación ─────────────────────────────────
# PythonAnywhere busca una variable llamada «application». La importación va
# al final, después de las variables, porque app.py las lee al importarse.
from app import app as application    # noqa: E402
