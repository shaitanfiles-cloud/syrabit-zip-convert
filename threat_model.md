# Threat Model

## Project Overview

Syrabit.ai is an educational web application for AssamBoard students. The production stack is a React + Vite frontend in `artifacts/syrabit`, a FastAPI backend in `artifacts/syrabit-backend`, and a Cloudflare Worker edge proxy in `workers/edge-proxy`. The app exposes public study content, authenticated student features, staff content-management workflows, and an admin control plane protected by separate admin auth and Cloudflare Access. Production traffic is assumed to run with `NODE_ENV=production`, TLS is platform-managed, and mockup sandbox code is out of scope unless shown to be production-reachable.

## Assets

- **User accounts and sessions** — student, staff, and admin identities; JWTs; session cookies; refresh tokens. Compromise enables impersonation and access to paid or privileged features.
- **Educational content and publishing pipeline** — chapter content, CMS documents, generated study plans, SEO pages, and public notes. Tampering here can deface public pages, distribute malicious content, or weaponize trusted pages against visitors.
- **Staff and admin capabilities** — content editing, publishing, pipeline controls, analytics, and operational settings. These roles sit above normal users and must be protected from takeover and cross-role abuse.
- **Application secrets and deployment credentials** — JWT secrets, origin shared secret, database credentials, Cloudflare configuration, API keys, and staff/admin passwords. Exposure can collapse trust boundaries quickly.
- **User data and business data** — email addresses, billing/plan state, conversation history, study artifacts, and analytics. These contain privacy-sensitive and operationally sensitive information.

## Trust Boundaries

- **Browser to API/edge boundary** — all frontend input is untrusted. Public, authenticated, staff, and admin routes must each enforce auth and authorization server-side.
- **Public content to browser DOM boundary** — chapter/CMS content originates from editors, staff, AI generation, and databases, then crosses into browser HTML/markdown renderers. This is a high-risk content injection boundary.
- **User to staff/admin boundary** — students, staff, and admins have materially different permissions. Staff content tools and admin control-plane routes must remain isolated.
- **Edge worker to origin boundary** — the worker injects trusted headers and proxies requests to the backend. The backend must not trust client-supplied equivalents.
- **Backend to database boundary** — FastAPI reads and writes user accounts, content, and operational state in backing stores. Broken auth, injection, or overly broad reads here expose most core assets.
- **Backend to third-party services boundary** — auth providers, LLMs, payment services, email, and Cloudflare services receive privileged outbound requests and secrets.

## Scan Anchors

- **Production entry points**: `artifacts/syrabit/src`, `artifacts/syrabit-backend/routes`, `artifacts/syrabit-backend/server.py`, `workers/edge-proxy/src/index.ts`.
- **Highest-risk code areas**: auth/session handling in `routes/auth.py`, `auth_deps.py`, `routes/admin_auth_users.py`; public content publishing in `routes/content.py`, `routes/cms_sarvam_health.py`, `routes/admin_monetization.py`, and frontend renderers/pages that consume HTML/markdown.
- **Surface split**: public study/CMS routes are internet-facing; `/api/auth/*` and student features are authenticated; `/api/staff/*` is staff/admin only; `/api/admin/*` is admin-only with Cloudflare Access layering.
- **Usually dev-only / lower priority**: mockup sandbox code, experimental artifacts outside the main `artifacts/syrabit*` and `workers/edge-proxy` production paths, unless production reachability is demonstrated.

## Threat Categories

### Spoofing

Syrabit.ai relies on user JWTs/cookies for students and a separate admin JWT plus Cloudflare Access for admins. The system must validate session material on every protected request, keep staff/admin credentials out of source-controlled documentation, and ensure privileged routes cannot be reached with downgraded or forged identities. Edge-injected trust headers must never be accepted directly from clients.

### Tampering

The application lets privileged actors edit educational content that is later shown to public users. Because these content flows cross into browser HTML and markdown renderers, the system must treat stored content as untrusted until it has been sanitized for the target sink. Staff and admin editing features must not permit content changes that become active script execution in reader browsers.

### Information Disclosure

The system stores secrets, JWT signing material, login-capable credentials, and user/staff/admin data. Secrets and passwords must not appear in repository files, logs, or client-readable responses. Public endpoints must only expose fields intended for unauthenticated readers, and authenticated routes must scope data to the requesting user or role. Content flagged private or personalized must never be admitted to the public CMS/library path merely because it is marked published for an internal workflow.

### Denial of Service

Public auth and content endpoints are internet-exposed and can be abused for scraping or resource exhaustion. The system must keep rate limiting and origin protections active on production entry points, bound expensive generation/parsing operations, and avoid letting direct-origin access bypass edge-layer abuse controls.

### Elevation of Privilege

Syrabit.ai has meaningful privilege tiers: student, staff, and admin. The system must enforce role checks on the backend, prevent content injection from becoming same-origin script execution, and prevent secret exposure from turning into staff/admin account takeover. Any public content path that can execute attacker-controlled script can become an account-compromise primitive because authenticated users browse the same origin. Credentialed browser trust settings are also part of this boundary: cross-site cookies and CORS allowlists must not trust arbitrary preview-hosting domains or they can hand attacker-controlled origins an authenticated read/write channel into user and admin APIs.