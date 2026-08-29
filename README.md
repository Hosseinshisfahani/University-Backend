# Backend — Django REST Modular Monolith

Single Django project, multiple isolated domain apps, one shared PostgreSQL database. See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full specification.

## Structure

```
backend/
  manage.py
  requirements.txt
  config/                      # Django project
    settings/
      base.py                  # shared settings (env-driven)
      dev.py                   # DEBUG, localhost CORS, insecure-cookie fallbacks
      prod.py                  # hardened: HSTS, secure cookies, proxy SSL header
    urls.py                    # everything versioned under /api/v1/
    wsgi.py / asgi.py
  apps/
    core/                      # shared abstract models (TimeStampedModel) — no domain logic
    accounts/                  # custom User model + cookie-based JWT auth
    finance/                   # platform wallet, ledger, payments (SEP), withdrawals (IRR)
    university_services/       # domain: core university operational services
    student_services/          # domain: student affairs modules and portals
    institutes/
      psy_institute/           # psychology center (scheduling, tests, workshops, tickets)
    lms_platform/              # domain: LMS for courses and workshops
```

The four domain directories are namespaces. `core`, `accounts`, and `finance` are foundational. `institutes.psy_institute` is the first fully scaffolded domain app.

## Setup

Requires Python 3.12 and PostgreSQL.

```bash
cd backend
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # then edit values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Settings default to `config.settings.dev`; production runs with `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login/` | Validate credentials, set HttpOnly JWT cookies |
| `POST /api/v1/auth/refresh/` | Rotate tokens using the refresh cookie |
| `POST /api/v1/auth/logout/` | Blacklist refresh token, clear cookies |
| `GET /api/v1/auth/me/` | Current user profile |
| `GET /api/v1/auth/csrf/` | Set the CSRF cookie |
| `GET/POST /api/v1/finance/...` | Wallet, ledger, payments (SEP), withdrawals |
| `GET/POST /api/v1/psy/...` | Psychology institute domain API |
| `GET /api/v1/docs/` | Swagger UI (OpenAPI schema at `/api/v1/schema/`) |

## Auth security model

- Access and refresh JWTs are issued **only** as `HttpOnly`, `Secure`, `SameSite=Lax` cookies — never in JSON bodies, never readable by JavaScript.
- The refresh cookie is path-scoped to `/api/v1/auth/` so it never travels with regular API requests.
- Refresh tokens rotate on every refresh and the old one is blacklisted; logout blacklists and clears everything.
- Unsafe methods on cookie-authenticated requests are CSRF-checked (`apps/accounts/authentication.py`); the frontend echoes the CSRF cookie in the `X-CSRFToken` header.

## Rules for new apps

1. One domain concern per app; apps own their models, serializers, views, urls.
2. Reads across apps: direct imports/ORM. Writes across apps: **Django Signals only**.
3. Register new apps in `LOCAL_APPS` (`config/settings/base.py`) and mount their urls in `config/urls.py` under `/api/v1/`.
4. `core` never imports from domain apps.
