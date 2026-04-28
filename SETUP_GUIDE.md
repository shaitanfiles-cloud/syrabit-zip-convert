# Setup Script Documentation

## `setup.sh` — Complete Environment Setup for Syrabit.ai

This script automates the complete development environment setup for the Syrabit.ai project in Qwen Coder or any compatible development environment.

## What It Does

The setup script performs the following steps:

### 1. **System Requirements Check**
- ✅ Verifies Node.js v20+ is installed
- ✅ Verifies Python 3.11+ is installed  
- ✅ Verifies pip3 is available
- ✅ Installs pnpm@10.26.1 globally if missing

### 2. **Frontend Dependencies (pnpm workspace)**
- Cleans pnpm store to avoid corruption
- Installs all workspace dependencies with frozen lockfile
- Sets up React + Vite + TypeScript tooling

### 3. **Backend Python Dependencies**
- Creates a Python virtual environment in `artifacts/syrabit-backend/venv/`
- Installs all production dependencies from `requirements.txt`:
  - FastAPI, Uvicorn, Gunicorn (web framework)
  - Pydantic, python-multipart (validation)
  - pymongo, motor, asyncpg (databases)
  - openai, google-auth (AI providers)
  - httpx, aiohttp (HTTP clients)
  - PyJWT, passlib, cryptography (security)
  - OpenTelemetry (observability)
  - And 40+ other packages
- Installs development dependencies (pytest, pytest-cov)

### 4. **Cloudflare Workers Edge Proxy**
- Installs worker-specific dependencies
- Sets up Wrangler CLI for local development and deployment

### 5. **Frontend Build (Optional)**
- Runs TypeScript typecheck
- Builds the frontend assets (non-blocking)

### 6. **Installation Verification**
- Verifies pnpm workspace integrity
- Tests critical Python package imports
- Confirms Wrangler CLI functionality

### 7. **Next Steps Display**
- Shows how to configure environment variables
- Provides commands to start all development servers
- Lists verification test commands
- Points to key documentation files

## Usage

```bash
# Make the script executable (only needed once)
chmod +x setup.sh

# Run the setup script
./setup.sh
```

## After Running Setup

### 1. Configure Environment Variables

Copy the example environment files and fill in your values:

```bash
# Frontend environment
cp artifacts/syrabit/.env.example artifacts/syrabit/.env

# Backend environment  
cp artifacts/syrabit-backend/.env.example artifacts/syrabit-backend/.env
```

Edit these files with your actual API keys, database URLs, and other configuration.

### 2. Start Development Servers

**Frontend (React + Vite):**
```bash
cd artifacts/syrabit
pnpm dev
```

**Backend (FastAPI):**
```bash
source artifacts/syrabit-backend/venv/bin/activate
cd artifacts/syrabit-backend
python3 -m uvicorn main:app --reload
# Or: uvicorn main:app --reload
```

**Edge Worker (Cloudflare Workers):**
```bash
cd workers/edge-proxy
./node_modules/.bin/wrangler dev
```

### 3. Run Verification Tests

```bash
# Full pre-merge gate (typecheck + JSON-LD validation)
pnpm verify

# JSON-LD validation only
pnpm --filter @workspace/syrabit verify:jsonld

# Backend Python tests
pytest artifacts/syrabit-backend/tests/
```

## Project Architecture

```
/workspace
├── artifacts/
│   ├── syrabit/           # Frontend: React + Vite + TypeScript
│   └── syrabit-backend/   # Backend: FastAPI + Python 3.11+
├── workers/
│   └── edge-proxy/        # Cloudflare Workers edge proxy
├── scripts/               # Shared scripts and utilities
├── setup.sh              # ← This setup script
└── .replit               # Replit IDE configuration
```

## Key Technologies

### Frontend
- React 18+ with TypeScript
- Vite for bundling and dev server
- Tailwind CSS for styling
- React Router for navigation
- TanStack Query for data fetching
- PWA support with service workers

### Backend
- FastAPI for REST APIs
- Python 3.11+
- MongoDB (motor) & PostgreSQL (asyncpg)
- OpenAI, Google Vertex AI, Groq, Cerebras integrations
- OpenTelemetry for distributed tracing
- JWT authentication

### Edge/Infrastructure
- Cloudflare Workers (Wrangler)
- Cloudflare Pages for frontend hosting
- Cloudflare AI Gateway for LLM caching
- Cloudflare D1 for edge database

## Troubleshooting

### Node.js Version Error
If you get a Node.js version error, upgrade to v20+:
```bash
# Using nvm
nvm install 20
nvm use 20

# Or download from https://nodejs.org/
```

### Python Version Error
If you need Python 3.11+:
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev

# macOS (with Homebrew)
brew install python@3.11
```

### pnpm Installation Fails
```bash
# Try installing via corepack
corepack enable
corepack prepare pnpm@10.26.1 --activate

# Or via npm
npm install -g pnpm@10.26.1
```

### Virtual Environment Issues
If the Python venv creation fails:
```bash
# Manually create the venv
python3 -m venv artifacts/syrabit-backend/venv

# Activate and install dependencies
source artifacts/syrabit-backend/venv/bin/activate
pip install -r artifacts/syrabit-backend/requirements.txt
```

### Wrangler Not Found
```bash
cd workers/edge-proxy
npm install
```

## Integration with Replit

The `.replit` file already includes:
- Module definitions for Node.js, PostgreSQL, and Python
- Post-build step to install pnpm
- Workflow definitions for running the edge proxy
- Port mappings for all services

Run `./setup.sh` once when opening the project in a new environment, then use the Replit run button or workflows.

## Maintenance

To update dependencies after the initial setup:

```bash
# Update frontend dependencies
pnpm install

# Update backend dependencies
source artifacts/syrabit-backend/venv/bin/activate
pip install --upgrade -r artifacts/syrabit-backend/requirements.txt

# Update edge worker dependencies
cd workers/edge-proxy
npm update
```

## Contributing

When adding new dependencies:
1. Add them to the appropriate `package.json` or `requirements.txt`
2. Run `./setup.sh` to verify they install correctly
3. Update this documentation if new tools are introduced

---

**Created for:** Syrabit.ai Development Team  
**Compatible with:** Qwen Coder, Replit, VS Code Dev Containers, local development  
**Last updated:** 2026-04-28
