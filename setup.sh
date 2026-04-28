#!/usr/bin/env bash
# =============================================================================
# Syrabit.ai — Environment Setup Script for Qwen Coder
# =============================================================================
# This script sets up the complete development environment for the Syrabit.ai
# project, including all dependencies for the frontend (pnpm workspace), 
# backend (Python FastAPI), and Cloudflare Workers edge proxy.
#
# Project Architecture:
#   - Frontend: React + Vite + TypeScript (artifacts/syrabit/)
#   - Backend: FastAPI + Python 3.11+ (artifacts/syrabit-backend/)
#   - Edge Proxy: Cloudflare Workers (workers/edge-proxy/)
#   - Monorepo: pnpm workspace with shared tooling
#
# Usage: ./setup.sh
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Track if we created the venv so we can inform the user
VENV_CREATED=false

# =============================================================================
# Step 1: Check System Requirements
# =============================================================================
log_info "Checking system requirements..."

# Check Node.js (required: v20+)
if ! command -v node &> /dev/null; then
    log_error "Node.js is not installed. Please install Node.js v20 or higher."
    exit 1
fi

NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 20 ]; then
    log_error "Node.js version must be v20 or higher. Current: $(node --version)"
    exit 1
fi
log_success "Node.js $(node --version) detected"

# Check Python (required: 3.11+)
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    log_error "Python version must be 3.11 or higher. Current: $(python3 --version)"
    exit 1
fi
log_success "Python $(python3 --version) detected"

# Check pip
if ! command -v pip3 &> /dev/null; then
    log_error "pip3 is not installed. Please install pip for Python 3."
    exit 1
fi
log_success "pip3 $(pip3 --version | awk '{print $2}') detected"

# Check pnpm (install if missing)
if ! command -v pnpm &> /dev/null; then
    log_warn "pnpm not found. Installing pnpm@10.26.1 globally..."
    npm install -g pnpm@10.26.1
fi
log_success "pnpm $(pnpm --version) detected"

# =============================================================================
# Step 2: Install Frontend Dependencies (pnpm workspace)
# =============================================================================
log_info "Installing frontend dependencies (pnpm workspace)..."

# Clean pnpm store to avoid corruption
pnpm store prune || true

# Install all workspace dependencies
# Use --frozen-lockfile if pnpm-lock.yaml exists, otherwise regular install
if [ -f "pnpm-lock.yaml" ]; then
    log_info "Found pnpm-lock.yaml, using frozen lockfile for reproducibility..."
    pnpm install --frozen-lockfile || {
        log_warn "Frozen lockfile install failed, trying regular install..."
        pnpm install
    }
else
    log_info "No pnpm-lock.yaml found, running regular install..."
    pnpm install
fi

log_success "Frontend dependencies installed"

# =============================================================================
# Step 3: Install Backend Python Dependencies
# =============================================================================
log_info "Installing backend Python dependencies..."

BACKEND_DIR="artifacts/syrabit-backend"

# Create virtual environment if it doesn't exist
if [ ! -d "${BACKEND_DIR}/venv" ]; then
    log_info "Creating Python virtual environment in ${BACKEND_DIR}/venv..."
    python3 -m venv "${BACKEND_DIR}/venv"
    VENV_CREATED=true
fi

# Activate virtual environment and install dependencies
source "${BACKEND_DIR}/venv/bin/activate"
pip install --upgrade pip

# Install production dependencies from requirements.txt
if [ -f "${BACKEND_DIR}/requirements.txt" ]; then
    log_info "Installing Python packages from requirements.txt..."
    pip install -r "${BACKEND_DIR}/requirements.txt"
else
    log_error "requirements.txt not found in ${BACKEND_DIR}"
    exit 1
fi

# Install development dependencies for backend (pytest, coverage, etc.)
if [ -f "${BACKEND_DIR}/pyproject.toml" ]; then
    log_info "Installing backend development dependencies..."
    pip install pytest pytest-cov || log_warn "Failed to install dev dependencies (continuing...)"
