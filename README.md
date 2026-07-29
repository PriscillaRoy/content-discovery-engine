# Semantic Search Engine

Embedding-based semantic search and personalized movie recommendations using FAISS + Graph + RAG,
with production-grade serving via Gunicorn, Redis caching, Milvus vector database, Feast feature store,
and Supabase PostgreSQL + Auth.

**Stack:** Python · FastAPI · FAISS · Milvus · sentence-transformers · NetworkX · Redis · Feast · Supabase · Ollama

---

## Progress

- [x] Session 1 — Embeddings + FAISS index
- [x] Session 2 — Graph layer (NetworkX)
- [x] Session 3 — RAG layer (Ollama)
- [x] Session 4 — FastAPI + precision@k evaluation
- [x] Session 5 — Production optimization (Redis, Gunicorn, Milvus)
- [x] Session 6 — Feature store (Feast) + personalized recommendations
- [x] Session 7 — Cloud migration (Supabase PostgreSQL + Auth, modular API)
- [ ] Session 8 — Upstash Redis + Zilliz Cloud + backend deployment
- [ ] Session 9 — React/Next.js frontend on Vercel
- [ ] Session 10 — Internet Archive integration + watch history pipeline

---

## Prerequisites

Before running the project, start these services:

### 1. Ollama (local LLM for RAG explanations)
```bash
brew install ollama
brew services start ollama
ollama pull llama3.2
```

### 2. Redis (caching layer — two instances)
```bash
brew install redis
brew services start redis                            # port 6379 — app cache
redis-server --port 6380 --daemonize yes            # port 6380 — Feast online store
redis-cli ping                                       # should return PONG
```

### 3. Milvus (vector database for streaming index)
```bash
# Download compose file (one time only)
curl -o milvus-compose.yml https://raw.githubusercontent.com/milvus-io/milvus/v2.4.0/deployments/docker/standalone/docker-compose.yml

# Start Milvus + etcd + MinIO
docker compose -f milvus-compose.yml up -d

# Verify all three containers are running
docker ps

# Stop when done
docker compose -f milvus-compose.yml down
```

---

## Setup

```bash
# Clone the repo
git clone https://github.com/PriscillaRoy/content-discovery-engine.git
cd content-discovery-engine

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file in the project root:

```bash
# Database backend: "sqlite" (local) or "supabase" (production)
DB_BACKEND=sqlite

# Supabase (required for DB_BACKEND=supabase)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-publishable-key
SUPABASE_DB_URL=postgresql://postgres:your-encoded-password@db.your-project.supabase.co:5432/postgres

# Redis (optional — defaults to localhost:6379)
# REDIS_URL=rediss://your-upstash-url   # Upstash in production

# Milvus (optional — defaults to localhost:19530)
# MILVUS_URI=https://your-zilliz-endpoint
# MILVUS_TOKEN=your-zilliz-token

# Search backend: "faiss" (default) or "milvus"
SEARCH_BACKEND=faiss
```

> ⚠️ Never commit `.env` to Git. It's in `.gitignore`.

---

## Build the indexes

Run these in order — each step depends on the previous:

```bash
python3 -m core.embeddings    # embed descriptions + build FAISS index
python3 -m core.graph         # build NetworkX graph
```

### Supabase migration (first time only)

```bash
python3 -m store.migrate      # creates tables + seeds 101 movies into Supabase
```

### Feast feature store

```bash
# Materialize features into Redis online store
cd store/feature_repo
feast materialize 2024-01-01T00:00:00 $(date -u +"%Y-%m-%dT%H:%M:%S")
cd ../..
```

---

## Start the server

```bash
# Development (single worker, auto-reload)
./start.sh dev

# Local simulation (2 Gunicorn workers — Mac Apple Silicon fix included)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ./start.sh local

# Production (full workers based on CPU count)
GUNICORN_WORKERS=25 ./start.sh local
```

---

## API Endpoints

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/signup` | Create a new user account |
| POST | `/auth/signin` | Sign in — returns JWT access token |
| POST | `/auth/signout` | Invalidate JWT |
| GET | `/auth/me` | Return current authenticated user |

