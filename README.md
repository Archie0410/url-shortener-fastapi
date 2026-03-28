# URL Shortener API

A scalable, production-ready URL shortener built with **FastAPI**, **PostgreSQL**, and **Redis**.

Converts long URLs into compact Base62-encoded short codes, redirects users with sub-millisecond cache hits, tracks click counts, and supports optional link expiry.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Deploy to Render](#deploy-to-render)
- [Scaling & Production Notes](#scaling--production-notes)

---

## Features

| Feature | Description |
|---------|-------------|
| **Shorten URLs** | `POST /shorten` — accepts a long URL, returns a unique short code |
| **Redirect** | `GET /{short_code}` — 302 redirects to the original URL |
| **Base62 Encoding** | Compact, URL-safe codes generated from database sequence IDs |
| **Click Tracking** | Atomic counter incremented on every successful redirect |
| **Redis Caching** | Hot-path redirects served from cache; graceful fallback to DB |
| **Link Expiry** | Optional `expires_in_days` parameter; expired links return `410 Gone` |
| **Collision Handling** | Automatic retry on rare `IntegrityError` (up to configurable max) |
| **Health Check** | `GET /health` — lightweight liveness probe |

---

## Tech Stack

- **Framework** — [FastAPI](https://fastapi.tiangolo.com/) (async-capable, auto-generated OpenAPI docs)
- **Database** — [PostgreSQL](https://www.postgresql.org/) via SQLAlchemy 2.0 ORM
- **Cache** — [Redis](https://redis.io/) for redirect payload caching
- **Validation** — [Pydantic v2](https://docs.pydantic.dev/) for request/response schemas and settings
- **Server** — [Uvicorn](https://www.uvicorn.org/) (ASGI)
- **Containerisation** — Docker Compose for local Postgres + Redis

---

## Architecture

```
┌───────────┐       ┌──────────────┐       ┌─────────────────┐       ┌────────────┐
│  Client   │──────►│  API Layer   │──────►│  Service Layer  │──────►│  Storage   │
│  (curl /  │       │  routes.py   │       │  url_service.py │       │            │
│  browser) │◄──────│  schemas.py  │◄──────│  redis_cache.py │◄──────│ PostgreSQL │
└───────────┘       │  deps.py     │       │  base62.py      │       │ Redis      │
                    └──────────────┘       └─────────────────┘       └────────────┘
```

**Request flow — Shorten:**
1. Client sends `POST /shorten` with a long URL
2. API layer validates the request body via Pydantic
3. Service layer allocates a Postgres sequence ID → encodes it to Base62
4. Row is inserted into `short_links` table (retry on collision)
5. Result is cached in Redis and returned as JSON

**Request flow — Redirect:**
1. Client hits `GET /{short_code}`
2. Service checks Redis cache first (fast path)
3. On cache miss, queries Postgres and populates Redis for next time
4. Click count is atomically incremented in Postgres
5. Client receives a `302` redirect to the original URL

---

## Project Structure

```
URL Shortner/
├── app/
│   ├── main.py                    # FastAPI app, lifespan (DB tables + Redis ping), logging
│   │
│   ├── core/
│   │   └── config.py              # Settings via pydantic-settings (.env support)
│   │
│   ├── encoding/
│   │   └── base62.py              # Base62 encode / decode (pure functions, no side effects)
│   │
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM model — ShortLink table
│   │   └── session.py             # Engine, connection pool, get_db dependency
│   │
│   ├── services/
│   │   ├── url_service.py         # Business logic — shorten, resolve, click tracking
│   │   └── redis_cache.py         # Cache get/set/delete, TTL management
│   │
│   └── api/
│       ├── schemas.py             # Pydantic request / response models
│       ├── deps.py                # FastAPI dependency injection wiring
│       └── routes.py              # HTTP endpoint handlers
│
├── .env.example                   # Sample environment variables
├── .gitignore
├── build.sh                       # Render build script
├── render.yaml                    # Render Blueprint (IaC)
├── docker-compose.yml             # PostgreSQL 16 + Redis 7 (local dev)
├── requirements.txt               # Python dependencies (pinned minimums)
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (for Postgres and Redis)

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd "URL Shortner"
```

### 2. Start PostgreSQL and Redis

```bash
docker compose up -d
```

This spins up PostgreSQL 16 on port `5432` and Redis 7 on port `6379`.

### 3. Configure environment variables

```bash
cp .env.example .env
```

The defaults in `.env.example` already match the `docker-compose.yml` services — no edits needed for local development.

### 4. Create a virtual environment and install dependencies

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

### 5. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On first launch, the app automatically creates the `short_links` table in Postgres via `create_all`.

### 6. Open the docs

- **Swagger UI** — [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** — [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## API Reference

### `POST /shorten`

Create a new short link.

**Request body:**

```json
{
  "url": "https://example.com/very/long/path?query=value",
  "expires_in_days": 30
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | A valid HTTP/HTTPS URL |
| `expires_in_days` | integer | No | TTL in days (1–3650). Omit for no expiry. |

**Response** `201 Created`:

```json
{
  "short_code": "g8",
  "short_url": "http://localhost:8000/g8",
  "long_url": "https://example.com/very/long/path?query=value",
  "expires_at": "2026-04-26T12:34:56.789012+00:00"
}
```

**cURL example:**

```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com", "expires_in_days": 7}'
```

---

### `GET /{short_code}`

Redirect to the original URL.

| Status | Meaning |
|--------|---------|
| `302 Found` | Redirects to the original long URL |
| `404 Not Found` | Short code does not exist |
| `410 Gone` | Short link has expired |

**cURL example:**

```bash
curl -L http://localhost:8000/g8
```

---

### `GET /health`

Liveness probe for load balancers and orchestrators.

**Response** `200 OK`:

```json
{
  "status": "ok"
}
```

---

## Configuration

All settings are loaded from environment variables (or a `.env` file). See `.env.example` for defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/urlshortener` | SQLAlchemy database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `CACHE_TTL_SECONDS` | `3600` | Max TTL (seconds) for cached redirect payloads |
| `SHORT_URL_BASE` | `http://localhost:8000` | Public origin prepended to short codes in responses |
| `MAX_SHORTEN_ATTEMPTS` | `5` | Number of retries on short code collision |

---

## How It Works

### Short code generation (Base62)

Instead of hashing (which risks collisions), we use a **deterministic approach**:

1. PostgreSQL's `nextval()` provides a globally unique, monotonically increasing integer (e.g. `1000`)
2. That integer is encoded to Base62 (e.g. `1000` → `"g8"`)
3. The mapping is **bijective** — every ID produces a unique code, and every code maps back to exactly one ID

```
Integer:  0  1  2  ...  61  62   63   ...  1000  ...  56,800,235,583
Base62:  "0" "1" "2" ... "Z" "10" "11" ... "g8"  ... "ZZZZZZ"
```

A 6-character code covers over **56 billion** unique URLs.

### Redis caching strategy

- On **shorten**: the new link is immediately cached with key `urlshort:v1:<code>`
- On **redirect**: Redis is checked first; cache miss falls through to Postgres and backfills the cache
- **TTL** is set to `min(CACHE_TTL_SECONDS, seconds_until_link_expiry)` so expired links don't linger in cache
- **All Redis errors are caught** — if Redis goes down, the app degrades to Postgres-only with zero downtime

### Click tracking

Every successful redirect (whether served from cache or DB) triggers:

```sql
UPDATE short_links SET click_count = click_count + 1 WHERE short_code = :code
```

This is an atomic operation — safe under concurrent load without race conditions.

### Link expiry

- When `expires_in_days` is provided, an `expires_at` timestamp is stored
- On redirect, the timestamp is checked; expired links return `410 Gone`
- Expired entries are evicted from Redis when detected (lazy cleanup)

---

## Deploy to Render

The project includes a **Render Blueprint** (`render.yaml`) and build script (`build.sh`) for one-click deployment.

### Option A: Blueprint (automatic)

1. Push this repo to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**
3. Connect your GitHub repo — Render reads `render.yaml` and creates:
   - A **Web Service** (Python, Gunicorn + Uvicorn workers)
   - A **PostgreSQL** database (free tier)
4. You will be prompted to set `SHORT_URL_BASE` — enter the URL Render assigns to your web service (e.g. `https://url-shortener-xxxx.onrender.com`)
5. For **Redis**, create a Redis service separately on Render (Blueprints don't auto-create Redis on the free plan):
   - **New** → **Redis** → pick a name and plan
   - Copy the **Internal Connection URL** (starts with `rediss://`)
   - Add it as the `REDIS_URL` environment variable on your web service
6. Click **Apply** — Render builds, deploys, and gives you a live URL

### Option B: Manual setup

#### 1. Create a PostgreSQL database

- Render Dashboard → **New** → **PostgreSQL**
- Pick the **Free** plan, name it anything
- Once created, copy the **Internal Database URL** (from the database's **Info** tab)

#### 2. Create a Redis instance

- Render Dashboard → **New** → **Redis**
- Pick a plan, name it anything
- Once created, copy the **Internal Connection URL** (starts with `rediss://`)

#### 3. Create a Web Service

- Render Dashboard → **New** → **Web Service**
- Connect your GitHub repo
- Configure:

| Setting | Value |
|---------|-------|
| **Runtime** | Python |
| **Build Command** | `./build.sh` |
| **Start Command** | `gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:$PORT` |

- Add these **Environment Variables**:

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | The Internal Database URL you copied (Render gives `postgres://...` — the app auto-converts it) |
| `REDIS_URL` | The Internal Connection URL from your Redis instance |
| `SHORT_URL_BASE` | Your Render service URL, e.g. `https://url-shortener-xxxx.onrender.com` |
| `PYTHON_VERSION` | `3.11.6` |

- Click **Create Web Service**

#### 4. Verify

Once the deploy finishes:

```bash
# Health check
curl https://url-shortener-xxxx.onrender.com/health

# Create a short link
curl -X POST https://url-shortener-xxxx.onrender.com/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com"}'

# Swagger docs
# https://url-shortener-xxxx.onrender.com/docs
```

### Render-specific notes

- **`DATABASE_URL` format**: Render provides `postgres://user:pass@host/db`. The app's config validator automatically rewrites this to `postgresql+psycopg2://...` for SQLAlchemy.
- **Redis TLS**: Render's Redis uses `rediss://` (TLS). The app detects this scheme and sets `ssl_cert_reqs=None` for Render's internal certificates.
- **Free tier cold starts**: Render's free web services spin down after 15 minutes of inactivity. The first request after a cold start takes ~30 seconds. Upgrade to a paid plan for always-on.
- **Connection limits**: Render's free Postgres allows ~97 connections. The app uses `pool_size=5, max_overflow=10` per worker (2 workers = 30 max connections), well within limits.

---

## Scaling & Production Notes

| Topic | Recommendation |
|-------|----------------|
| **Horizontal scaling** | Run multiple Uvicorn/Gunicorn workers behind a load balancer. Postgres is the single source of truth; Redis handles read amplification. |
| **Database migrations** | Replace `create_all` with [Alembic](https://alembic.sqlalchemy.org/) for safe schema evolution. |
| **Connection pooling** | Tune `pool_size` and `max_overflow` in `app/db/session.py` based on your worker count and expected load. |
| **Cache invalidation** | Currently no `UPDATE` endpoint exists. If you add one, remember to delete the Redis key for the affected short code. |
| **Rate limiting** | Add a middleware or reverse proxy rate limiter (e.g. `slowapi`, Nginx) to prevent abuse of `POST /shorten`. |
| **Custom aliases** | Extend `ShortenRequest` with an optional `custom_code` field and validate it against Base62 charset + uniqueness. |
| **Analytics** | For detailed analytics (referrer, geo, device), log redirect events to a separate analytics table or stream to Kafka. |
| **Monitoring** | Integrate structured logging with your preferred aggregator (ELK, Datadog, etc.). Extend `/health` to check DB and Redis connectivity. |

---

## Requirements

- **Python** 3.10+
- **PostgreSQL** 14+ (tested with 16 via Docker Compose)
- **Redis** 6+ (tested with 7 via Docker Compose)


