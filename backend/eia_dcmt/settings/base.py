"""Base settings for the EiA2030 Data Collection Monitoring Tool.

12-factor / env-driven. Environment-specific overrides live in dev.py / stg.py /
prod.py / test.py. Mirrors the current R deployment which pulls a `.Renviron`
per environment from S3 — here we use a `.env` file + real environment variables.
"""
from __future__ import annotations

from pathlib import Path

import environ
from celery.schedules import crontab
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["*"]),
)

# Read a .env file if present (local dev). In stg/prod, real env vars win.
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# --- Applications -----------------------------------------------------------
DJANGO_APPS = [
    # django-unfold — modern admin UI. Must precede django.contrib.admin.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
]

# Auth0 (OIDC) is the PRIMARY registration / sign-in path for end users — most
# enumerators are field staff outside CGIAR, so Auth0 (email/social) is what they
# use. Microsoft Entra ID is an OPTIONAL fallback OIDC provider (for CGIAR/IITA
# staff), env-gated and off until creds are supplied — never a replacement for
# Auth0. Local email+password signup/login stay disabled (see the auth section
# below and the redirects in eia_dcmt/urls.py). Platform Admins still use the
# Django /admin login (superuser) for back-office tasks.
THIRD_PARTY_APPS = [
    "rest_framework",
    "guardian",
    "django_celery_beat",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
]

AUTH0_DOMAIN = env("AUTH0_DOMAIN", default="")
AUTH0_CLIENT_ID = env("AUTH0_CLIENT_ID", default="")
AUTH0_CLIENT_SECRET = env("AUTH0_CLIENT_SECRET", default="")
# True only when all three creds are present; the login page uses this to show a
# clear "not configured" message instead of a 500 from the OIDC discovery fetch.
AUTH0_CONFIGURED = bool(AUTH0_DOMAIN and AUTH0_CLIENT_ID and AUTH0_CLIENT_SECRET)

# Microsoft Entra ID — OPTIONAL fallback OIDC provider (CGIAR/IITA staff). Stays
# off until all three are supplied; Auth0 remains the primary login either way.
ENTRA_TENANT_ID = env("ENTRA_TENANT_ID", default="")
ENTRA_CLIENT_ID = env("ENTRA_CLIENT_ID", default="")
ENTRA_CLIENT_SECRET = env("ENTRA_CLIENT_SECRET", default="")
ENTRA_CONFIGURED = bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET)

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.rbac",
    "apps.projects",
    "apps.config_admin",
    "apps.ingestion",
    "apps.submissions",
    "apps.review",
    "apps.validation",
    "apps.fieldwork",
    "apps.kpi",
    "apps.dashboards",
    "apps.console",
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files (incl. the admin's CSS/JS) under gunicorn, where
    # Django's runserver auto-static is not available.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "eia_dcmt.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.common.context_processors.site",
                "apps.dashboards.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "eia_dcmt.wsgi.application"
ASGI_APPLICATION = "eia_dcmt.asgi.application"

# --- Database ---------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://eia:eia@localhost:5432/eia_dcmt",
    )
}

# --- Auth -------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "guardian.backends.ObjectPermissionBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Product name shown in the UI (title bars, sidebar brand, login). Configurable
# so the platform can be white-labelled per deployment.
SITE_NAME = env("SITE_NAME", default="Fieldbase")

# Sender for platform email (digests, alerts, notifications).
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default=f"{SITE_NAME} <no-reply@fieldbase.local>"
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SITE_ID = 1

# Auth0-only: no local signup, no password login. The login URL points straight
# at the Auth0 OIDC provider, and SOCIALACCOUNT_LOGIN_ON_GET skips the interstitial.
ACCOUNT_EMAIL_VERIFICATION = "none"  # Auth0 verifies identity
# Our custom User logs in by email and has NO username field — tell allauth so it
# doesn't try to validate/populate a username during the Auth0 social signup.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]  # no username, no password (handled by Auth0)
LOGIN_REDIRECT_URL = "/"
# Anonymous users land on our login page (a "Continue with Auth0" button), which
# degrades gracefully when Auth0 isn't configured instead of 500-ing.
LOGIN_URL = "/login/"
AUTH0_LOGIN_URL = "/accounts/oidc/auth0/login/"
ENTRA_LOGIN_URL = "/accounts/oidc/entra/login/"
ACCOUNT_LOGOUT_ON_GET = True
SOCIALACCOUNT_LOGIN_ON_GET = True

ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"
# Auth0 is always registered (primary). Entra ID is appended only when its creds
# are present, so it never interferes with the Auth0-only default deployment.
_OIDC_APPS = [
    {
        "provider_id": "auth0",
        "name": "Auth0",
        "client_id": AUTH0_CLIENT_ID,
        "secret": AUTH0_CLIENT_SECRET,
        "settings": {
            "server_url": f"https://{AUTH0_DOMAIN}/.well-known/openid-configuration",
        },
    }
]
if ENTRA_CONFIGURED:
    _OIDC_APPS.append({
        "provider_id": "entra",
        "name": "Microsoft Entra ID",
        "client_id": ENTRA_CLIENT_ID,
        "secret": ENTRA_CLIENT_SECRET,
        "settings": {
            "server_url": (
                f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
                "/v2.0/.well-known/openid-configuration"
            ),
        },
    })

