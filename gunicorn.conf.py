"""Gunicorn configuration for OnLife Afro.

Run with:
    gunicorn wsgi:app --config gunicorn.conf.py

Most values can be overridden by environment variables so the same file works
locally and on Render / Docker / any Linux host.
"""

import multiprocessing
import os

# ── Networking ──────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# ── Workers ─────────────────────────────────────────────────
# The app uses SQLite, which serialises writes; a modest number of sync
# workers is the safe default. Override with WEB_CONCURRENCY if needed.
workers = int(os.environ.get("WEB_CONCURRENCY", min(3, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")

# ── Timeouts ────────────────────────────────────────────────
# Longer timeout so the optional DANE pipeline run on first request can finish.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))
graceful_timeout = 30
keepalive = 5

# ── Logging ─────────────────────────────────────────────────
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")   # stdout
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")     # stderr
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# ── Misc ────────────────────────────────────────────────────
preload_app = False   # keep False so each worker initialises its own DB handle
proc_name = "onlife-afro"
