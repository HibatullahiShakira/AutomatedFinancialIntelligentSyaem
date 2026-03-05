# Docker files

Phase 0 local development stack lives in `docker-compose.yml` with these services:

- `db` (Postgres 15)
- `redis` (Redis 7)
- `localstack` (S3, SQS, SageMaker emulation)
- `smtp` (Mailhog for email testing)
- `app` (Django API)
- `celery` (worker)

Run from this folder:

```bash
docker compose up --build
```
