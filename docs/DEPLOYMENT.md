# Deployment Guide

## Opción A: On-premise (PC del cliente) con Docker Compose

### Servicios incluidos

- `frontend` (Next.js)
- `backend-api` (FastAPI)
- `backend-worker` (Celery)
- `postgres`
- `redis`

### Puesta en marcha

```bash
cp .env.docker.example .env
docker compose up -d --build
```

### Validación rápida

1. Abrir `http://localhost:3000`.
2. Verificar API en `http://localhost:8000/healthz`.
3. Subir lote de PDFs y confirmar progreso en UI.

### Escalado de procesamiento

```bash
docker compose up -d --scale backend-worker=2
```

Ajustar concurrencia por contenedor:

```bash
CELERY_WORKER_CONCURRENCY=8
```

## Opción B: Frontend en Vercel + Backend en DigitalOcean

### Frontend (Vercel)

- Root Directory: `frontend`
- Install Command: `pnpm install`
- Build Command: `pnpm build`
- Variable requerida:

```bash
NEXT_PUBLIC_API_BASE_URL=https://<backend-domain>
```

### Backend (DigitalOcean)

Usar `backend/.do/app.example.yaml` como base.

Componentes mínimos:

1. `api` ejecutando `./start.sh`
2. `queue-worker` ejecutando `./worker.sh`

### Variables obligatorias para producción

```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://...
FRONTEND_BASE_URL=https://<frontend-domain>
CORS_ALLOWED_ORIGINS=https://<frontend-domain>
TRUSTED_HOSTS=<backend-domain>
FORCE_HTTPS_REDIRECT=true
AUTH_JWT_SECRET_KEY=<long-random-secret>
AUTH_DEBUG_RETURN_RESET_TOKEN=false
AUTH_ALLOWED_EMAILS=user1@empresa.cl,user2@empresa.cl
REDIS_URL=redis://.../0
CELERY_RESULT_BACKEND=redis://.../1
CELERY_WORKER_CONCURRENCY=8
CELERY_MAX_TASKS_PER_CHILD=50
MAX_PDFS_PER_BATCH=70
```

## Post-deploy checklist

1. Login correcto con usuario autorizado.
2. Recuperación/cambio de contraseña funcionando.
3. Carga de 70 PDFs aceptada.
4. Batch finaliza en `completed`.
5. Exportación PDF normal y pickeo bodega/local.