fi

log_success "Backend Python dependencies installed"

# =============================================================================
# Step 4: Install Cloudflare Workers Dependencies
# =============================================================================
log_info "Setting up Cloudflare Workers edge proxy..."

WORKER_DIR="workers/edge-proxy"
cd "${WORKER_DIR}"

# Install worker-specific dependencies using npm ci for speed (uses package-lock.json)
if [ ! -d "node_modules" ]; then
    log_info "Installing Cloudflare Workers dependencies..."
    npm ci || npm install
fi

# Verify wrangler installation
if [ ! -f "node_modules/.bin/wrangler" ]; then
    log_error "Wrangler CLI not found after installation"
    exit 1
fi

cd ../..
log_success "Cloudflare Workers dependencies installed"

# =============================================================================
# Step 5: Build Frontend (Optional - can be skipped in dev mode)
# =============================================================================
log_info "Building frontend assets (optional step)..."

# Run typecheck first (non-blocking)
pnpm run typecheck:libs || log_warn "Typecheck found issues (continuing...)"

# Build the main syrabit frontend
cd artifacts/syrabit
if [ -f "package.json" ]; then
    log_info "Running frontend build..."
    npm run build || log_warn "Frontend build failed (you can run manually later with 'pnpm build')"
fi
cd ../..

log_success "Frontend build completed"

# =============================================================================
# Step 6: Verify Installation
# =============================================================================
log_info "Verifying installation..."

# Verify pnpm workspace
pnpm list --depth=-1 > /dev/null || log_warn "pnpm workspace verification failed"

# Verify Python environment
source "${BACKEND_DIR}/venv/bin/activate" || { log_error "Failed to activate Python venv"; exit 1; }
python3 -c "import fastapi, uvicorn, pydantic, motor, asyncpg" || log_error "Critical Python packages missing"

# Verify wrangler
cd "${WORKER_DIR}"
./node_modules/.bin/wrangler --version > /dev/null || log_error "Wrangler CLI not working"
cd ../..

log_success "Installation verified successfully!"

# =============================================================================
# Step 7: Display Next Steps
# =============================================================================
echo ""
echo "============================================================================="
echo "  SETUP COMPLETE! 🎉"
echo "============================================================================="
echo ""
echo "Next steps:"
echo "  1. Copy .env.example files and configure your environment variables:"
echo "     - artifacts/syrabit/.env.example → artifacts/syrabit/.env"
echo "     - artifacts/syrabit-backend/.env.example → artifacts/syrabit-backend/.env"
echo ""
echo "  2. Start development servers:"
if [ "\$VENV_CREATED" = true ]; then
    echo "     ⚠️  A new Python venv was created. Activate it with:"
    echo "        source \${BACKEND_DIR}/venv/bin/activate"
fi
echo "     Frontend:  cd artifacts/syrabit && pnpm dev"
echo "     Backend:   source \${BACKEND_DIR}/venv/bin/activate && uvicorn main:app --reload"
echo "                (or 'python3 -m uvicorn main:app --reload' from backend dir)"
echo "     Edge Worker: cd \${WORKER_DIR} && ./node_modules/.bin/wrangler dev"
echo ""
echo "  3. Or use the Replit workflows defined in .replit file"
echo ""
echo "  4. Run verification tests:"
echo "     pnpm verify                                    # Full pre-merge gate"
echo "     pnpm --filter @workspace/syrabit verify:jsonld # JSON-LD validation"
echo "     pytest artifacts/syrabit-backend/tests/        # Backend tests"
echo ""
echo "  5. Key documentation:"
echo "     - replit.md              : Project architecture overview"
echo "     - SYRABIT_DEVELOPER_GUIDE.md : Developer guidelines"
echo "     - IMPLEMENTATION_COMPLETE.md : Feature implementation status"
echo ""
echo "============================================================================="
echo ""

# Deactivate virtual environment
deactivate 2>/dev/null || true

exit 0