### Movies
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/similar/{title}` | FAISS similarity search |
| POST | `/recommend` | Combined FAISS + Graph recommendations |
| POST | `/explain` | Full RAG pipeline with LLM explanation |
| POST | `/search` | Search by description (FAISS or Milvus backend) |

### Features
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/features/{movie_id}` | Feast online feature lookup |
| POST | `/recommend/personalized` | Two-tower personalized recommendations |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/evaluate` | precision@k evaluation |
| GET | `/cache/stats` | Redis cache statistics |
| DELETE | `/cache/clear` | Invalidate all cached results |
| POST | `/milvus/upsert` | Real-time movie upsert into Milvus |

Interactive API docs: `http://localhost:8000/docs`

---

## Configuration

All settings in `config.py`. Override any value via `.env`:

```python
FAISS_INDEX_TYPE = "ivf"            # flat | ivf | ivfpq
FAISS_METRIC     = "ip"             # ip | l2
EMBEDDING_MODEL  = "all-MiniLM-L6-v2"
OLLAMA_MODEL     = "llama3.2"
REDIS_TTL        = 3600             # cache expiry in seconds
SEARCH_BACKEND   = "faiss"          # faiss | milvus
DB_BACKEND       = "sqlite"         # sqlite | supabase
```

---

## Project Structure

```
content-discovery-engine/
├── api/
│   ├── main.py                  # FastAPI app — mounts routers only
│   ├── dependencies.py          # AppResources dependency injection
│   └── routers/
│       ├── auth.py              # /auth/* endpoints + JWT dependency
│       ├── movies.py            # /similar, /recommend, /explain, /search
│       ├── features.py          # /features, /recommend/personalized
│       └── admin.py             # /health, /evaluate, /cache/*, /milvus/upsert
├── core/
│   ├── embeddings.py            # FAISS index + sentence-transformers
│   ├── graph.py                 # NetworkX graph layer
│   ├── rag.py                   # RAG pipeline (retrieve → augment → generate)
│   └── milvus_store.py          # Milvus vector DB (real-time upsert)
├── store/
│   ├── database.py              # Router: sqlite or supabase backend
│   ├── database_sqlite.py       # SQLite implementation
│   ├── database_supabase.py     # PostgreSQL/Supabase implementation
│   ├── supabase_client.py       # Supabase auth + PostgreSQL connection
│   ├── migrate.py               # One-time Supabase table creation + seeding
│   ├── cache.py                 # Redis caching layer
│   ├── feature_store.py         # Custom feature store
│   ├── generate_features.py     # Generates parquet for Feast
│   └── feature_repo/            # Feast configuration
│       ├── feature_store.yaml
│       ├── features.py
│       └── data/                # Parquet offline store
├── data/
│   └── movies.csv               # 101-movie dataset
├── indexes/                     # Generated indexes (not committed)
│   ├── movies.faiss
│   ├── movies.db
│   ├── embeddings.npy
│   └── movies_graph.pkl
├── config.py                    # All configuration + env var loading
├── generate_data.py             # Dataset generation
├── start.sh                     # Server startup script
├── gunicorn_config.py           # Gunicorn production config
├── requirements.txt
└── .env                         # Local secrets (never committed)
```

---

## Architecture

```
Client
  │
  ▼
FastAPI (Gunicorn + UvicornWorker)
  │
  ├── Auth Router ──────────────── Supabase Auth (JWT)
  │
  ├── Movies Router
  │     ├── FAISS Index ────────── Semantic similarity search
  │     ├── NetworkX Graph ─────── Genre + similarity traversal
  │     └── Ollama (llama3.2) ──── RAG explanation generation
  │
  ├── Features Router
  │     ├── Feast Feature Store ── Redis online store (port 6380)
  │     └── Two-Tower Ranking ──── FAISS+Graph retrieval → Feast re-ranking
  │
  └── Admin Router
        ├── Redis Cache ─────────── TTL-based response caching (port 6379)
        └── Milvus ──────────────── Real-time vector upsert
```

---

## Database Schema (Supabase)

```sql
movies        — id, title, year, genre, description
users         — id (UUID), email, created_at
ratings       — user_id, movie_id, rating (1-5), watched_pct
watch_history — user_id, movie_id, watched_pct, watched_at
```