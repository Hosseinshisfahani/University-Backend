# Routine commands

Never `docker compose build` or `next build` on the VPS. Never `git add .` (pycache / `github-actions-deploy`).

## Frontend (laptop → auto deploy)

```bash
cd /Users/hossein.sh.isfahani/projects/University/frontend
git add path/to/file
git status
git commit -m "Your message"
git push origin main
```

Wait for University-Frontend Actions: lint/build → GHCR → **Pull frontend on VPS**.

## Backend (laptop → image only)

```bash
cd /Users/hossein.sh.isfahani/projects/University/backend
git add path/to/file
git status
git commit -m "Your message"
git push origin main
```

Wait until **Django check** and **Push GHCR image** are green. Ignore a red **Pull backend on VPS**.

## Backend (VPS — you pull)

```bash
cd /var/www/university
docker compose --env-file compose.env -f docker-compose.prod.yml pull backend
docker compose --env-file compose.env -f docker-compose.prod.yml up -d backend
docker compose --env-file compose.env -f docker-compose.prod.yml logs --tail 40 backend
```

If pull fails with `lookup ghcr.io ... server misbehaving`, fix VPS DNS, then retry.

## Health

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/
curl -fsS -o /dev/null -w "%{http_code}\n" https://icqt.ac.ir/
curl -fsS -o /dev/null -w "%{http_code}\n" https://ayehh.ir/
```

## Superuser (VPS)

```bash
cd /var/www/university
docker compose --env-file compose.env -f docker-compose.prod.yml exec backend \
  python manage.py createsuperuser
```

Django admin: https://ayehh.ir/django-admin/

## Copy nginx / compose (not in the image)

```bash
# after files are on the VPS
cd /var/www/university
docker compose --env-file compose.env -f docker-compose.prod.yml up -d
nginx -t && systemctl reload nginx
```
