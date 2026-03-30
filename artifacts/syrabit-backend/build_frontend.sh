#!/bin/bash
set -e
echo "Building frontend for production..."
cd /home/runner/workspace
pnpm --filter @workspace/syrabit run build
echo "Copying build output to backend/frontend/build..."
rm -rf artifacts/syrabit-backend/frontend/build
mkdir -p artifacts/syrabit-backend/frontend/build
cp -r artifacts/syrabit/dist/* artifacts/syrabit-backend/frontend/build/
echo "Done. Frontend build copied to artifacts/syrabit-backend/frontend/build/"
ls -la artifacts/syrabit-backend/frontend/build/
