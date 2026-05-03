#!/bin/bash
set -e
pnpm install --frozen-lockfile
pnpm --filter db push
pip install -r artifacts/syrabit-backend/requirements.txt -q
