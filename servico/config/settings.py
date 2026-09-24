"""Configuração do serviço Milionere (MVP local).

Produção (ver docs/SERVICO.md): Postgres + pgvector, Redis + Celery, R2, allauth. Aqui, no MVP local:
SQLite, jobs em threads no próprio processo (estudio/jobs.py) e arquivos em servico/media/.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # servico/
RAIZ = BASE_DIR.parent                                      # raiz do repositório
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# o pipeline (motor/milionere) grava tudo do serviço dentro de media/, nunca em producao/ do repositório
os.environ.setdefault("MILIONERE_PRODUCAO", str(MEDIA_ROOT / "producao"))
os.environ.setdefault("MILIONERE_SAIDA", str(MEDIA_ROOT / "videos"))
sys.path.insert(0, str(RAIZ / "motor"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-inseguro-troque-em-producao")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "estudio",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3",
                         "OPTIONS": {"timeout": 20}}}  # o site e o produtor escrevem no mesmo arquivo

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 80 * 1024 * 1024  # imagens das cenas vão no corpo do pedido (MVP)
MILIONERE_VIDEOS_SIMULTANEOS = int(os.environ.get("MILIONERE_VIDEOS_SIMULTANEOS", "1"))