SOCIALACCOUNT_PROVIDERS = {"openid_connect": {"APPS": _OIDC_APPS}}

GUARDIAN_RAISE_403 = True

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"user": "1000/hour"},
}

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
# The DatabaseScheduler syncs these into django_celery_beat on startup.
CELERY_BEAT_SCHEDULE = {
    # Daily ONA sync (replaces the R `0 0 * * * Rscript dataprocessing.R` cron).
    "daily-source-sync": {
        "task": "ingestion.sync_all_use_cases",
        "schedule": crontab(hour=0, minute=0),
    },
    "review-digest-weekday-mornings": {
        "task": "review.send_review_digests",
        "schedule": crontab(hour=7, minute=0, day_of_week="mon-fri"),
    },
    # M&E KPI aggregates — near-real-time refresh.
    "kpi-rebuild-15min": {
        "task": "kpi.rebuild_all",
        "schedule": crontab(minute="*/15"),
    },
    # M&E threshold alerts — evaluate rules hourly and notify watchers.
    "kpi-run-alerts-hourly": {
        "task": "kpi.run_alerts",
        "schedule": crontab(minute=5),
    },
}

# --- External integrations (parity with R .Renviron) ------------------------
ONA_BASE_URL = env("ONA_BASE_URL", default="https://api.ona.io")
ONA_TOKEN = env("ONA_TOKEN", default="")
# Write-back of reviewer edits to the source server is OFF by default (it mutates
# live records). Enable per environment once validated against a sandbox.
WRITEBACK_ENABLED = env.bool("WRITEBACK_ENABLED", default=False)
IPINFO_BASE_URL = env("IPINFO_BASE_URL", default="https://ipinfo.io")
# Shared secret guarding the collection-server webhook (ODK Central / ONA →
# instant re-sync). Empty = webhooks disabled (endpoint returns 503). The server
# must send it as the X-Webhook-Token header or a ?token= query param.
COLLECTION_WEBHOOK_SECRET = env("COLLECTION_WEBHOOK_SECRET", default="")
# Debounce window (seconds): collapse a burst of webhook hits for one project
# into a single re-sync to avoid sync storms.
COLLECTION_WEBHOOK_DEBOUNCE_SECONDS = env.int("COLLECTION_WEBHOOK_DEBOUNCE_SECONDS", default=30)

# --- i18n / tz --------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static -----------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (e.g. published XLSForms).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- django-unfold admin theme (forest green to match the app) ---------------
UNFOLD = {
    "SITE_TITLE": f"{SITE_NAME} Administration",
    "SITE_HEADER": SITE_NAME,
    "SITE_SUBHEADER": "Field data & M&E",
    "SITE_SYMBOL": "eco",  # Material symbol (leaf) shown in the sidebar header
    # Clicking the admin header / "View site" returns to the main app dashboard.
    "SITE_URL": "/",
    # Quick links shown in a dropdown next to the admin site header.
    "SITE_DROPDOWN": [
        {"icon": "dashboard", "title": "Open dashboard", "link": "/"},
        {"icon": "logout", "title": "Sign out", "link": reverse_lazy("account_logout")},
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "232 244 238",
            "100": "209 232 219",
            "200": "167 211 187",
            "300": "120 188 152",
            "400": "74 156 117",
            "500": "45 128 92",
            "600": "26 104 72",
            "700": "13 92 63",
            "800": "10 70 48",
            "900": "7 51 34",
            "950": "4 33 22",
        },
    },
    # The admin holds only system-level models now (review/audit + Django/3rd-party
    # system tables); all project config, access and field data live in the in-app
    # console. Let unfold auto-build the nav from whatever stays registered.
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "items": [
                    {"title": "Open dashboard", "icon": "arrow_back", "link": "/"},
                    {"title": "Reviews", "icon": "fact_check",
                     "link": reverse_lazy("admin:review_review_changelist")},
                    {"title": "Review actions", "icon": "history",
                     "link": reverse_lazy("admin:review_reviewactionlog_changelist")},
                ],
            },
        ],
    },
}

# Path where per-project YAML config seeds live.
PROJECT_CONFIG_DIR = BASE_DIR / "config" / "projects"
