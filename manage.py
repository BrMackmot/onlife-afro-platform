#!/usr/bin/env python3
"""OnLife Afro — management CLI.

Usage:
    python manage.py initdb
    python manage.py createadmin <username> <password> [full name]
    python manage.py setrole <username> <community|institutional|admin>
    python manage.py listusers
    python manage.py pipeline
    python manage.py stats
    python manage.py runserver [port]

Importing app.py initialises (and migrates) the SQLite database automatically,
so `initdb` is mostly a confirmation step.
"""

import sys

# Importing app runs init_db() and creates the folders/database.
import app as onlife
from app import app as flask_app, get_db, hash_password, db_metrics, try_run_pipeline

VALID_ROLES = {"community", "institutional", "admin"}


def _usage_and_exit(msg=None, code=1):
    if msg:
        print("Error:", msg, "\n")
    print(__doc__)
    sys.exit(code)


def cmd_initdb(_args):
    with flask_app.app_context():
        db = get_db()
        m = db_metrics(db)
    print("Database ready.")
    print(f"  users={m['users']}  contributions={m['total']} "
          f"(approved={m['approved']}, pending={m['pending']})")


def cmd_createadmin(args):
    if len(args) < 2:
        _usage_and_exit("createadmin needs <username> <password> [name]")
    username, password = args[0], args[1]
    name = " ".join(args[2:]) if len(args) > 2 else username
    with flask_app.app_context():
        db = get_db()
        exists = db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if exists:
            db.execute("UPDATE users SET password=?, name=?, role='admin' WHERE username=?",
                       (hash_password(password), name, username))
            print(f"Updated existing user '{username}' -> role=admin, password reset.")
        else:
            db.execute("INSERT INTO users (username,password,name,role) VALUES (?,?,?,?)",
                       (username, hash_password(password), name, "admin"))
            print(f"Created admin user '{username}'.")
        db.commit()


def cmd_setrole(args):
    if len(args) < 2:
        _usage_and_exit("setrole needs <username> <role>")
    username, role = args[0], args[1].lower()
    if role not in VALID_ROLES:
        _usage_and_exit(f"role must be one of {sorted(VALID_ROLES)}")
    with flask_app.app_context():
        db = get_db()
        cur = db.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        db.commit()
        if cur.rowcount:
            print(f"User '{username}' is now role={role}.")
        else:
            print(f"No user named '{username}'.")


def cmd_listusers(_args):
    with flask_app.app_context():
        db = get_db()
        rows = db.execute("SELECT id,username,name,role,created_at FROM users ORDER BY id").fetchall()
    if not rows:
        print("No users yet.")
        return
    print(f"{'id':>3}  {'username':<18} {'role':<14} {'name'}")
    for r in rows:
        print(f"{r['id']:>3}  {r['username']:<18} {r['role']:<14} {r['name']}")


def cmd_pipeline(_args):
    print("Running DANE/GEIH pipeline...")
    ok = try_run_pipeline()
    print("Pipeline finished." if ok else "Pipeline skipped (load_geih_data.py not found or failed).")


def cmd_stats(_args):
    with flask_app.app_context():
        db = get_db()
        m = db_metrics(db)
    print("OnLife Afro — database stats")
    for k, v in m.items():
        print(f"  {k:<12} {v}")


def cmd_runserver(args):
    port = int(args[0]) if args else 5000
    print(f"Starting dev server on http://127.0.0.1:{port}")
    flask_app.run(host="0.0.0.0", port=port)


COMMANDS = {
    "initdb": cmd_initdb,
    "createadmin": cmd_createadmin,
    "setrole": cmd_setrole,
    "listusers": cmd_listusers,
    "pipeline": cmd_pipeline,
    "stats": cmd_stats,
    "runserver": cmd_runserver,
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        _usage_and_exit(code=0)
    cmd, rest = argv[0], argv[1:]
    fn = COMMANDS.get(cmd)
    if not fn:
        _usage_and_exit(f"unknown command '{cmd}'")
    fn(rest)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BrokenPipeError:
        # Output was piped to a command that closed early (e.g. `| head`).
        try:
            sys.stdout.close()
        except Exception:
            pass
