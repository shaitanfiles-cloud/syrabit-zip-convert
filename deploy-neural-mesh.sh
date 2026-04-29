#!/bin/bash
set -e

# Syrabit Neural Mesh Deployment Script
# Orchestrates deployment of Frontend → Edge → Core

echo "🚀 Deploying Syrabit Neural Mesh..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
RUST_CORE_DIR="backend/rust-core"
EDGE_DIR="edge"
FRONTEND_DIR="frontend"

# Parse command line arguments
DEPLOY_TARGET="${1:-all}" # all, core, edge, frontend

deploy_rust_core() {
    echo -e "${BLUE}=== Deploying Rust Core ===${NC}"
    
    if [ ! -d "$RUST_CORE_DIR" ]; then
        echo -e "${RED}Error: Rust Core directory not found${NC}"
        return 1
    fi
    
    cd "$RUST_CORE_DIR"
    
    # Build Docker image
    echo -e "${YELLOW}Building Docker image...${NC}"
    docker build -t syrabit-rust-core:latest .
    
    # Tag for registry (optional)
    if [ -n "$DOCKER_REGISTRY" ]; then
        echo -e "${YELLOW}Tagging for registry: $DOCKER_REGISTRY${NC}"
        docker tag syrabit-rust-core:latest "$DOCKER_REGISTRY/syrabit-rust-core:latest"
        docker push "$DOCKER_REGISTRY/syrabit-rust-core:latest"
    fi
    
    # Deploy to Railway (if railway CLI is available)
    if command -v railway &> /dev/null; then
        echo -e "${YELLOW}Deploying to Railway...${NC}"
        railway up --detach
    else
        echo -e "${YELLOW}Railway CLI not found. Manual deployment required.${NC}"
        echo "Run: cd $RUST_CORE_DIR && railway up"
    fi
    
    cd - > /dev/null
    echo -e "${GREEN}✅ Rust Core deployment complete${NC}"
    echo ""
}

deploy_edge_worker() {
    echo -e "${BLUE}=== Deploying Edge Worker ===${NC}"
    
    if [ ! -f "$EDGE_DIR/worker.js" ]; then
        echo -e "${RED}Error: Edge worker file not found${NC}"
        return 1
    fi
    
    cd "$EDGE_DIR"
    
    # Check for Wrangler CLI
    if ! command -v wrangler &> /dev/null; then
        echo -e "${RED}Wrangler CLI not found. Installing...${NC}"
        npm install -g wrangler
    fi
    
    # Deploy to Cloudflare Workers
    echo -e "${YELLOW}Deploying to Cloudflare Workers...${NC}"
    wrangler deploy worker.js --env production
    
    cd - > /dev/null
    echo -e "${GREEN}✅ Edge Worker deployment complete${NC}"
    echo ""
}

deploy_frontend() {
    echo -e "${BLUE}=== Deploying Frontend ===${NC}"
    
    if [ ! -d "$FRONTEND_DIR" ]; then
        echo -e "${RED}Error: Frontend directory not found${NC}"
        return 1
    fi
    
    cd "$FRONTEND_DIR"
    
    # Install dependencies
    echo -e "${YELLOW}Installing dependencies...${NC}"
    if [ -f "pnpm-lock.yaml" ]; then
        pnpm install --frozen-lockfile
    elif [ -f "yarn.lock" ]; then
        yarn install --frozen-lockfile
    else
        npm ci
    fi
    
    # Build
    echo -e "${YELLOW}Building frontend...${NC}"
    npm run build
    
    # Deploy (adjust based on your hosting provider)
    if command -v vercel &> /dev/null; then
        echo -e "${YELLOW}Deploying to Vercel...${NC}"
        vercel --prod
    elif command -v netlify &> /dev/null; then
        echo -e "${YELLOW}Deploying to Netlify...${NC}"
        netlify deploy --prod --dir=dist
    elif command -v wrangler &> /dev/null; then
        echo -e "${YELLOW}Deploying to Cloudflare Pages...${NC}"
        wrangler pages deploy dist --project-name=syrabit-frontend
    else
        echo -e "${YELLOW}No deployment tool found. Build artifacts in dist/${NC}"
    fi
    
    cd - > /dev/null
    echo -e "${GREEN}✅ Frontend deployment complete${NC}"
    echo ""
}

run_health_checks() {
    echo -e "${BLUE}=== Running Health Checks ===${NC}"
    
    # Check Rust Core health
    RUST_CORE_URL="${RUST_CORE_URL:-http://localhost:3000}"
    echo -e "${YELLOW}Checking Rust Core health...${NC}"
    
    if curl -f -s "$RUST_CORE_URL/health" > /dev/null; then
        echo -e "${GREEN}✅ Rust Core is healthy${NC}"
    else
        echo -e "${RED}❌ Rust Core health check failed${NC}"
    fi
    
    # Check Edge Worker
    EDGE_URL="${EDGE_URL:-https://syrabit.ai}"
    echo -e "${YELLOW}Checking Edge Worker...${NC}"
    
    if curl -f -s "$EDGE_URL" > /dev/null; then
        echo -e "${GREEN}✅ Edge Worker is responding${NC}"
    else
        echo -e "${RED}❌ Edge Worker check failed${NC}"
    fi
    
    echo ""
}

# Main deployment logic
case "$DEPLOY_TARGET" in
    core)
        deploy_rust_core
        ;;
    edge)
        deploy_edge_worker
        ;;
    frontend)
        deploy_frontend
        ;;
    all|*)
        deploy_rust_core
        deploy_edge_worker
        deploy_frontend
        run_health_checks
        ;;
esac

echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
echo ""
echo "Summary:"
echo "  - Rust Core: $RUST_CORE_DIR"
echo "  - Edge Worker: $EDGE_DIR"
echo "  - Frontend: $FRONTEND_DIR"
echo ""
echo "Next steps:"
echo "  1. Verify all services are running"
echo "  2. Check logs for any errors"
echo "  3. Test the JARVIS HUD at /jarvis"
echo "  4. Test staff login at /staff/login"
