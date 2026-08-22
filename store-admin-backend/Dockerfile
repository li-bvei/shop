FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# MySQL client headers aren't needed — PyMySQL is a pure-Python driver
# (see config/__init__.py's install_as_MySQLdb() shim), so no build-essential
# / default-libmysqlclient-dev layer is required here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Doesn't touch the database, so it's safe to run at build time — needs no
# real SECRET_KEY/DB connection, just the settings module to import cleanly.
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# .env is not baked into the image — mount it (or pass real env vars) at
# `docker run`/compose time. manage.py migrate is run as a one-off command
# by the deployer, not automatically on every container start, so a bad
# migration never silently rolls out with a container restart.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
