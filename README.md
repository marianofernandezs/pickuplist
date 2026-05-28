# Generador Lista VIGE (Determinístico, sin IA)

Aplicación para cargar múltiples facturas PDF, extraer productos con parsing determinístico y exportar listas de pickeo.

## Stack

- Frontend: Next.js 16 + React 19 + TypeScript + Tailwind
- Backend: FastAPI + SQLAlchemy
- Cola: Celery + Redis
- Base de datos: PostgreSQL
- Extracción PDF: PyMuPDF + pdfplumber
- Exportación PDF: ReportLab

## Docker completo (recomendado para cliente en PC local)

Este proyecto ya está preparado para correr todo junto en Docker:

- `frontend` (Next.js)
- `backend-api` (FastAPI)
- `backend-worker` (Celery)
- `postgres`
- `redis`

### 1. Configurar variables de entorno

```bash
cp .env.docker.example .env
```

### 2. Levantar todo

```bash
docker compose up -d --build
```

### 3. Acceder

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- Healthcheck: `http://localhost:8000/healthz`

### 4. Ver logs

```bash
docker compose logs -f backend-api
# o
docker compose logs -f backend-worker
```

### 5. Crear usuario autorizado

```bash
docker compose exec backend-api python scripts/create_user.py \
  --email admin@empresa.cl \
  --full-name "Administrador VIGE" \
  --password "ClaveSegura123"
```

## Escalado de cola para lotes grandes

El sistema soporta lotes de hasta `70` PDFs y encola `1 tarea por PDF`.

Para mayor paralelismo, puedes levantar más workers:

```bash
docker compose up -d --scale backend-worker=2
```

También puedes ajustar concurrencia por worker en `.env`:

```bash
CELERY_WORKER_CONCURRENCY=8
CELERY_MAX_TASKS_PER_CHILD=50
```

## Rutas frontend

- `/login`: iniciar sesión
- `/forgot-password`: solicitar recuperación
- `/reset-password`: cambiar contraseña con token
- `/`: dashboard protegido

## Desarrollo local sin Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Worker (otra terminal):

```bash
cd backend
source .venv/bin/activate
celery -A app.celery_app:celery_app worker --loglevel=INFO --concurrency=8
```

### Frontend

```bash
cd frontend
pnpm install
cp .env.example .env.local
pnpm dev
```

## Seguridad aplicada

- Autenticación JWT en endpoints de negocio.
- Recuperación de contraseña con token hasheado y expiración.
- CORS y Trusted Hosts configurables.
- Headers de seguridad en frontend y backend.
- Validaciones estrictas en `ENVIRONMENT=production`.

## Limpieza completa del entorno Docker

```bash
docker compose down -v
```

Esto borra contenedores y volúmenes (incluye datos de PostgreSQL y Redis).
