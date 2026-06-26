#!/bin/sh
set -e

echo "[entrypoint] FocusBarber — ambiente: ${DJANGO_SETTINGS_MODULE}"

# ---------- 1) Esperar o banco de dados (PRD §13.4.6) ----------
python - <<'PY'
import os, socket, sys, time

host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "5432"))
deadline = 60
waited = 0
while waited < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] Banco disponível em {host}:{port} ({waited}s)")
            break
    except OSError:
        print(f"[entrypoint] Aguardando banco {host}:{port}... ({waited}s)")
        time.sleep(2)
        waited += 2
else:
    print("[entrypoint] Banco não respondeu a tempo — abortando.", file=sys.stderr)
    sys.exit(1)
PY

# ---------- 2) Migrations ----------
python manage.py migrate --noinput

# ---------- 3) collectstatic --clear (PRD §13.5) ----------
# Reexecutado a cada boot: reconstrói STATIC_ROOT de forma limpa.
python manage.py collectstatic --noinput --clear

echo "[entrypoint] Pronto. Iniciando: $@"
exec "$@"