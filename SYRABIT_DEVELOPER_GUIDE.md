# Syrabit.ai — Complete Developer Handoff Document

> **Last Updated:** April 2026
> **Purpose:** Complete blueprint for rebuilding the Syrabit.ai application from scratch. Covers every feature, workflow, design decision, database schema, and integration.

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Tech Stack](#2-tech-stack)
3. [Frontend Architecture](#3-frontend-architecture)
   - 3a. [Design System](#3a-design-system)
   - 3b. [Layout System](#3b-layout-system)
   - 3c. [Component Library](#3c-component-library)
   - 3d. [Routing Structure](#3d-routing-structure)
   - 3e. [State Management](#3e-state-management)
4. [Backend Architecture](#4-backend-architecture)
   - 4a. [Server Setup](#4a-server-setup)
   - 4b. [API Route Structure](#4b-api-route-structure)
   - 4c. [Middleware Stack](#4c-middleware-stack)
   - 4d. [Authentication & Authorization](#4d-authentication--authorization)
5. [Database Schema](#5-database-schema)
   - 5a. [PostgreSQL Tables](#5a-postgresql-tables)
   - 5b. [MongoDB Collections](#5b-mongodb-collections)
   - 5c. [Redis Keys](#5c-redis-keys)
6. [AI Chat System (Syra)](#6-ai-chat-system-syra)
   - 6a. [Chat Flow](#6a-chat-flow)
   - 6b. [Tiered Grounding Strategy](#6b-tiered-grounding-strategy)
   - 6c. [RAG Pipeline](#6c-rag-pipeline)
   - 6d. [Trust Layer & Safety](#6d-trust-layer--safety)
   - 6e. [LLM Infrastructure](#6e-llm-infrastructure)
   - 6f. [Credit System](#6f-credit-system)
7. [Content Pipeline & Admin Panel](#7-content-pipeline--admin-panel)
   - 7a. [Admin Dashboard Sections](#7a-admin-dashboard-sections)
   - 7b. [Content Generation Pipeline](#7b-content-generation-pipeline)
8. [SEO Strategy](#8-seo-strategy)
9. [Payments & Monetization](#9-payments--monetization)
10. [PWA & Mobile Experience](#10-pwa--mobile-experience)
    - 10a. [PWA Configuration](#10a-pwa-configuration)
    - 10b. [Service Worker](#10b-service-worker)
    - 10c. [Mobile UX](#10c-mobile-ux)
11. [Third-Party Integrations Summary](#11-third-party-integrations-summary)
12. [Key Business Rules](#12-key-business-rules)

---

## 1. Product Overview

| Field | Detail |
|---|---|
| **App Name** | Syrabit.ai |
| **Tagline** | "AI-Powered Educational Browser" |
| **Target Audience** | Students under Assam Board (AHSEC, SEBA) and Degree level (B.Com, B.A, B.Sc) |
| **Core Value Proposition** | Instant, syllabus-aligned answers, Previous Year Question (PYQ) insights, structured notes, and AI-powered study guides specific to the Assam education ecosystem |
| **Monetization Model** | Credit-based freemium with paid subscription tiers |
| **Live URL** | `https://syrabit.ai/` |
| **Start URL (PWA)** | `/library` |

The application serves as a comprehensive study companion for Assam Board students. It combines a browsable educational content library with an AI chat assistant ("Syra") that provides syllabus-aligned, contextual answers. The admin panel provides a full CMS, content generation pipeline, SEO management, analytics, and monetization tools.

---

## 2. Tech Stack

### Frontend

| Package | Version / Notes | Purpose |
|---|---|---|
| React | 18+ | UI framework |
| Vite | Build tool | Dev server and production bundler |
| Tailwind CSS | — | Utility-first styling |
| Framer Motion | — | Animations and transitions |
| Radix UI | — | Accessible UI primitives (Accordion, Switch, etc.) |
| Lucide React | — | Icon library |
| react-router-dom | v7 | Client-side routing |
| TanStack React Query | — | Server state management, caching, prefetching |
| Axios | — | API client with interceptors |
| react-markdown + remark-gfm + rehype-raw | — | Markdown content rendering |
| Recharts | — | Admin analytics charts |
| Sonner | — | Toast notifications |
| react-helmet-async | — | SEO meta tags |
| react-ga4 | — | Google Analytics integration |
| next-themes | — | Theme provider (dark/light mode, class strategy) |

### Backend

| Technology | Notes |
|---|---|
| FastAPI | Python 3.10+, fully async |
| Pydantic | Request/response validation models |
| JWT | Dual-secret authentication (user + admin) |
| Google OAuth 2.0 | Social login integration |
| SSE (Server-Sent Events) | Streaming AI responses |

### Databases

| Database | Purpose |
|---|---|
| PostgreSQL | Primary relational — users, conversations, activity logs, notifications, password resets |
| MongoDB Atlas | Content, syllabus, RAG chunks, SEO pages, analytics, config, payments |
| Redis / Upstash | Session caching, rate limiting, AI response caching |
| Supabase | Legacy mirror for users/conversations durability |

### AI/LLM Providers (multi-provider with fallback)

| Provider | Models / Purpose |
|---|---|
| Groq | Llama 3.1/3.3 — primary fast inference |
| Google Gemini / Vertex AI | Embeddings (`text-multilingual-embedding-002`), Vision OCR, content enhancement |
| Sarvam AI | Regional language support, translation, TTS |
| Fireworks AI | DeepSeek, Qwen models |
| Cerebras | Ultra-fast Llama inference |
| Voyage AI | Reranking in RAG pipeline |
| OpenRouter / OpenAI / xAI | Fallback providers |

### Infrastructure

| Service | Purpose |
|---|---|
| Cloudflare Pages | Frontend hosting |
| Cloudflare AI Gateway | LLM request routing, caching, fallback |
| Railway | Backend hosting |

---

## 3. Frontend Architecture

### 3a. Design System

**Theme:** "Futuristic Sci-Fi Glassmorphism"

#### Color Palette

| Token | Light Mode | Dark Mode |
|---|---|---|
| `--background` | `240 20% 96%` (#f0f0f5) | `0 0% 7%` (#121212) |
| `--foreground` | `240 65% 7%` (#0a0a1a) | `0 0% 91%` (#E8E8E8) |
| `--primary` | `263 80% 57%` (#7c3aed) | `258 60% 68%` (#9575e0) |
| `--card` | `0 0% 100%` (white) | `0 0% 10%` (#1a1a1a) |
| `--muted` | `263 55% 97%` | `0 0% 13%` (#212121) |
| `--border` | `263 60% 75%` (violet-tinted) | `0 0% 20%` (#333) |
| `--destructive` | `0 84% 60%` (#ef4444) | `0 72% 65%` |

#### Glow Effect RGBA Values (Dark Mode)

| Token | Value |
|---|---|
| `--glow-primary` | `rgba(149, 117, 224, 0.28)` |
| `--glow-secondary` | `rgba(120, 130, 210, 0.20)` |
| `--glow-accent` | `rgba(180, 120, 240, 0.22)` |
| `--glow-tertiary` | `rgba(80, 120, 220, 0.16)` |

#### Glassmorphism RGBA Values (Dark Mode)

| Token | Value |
|---|---|
| `--card-glass` | `rgba(26, 26, 26, 0.90)` |
| `--card-glass-border` | `rgba(149, 117, 224, 0.12)` |
| `--popover-glass` | `rgba(23, 23, 23, 0.97)` |
| `--input-bg` | `rgba(149, 117, 224, 0.05)` |
| `--sidebar-glass` | `rgba(15, 15, 15, 0.95)` |

#### Typography

| Property | Value |
|---|---|
| Primary Font | `'Space Grotesk'` (geometric, sci-fi feel) |
| Fallback Font | `'Inter'` (legibility) |
| System Fallbacks | `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| Letter Spacing | `0.012em` |
| Border Radius | `0.875rem` (14px) |

#### Glassmorphism Pattern

The `.glass-card` class applies:
```css
background: var(--card-glass);
backdrop-filter: blur(24px) saturate(1.6);
border: 1px solid var(--card-glass-border);
box-shadow: 0 8px 32px rgba(0,0,0,0.18), 0 0 0 1px rgba(255,255,255,0.04) inset;
```

A premium variant (`.glass-card-premium`) uses stronger blur (28px) and saturation (1.8) with a more visible violet border.

#### Mesh Background ("Nebula" Effect)

The `.futuristic-bg::before` pseudo-element creates an animated gradient mesh using five overlapping radial gradients with CSS keyframe animation (`meshFloat`, 45s cycle). Opacity is kept at 0.28 for subtlety.

#### Animation Keyframes

| Keyframe | Duration | Purpose |
|---|---|---|
| `shimmer` | 3s linear infinite | Gradient text sweep on brand elements |
| `pulseGlow` | 8s ease-in-out infinite | Pulsing violet glow on icon containers |
| `orbit` | 20s linear infinite | Spinning border ring (loading splash) |
| `float` | 10s ease-in-out infinite | Gentle vertical float on decorative elements |
| `meshFloat` | 45s ease-in-out infinite | Background gradient orb movement |
| `borderGlow` | 10s ease-in-out infinite | Border color pulse |
| `blink` | — | Blinking cursor for streaming text |
| `typingBounce` | — | Typing dots bounce animation |
| `fadeIn`, `slideUp`, `revealUp`, `slideInLeft`, `slideInRight`, `scaleFadeIn`, `popIn` | — | Entrance animations |
| `focusGlow` | 2s ease-in-out infinite | Input focus ring glow |
| `accordion-down/up` | — | Radix Accordion open/close |

All animations respect `prefers-reduced-motion: reduce` — animations are disabled and durations set to `0.01ms`.

#### Design Token Files

| File | Purpose |
|---|---|
| `src/styles/tokens.css` | CSS custom properties (HSL-based), duplicated light/dark mode tokens |
| `src/index.css` | Full design system — tokens + keyframes + utility classes + component classes |

### 3b. Layout System

**Desktop:** Collapsible sidebar navigation (`<Sidebar />`) + main content area. The sidebar is hidden on mobile.

**Mobile:** Persistent bottom tab bar (`<BottomNav />`) with glassmorphic blur effect (`blur(28px) saturate(1.6)`), shown only below 768px (`md:hidden`). A `<Navbar />` component provides the top header.

**Responsive Breakpoint:** `768px` — a custom `use-mobile` hook detects viewport width.

**Safe Area Support:** Bottom nav uses `paddingBottom: env(safe-area-inset-bottom, 0px)` for notched devices. Chat page uses `pb-[calc(8rem+68px+env(safe-area-inset-bottom,0px))]` to account for the input bar + bottom nav.

**Article/Reading Mode:** `.reading-content` class applies `max-width: 68ch` with auto left/right margins. Global line-height on educational content pages targets ~1.85 for reading comfort.

**AppLayout Structure:**
```
<div className="flex h-screen">
  <Sidebar />                       ← Desktop only
  <div className="flex-1 flex flex-col">
    <Navbar />                       ← Top header
    <main id="main-content">         ← Scrollable content area
      {children}
    </main>
  </div>
  <BottomNav />                      ← Mobile only (md:hidden)
</div>
```

Scroll position resets on route change via `useEffect` on `location.pathname`.

### 3c. Component Library

UI primitives follow a Shadcn-like pattern in `src/components/ui/`:

| Component | Notes |
|---|---|
| `Accordion` | Radix UI based, with CSS keyframe animations |
| `Badge` | — |
| `Button` | Variants include gradient (`btn-gradient`) and glow (`btn-glow`) |
| `Dropdown` | — |
| `Input` | With focus glow animation class (`input-glow`) |
| `Label` | — |
| `Separator` | — |
| `Skeleton` | Loading placeholder |
| `Switch` | Radix UI based |
| `Tooltip` | — |

**Custom Components:**

| Component | Location | Purpose |
|---|---|---|
| `ScrollReveal` | `src/components/ui/` | Intersection Observer entrance animations |
| `GlowOrb` / `FloatingParticles` | Landing page components | Visual flair / decorative background elements |
| `PageMeta` | `src/components/seo/PageMeta` | Centralized SEO management via `react-helmet-async` — sets title, description, OG tags, keywords, canonical URL |
| `ErrorBoundary` | `src/components/ErrorBoundary` | Top-level error boundary |
| `AuthGuard` | `src/components/AuthGuard` | Route protection — redirects unauthenticated users |
| `AdminGuard` | `src/components/AdminGuard` | Admin route protection — verifies admin JWT |

### 3d. Routing Structure

All routing is defined in `src/App.jsx` using `react-router-dom` v7 `<Routes>`. Every page is lazily loaded via `React.lazy()` with code splitting. A `DeferredFallback` component delays showing the loading spinner by 300ms to avoid flash.

#### Public Routes (no auth required)

| Path | Component | Description |
|---|---|---|
| `/` | `LandingPage` | Hero, Features, Pricing sections. Auto-redirects to `/library` if logged in, or `/chat` after 3 seconds if not. |
| `/pricing` | `PricingPage` | Pricing page |
| `/subscribe` | `PricingPage` | Alias for pricing |
| `/terms` | `TermsPage` | Terms of service |
| `/privacy` | `PrivacyPage` | Privacy policy |
| `/exam-routine` | `ExamRoutinePage` | Exam schedule |
| `/payment/success` | `PaymentSuccessPage` | Post-payment success |
| `/payment/cancel` | `PaymentCancelPage` | Post-payment cancel |

#### Authentication Routes

| Path | Component |
|---|---|
| `/login` | `LoginPage` |
| `/signup` | `SignupPage` |
| `/reset-password` | `ResetPasswordPage` |

#### Public Content Routes (no auth, browsable)

| Path | Component | Description |
|---|---|---|
| `/library` | `LibraryPage` | Central "Educational Browser" — subject discovery |
| `/curriculum` | `CurriculumMap` | Curriculum overview |
| `/subject/:subjectId` | `SubjectPage` | Subject-specific content listing |
| `/learn/:slug` | `LearnPage` | Detailed study material pages (CMS content, SEO-optimized) |
| `/pyq/:slug` | `PYQReplicaPage` | PYQ HTML replica pages |

#### Programmatic SEO Routes

| Path | Component | Description |
|---|---|---|
| `/:board/:classSlug/:subjectSlug` | `SubjectLandingPage` | Subject landing |
| `/:board/:classSlug/:subjectSlug/:topicSlug` | `SeoTopicPage` | Topic notes (default) |
| `/:board/:classSlug/:subjectSlug/:topicSlug/:pageType` | `SeoTopicPage` | Specialized content (mcqs, important-questions, examples, syllabus) |

#### Protected User Routes (require auth)

| Path | Component | Guard | Description |
|---|---|---|---|
| `/chat` | `ChatPage` | — (self-guarded via `useAuth`) | AI Chat interface with RAG context |
| `/history` | `HistoryPage` | — | Past conversation logs |
| `/profile` | `ProfilePage` | — | User settings, academic details, subscription management |
| `/onboarding` | `OnboardingPage` | Self-guarded | Initial board/class/stream selection |
| `/cms/:userId/:slug` | `PersonalizedCmsPage` | `<AuthGuard>` | Personalized CMS content (paid) |

#### Admin Routes

| Path | Component | Guard |
|---|---|---|
| `/admin/login` | `AdminLoginPage` | None |
| `/admin` | `AdminPage` | `<AdminGuard>` |

#### 404

| Path | Component |
|---|---|
| `*` | `NotFoundPage` |

### 3e. State Management

**Server State:** React Query (TanStack) with global `QueryClient` configuration:
- `staleTime`: 5 minutes
- `gcTime`: 1 hour
- `retry`: 2 attempts
- `refetchOnWindowFocus`: false

A library bundle is prefetched on app mount (authenticated users) or on hover/touch of library link (unauthenticated), falling back to auto-prefetch after 1 second.

**Auth State:** React Context API (`AuthContext`) providing `user` object and auth methods. JWT tokens stored in `localStorage` under `'token'` key. Admin tokens stored under `'admin_token'`.

**API Client:** Axios instance (`apiClient()`) with:
- Base URL from `API_BASE` constant
- Auth token interceptor (reads from `localStorage`)
- `withCredentials: true` for cookie-based admin auth
- Centralized error handling

**Theme State:** `next-themes` `ThemeProvider` with `attribute="class"`, default theme `"dark"`, system theme detection disabled.

**App Provider Hierarchy:**
```
<HelmetProvider>
  <ErrorBoundary>
    <ThemeProvider>
      <QueryClientProvider>
        <AuthProvider>
          <BrowserRouter>
            <PageTracker />      ← GA4 page tracking
            <Toaster />          ← Sonner toast notifications
            <Suspense>
              <Routes />
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </ErrorBoundary>
</HelmetProvider>
```

---

## 4. Backend Architecture

### 4a. Server Setup

- FastAPI application with `async`/`await` patterns throughout all handlers
- `asynccontextmanager` lifespan function initializes and tears down:
  - PostgreSQL connection pool
  - MongoDB client
  - Redis connection
- Strict environment validation at startup — fails fast if `MONGO_URL`, `JWT_SECRET`, `ADMIN_JWT_SECRET`, or `ADMIN_PASSWORDS` are missing. Warns if recommended keys (`GROQ_API_KEY`, `SARVAM_API_KEY`) are not set.
- LLM provider diagnostics run on boot — logs SET/NOT SET status for all provider keys: `GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `XAI_API_KEY`, `OPENAI_API_KEY`, `FIREWORKS_API_KEY`, `SARVAM_API_KEY`, `CEREBRAS_API_KEY`, `EMERGENT_API_KEY`, `OPENROUTER_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- JSON-structured logging via custom `_JSONFormatter` (timestamp, level, logger, message, exception, request_id)
- Worker leader election via file lock (`/tmp/.syrabit_startup.lock`) — only the first worker runs migrations, index creation, and seeding
- Background startup tasks: Supabase→PG user migration, credit limit healing, GA4 refresh token loading from DB, syllabus embedding seeding
- Most routes mounted under `/api` prefix (exception: PYQ slug routes)

### 4b. API Route Structure

Most endpoints are mounted under the `/api` prefix via an `APIRouter`. Exception: `routes/pyq.py` mounts some routes directly on the app (e.g., `/pyq/{slug}` for public PYQ pages).

| Route File | Key Endpoints | Description |
|---|---|---|
| `routes/auth.py` | `/auth/signup`, `/auth/login`, `/auth/google`, `/auth/reset-password` | User registration, login (email + Google OAuth), password reset |
| `routes/ai_chat.py` | `/ai/chat/stream` | SSE streaming chat with RAG context, credit deduction |
| `routes/content.py` | `/content/library-bundle`, `/content/boards`, `/content/classes`, `/content/streams`, `/content/subjects`, `/content/chapters` | Library content hierarchy CRUD, bulk library bundle endpoint |
| `routes/syllabus.py` | `/syllabus/...` | Curriculum mapping and syllabus data |
| `routes/conversations.py` | `/conversations`, `/conversations/{conv_id}` | User conversation CRUD (list, get, update, delete) |
| `routes/user.py` | `/user/onboarding`, `/user/profile`, `/user/avatar`, `/user/saved-subjects`, `/user/credits`, `/user/stats` | User profile, onboarding, saved subjects, credit balance |
| `routes/admin_auth_users.py` | `/admin/login`, `/admin/logout`, `/admin/verify`, `/admin/dashboard`, `/admin/users`, `/auth/refresh`, `/auth/logout` | Admin authentication, session management, user management, dashboard overview |
| `routes/analytics.py` | `/admin/analytics`, `/admin/analytics/live`, `/analytics/page-view`, `/analytics/session-ping`, `/analytics/session-end`, `/analytics/track` | Admin analytics data, client-side page view / session / event tracking |
| `routes/admin_content.py` | `/admin/content/...` | Admin CMS operations — CRUD for boards, classes, streams, subjects, chapters |
| `routes/admin_pipeline.py` | `/admin/pipeline/...` | Content generation pipeline — auto-generate notes, MCQs, blogs |
| `routes/admin_settings.py` | `/admin/settings/...` | System configuration management — site settings, API config, rate limits, health |
| `routes/admin_notifications.py` | `/admin/notifications`, `/push/vapid-public-key`, `/push/subscribe`, `/admin/exam-schedule` | Push notification management, VAPID key endpoint, exam schedule CRUD |
| `routes/admin_monetization.py` | `/admin/monetization/...` | Payment and subscription management — Razorpay/Stripe integration |
| `routes/admin_advanced.py` | `/admin/monetization/overview`, `/admin/monetization/referrals`, `/admin/seo/internal-links/...`, `/admin/conversations/extract-faqs` | Advanced admin features: referral system, SEO internal link analysis/injection, FAQ extraction from conversations |
| `routes/cms_sarvam_health.py` | `/admin/content/cms-documents`, `/admin/content/cms-documents/{doc_id}` | CMS document management (list, create, update, publish), includes `CmsNoIndexMiddleware` and `BotRenderMiddleware` |
| `seo_engine.py` (top-level) | `/seo/...` | Dynamic SEO page generation, sitemap, JSON-LD schema injection |
| `qa_engine.py` (top-level) | Public + admin Q&A routes | Vector-based Q&A with public and admin routers |
| `routes/pyq.py` | `/api/admin/pyq/upload`, `/api/admin/pyq/agentic-process`, `/api/admin/pyq/html-replica`, `/api/pyq/list`, `/pyq/{slug}` | PYQ upload, agentic processing (OCR → AI extraction), HTML replica generation, public PYQ listing (mounted outside `/api` prefix for slug routes) |

**Key Endpoints (selected highlights):**

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/signup` | User registration |
| `POST` | `/api/auth/login` | Email/password login |
| `POST` | `/api/auth/google` | Google OAuth login |
| `POST` | `/api/auth/reset-password` | Request password reset |
| `POST` | `/api/auth/refresh` | Refresh JWT token |
| `POST` | `/api/auth/logout` | User logout |
| `POST` | `/api/ai/chat/stream` | SSE streaming chat with RAG |
| `GET` | `/api/content/library-bundle` | Full library hierarchy bundle (boards, classes, streams, subjects) |
| `GET` | `/api/content/subjects` | List all subjects |
| `GET` | `/api/content/chapters?subject_id=X` | Chapters for a subject |
| `GET` | `/api/conversations` | List user conversations |
| `GET` | `/api/conversations/{conv_id}` | Get single conversation |
| `DELETE` | `/api/conversations/{conv_id}` | Delete conversation |
| `PATCH` | `/api/conversations/{conv_id}` | Update conversation (star, archive, rename) |
| `POST` | `/api/user/onboarding` | Set user's board/class/stream |
| `GET` | `/api/user/profile` | Get user profile |
| `PATCH` | `/api/user/profile` | Update user profile |
| `POST` | `/api/user/avatar` | Upload avatar image |
| `GET` | `/api/user/saved-subjects` | List saved/bookmarked subjects |
| `POST` | `/api/user/saved-subjects/{subject_id}` | Toggle subject bookmark |
| `GET` | `/api/user/credits` | Current user credit balance |
| `GET` | `/api/user/stats` | User usage statistics |
| `GET` | `/api/health` | System health check (DB connectivity, LLM availability) |
| `POST` | `/api/admin/login` | Admin login |
| `GET` | `/api/admin/verify` | Verify admin session |
| `POST` | `/api/admin/logout` | Admin logout (clears httpOnly cookie) |
| `GET` | `/api/admin/dashboard` | Admin dashboard overview data |
| `GET` | `/api/admin/users` | List all users (admin) |
| `PATCH` | `/api/admin/users/{user_id}/status` | Update user status (admin) |
| `GET` | `/api/admin/settings` | Get site settings |
| `PUT` | `/api/admin/settings` | Update site settings |
| `GET` | `/api/admin/analytics` | Analytics overview data |
| `GET` | `/api/admin/analytics/live` | Real-time visitor count |
| `POST` | `/api/analytics/page-view` | Track page view (client-side) |
| `POST` | `/api/analytics/session-ping` | Session keep-alive ping (client-side) |
| `POST` | `/api/analytics/track` | Generic event tracking (client-side) |
| `GET` | `/api/admin/notifications` | List notifications |
| `POST` | `/api/admin/notifications` | Create/send notification |
| `GET` | `/api/push/vapid-public-key` | Get VAPID public key for push subscriptions |
| `POST` | `/api/push/subscribe` | Subscribe to push notifications |
| `GET` | `/api/admin/exam-schedule` | Get exam schedule |
| `POST` | `/api/admin/exam-schedule` | Update exam schedule |
| `GET` | `/api/admin/monetization/overview` | Revenue overview |
| `GET` | `/api/admin/monetization/referrals` | Referral program data |
| `GET` | `/api/admin/seo/internal-links/analyze` | Analyze internal links |
| `POST` | `/api/admin/seo/internal-links/inject/{slug}` | Inject internal links into a page |
| `GET` | `/api/admin/conversations/extract-faqs` | Extract FAQs from user conversations |
| `GET` | `/api/admin/content/cms-documents` | List CMS documents |
| `POST` | `/api/admin/content/cms-documents` | Create CMS document |
| `PATCH` | `/api/admin/content/cms-documents/{doc_id}` | Update CMS document |
| `POST` | `/api/admin/content/cms-documents/{doc_id}/publish` | Publish CMS document |
| `POST` | `/api/admin/pyq/upload` | Upload PYQ PDF |
| `POST` | `/api/admin/pyq/agentic-process` | Run agentic PYQ processing (OCR → AI) |
| `POST` | `/api/admin/pyq/html-replica` | Generate PYQ HTML replica |
| `GET` | `/api/pyq/list` | List public PYQ pages |
| `GET` | `/pyq/{slug}` | Serve PYQ HTML replica page (outside `/api` prefix) |

### 4c. Middleware Stack

Applied in this order:

1. **GlobalRateLimitMiddleware** — Plan-aware rate limiting:
   - Tracks requests per IP and per authenticated user
   - Uses Redis sliding window counters
   - Free users have stricter limits than paid users
   - Returns `429 Too Many Requests` when limits exceeded

2. **SecurityHeadersMiddleware** — Sets security headers on all responses:
   - `Content-Security-Policy` (CSP)
   - `Strict-Transport-Security` (HSTS)
   - `X-Frame-Options: DENY`
   - `X-Content-Type-Options: nosniff`

3. **GZip Middleware** — Compresses responses larger than 500 bytes

4. **CORS Middleware** — Configurable allowed origins:
   - Production: `syrabit.ai`, Cloudflare Pages domains
   - Development: Replit dev domains
   - Credentials: `allow_credentials=True`

### 4d. Authentication & Authorization

**JWT Dual-Secret System:**
- `JWT_SECRET` — Used to sign and verify student JWT tokens
- `ADMIN_JWT_SECRET` — Separate secret for admin JWT tokens
- This ensures admin tokens cannot be forged even if the user secret is compromised

**Google OAuth Flow:**
- Uses `google-auth` library to verify Google ID tokens
- Creates or links user account on first Google login
- Sets `auth_provider` to `'google'` and stores `google_id`

**Role-Based Access Control:**
- Two roles: `student` (default) and `admin`
- `is_admin` boolean flag on the `users` table
- FastAPI dependency guards:
  - `get_current_user` — Extracts and validates user JWT from `Authorization` header
  - `get_admin_user` — Validates admin JWT from httpOnly cookie or `Authorization` header

**Session Management:**
- Admin sessions use httpOnly cookies (set by `/api/admin/verify`)
- Admin token also stored in `localStorage` as fallback
- Session keep-alive: Admin page pings `/admin/verify` every 20 minutes to slide the session
- Redis session caching with 30-minute TTL for fast user lookups

---

## 5. Database Schema

### 5a. PostgreSQL Tables

#### `users`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, default gen | Primary key |
| `name` | VARCHAR | NOT NULL | Display name |
| `email` | VARCHAR | UNIQUE, NOT NULL | Login email |
| `password_hash` | VARCHAR | NULLABLE | Bcrypt hash (null for Google OAuth users) |
| `plan` | VARCHAR | DEFAULT 'free' | Subscription tier: `free`, `starter`, `pro` |
| `credits_used` | INT | DEFAULT 0 | Total credits consumed (current period) |
| `credits_limit` | INT | NULLABLE | Max credits for current plan |
| `credits_used_today` | INT | DEFAULT 0 | Daily credit counter (for free tier reset) |
| `credits_reset_date` | TIMESTAMP | NULLABLE | When daily credits last reset |
| `is_admin` | BOOLEAN | DEFAULT false | Admin role flag |
| `onboarding_done` | BOOLEAN | DEFAULT false | Whether user completed board/class selection |
| `board_id` | VARCHAR | NULLABLE | References MongoDB `boards` collection |
| `class_id` | VARCHAR | NULLABLE | References MongoDB `classes` collection |
| `stream_id` | VARCHAR | NULLABLE | References MongoDB `streams` collection |
| `board_name` | VARCHAR | NULLABLE | Denormalized board name |
| `class_name` | VARCHAR | NULLABLE | Denormalized class name |
| `stream_name` | VARCHAR | NULLABLE | Denormalized stream name |
| `google_id` | VARCHAR | NULLABLE | Google account ID for OAuth users |
| `auth_provider` | VARCHAR | DEFAULT 'email' | `'email'` or `'google'` |
| `status` | VARCHAR | DEFAULT 'active' | Account status (`active`, `suspended`) |
| `bio` | TEXT | DEFAULT '' | User bio |
| `phone` | VARCHAR | DEFAULT '' | Phone number |
| `avatar_url` | VARCHAR | DEFAULT '' | Profile avatar URL |
| `saved_subjects` | JSONB | DEFAULT '[]' | Array of saved subject IDs |
| `document_access` | VARCHAR | DEFAULT 'zero' | Document access level |
| `has_free_credits_issued` | BOOLEAN | DEFAULT true | Whether initial free credits have been issued |
| `created_at` | TIMESTAMP | DEFAULT NOW | Account creation timestamp |

#### `conversations`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | SERIAL / UUID | PK | Primary key |
| `user_id` | UUID | FK → users.id | Owner |
| `title` | VARCHAR | NULLABLE | Auto-generated from first message |
| `preview` | VARCHAR | NULLABLE | Truncated first message for listings |
| `subject_id` | VARCHAR | NULLABLE | MongoDB subject context |
| `subject_name` | VARCHAR | NULLABLE | Denormalized subject name |
| `starred` | BOOLEAN | DEFAULT false | User bookmarked |
| `archived` | BOOLEAN | DEFAULT false | Soft archive |
| `messages` | JSONB | NOT NULL | Array of `{id, role, content, timestamp, rag_source?, rag_chunks?, sources?}` |
| `tokens` | INT | DEFAULT 0 | Token count for the conversation |
| `created_at` | TIMESTAMP | DEFAULT NOW | — |
| `updated_at` | TIMESTAMP | DEFAULT NOW | Auto-updated on message append |

#### `notifications`

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | PK |
| `title` | VARCHAR | Notification title |
| `message` | TEXT | Notification body |
| `type` | VARCHAR | e.g., `'info'`, `'alert'`, `'update'` |
| `channel` | VARCHAR | e.g., `'push'`, `'email'`, `'in-app'` |
| `audience` | VARCHAR | e.g., `'all'`, `'free'`, `'pro'` |
| `status` | VARCHAR | `'draft'`, `'sent'`, `'failed'` |
| `created_at` | TIMESTAMP | — |
| `sent_at` | TIMESTAMP | — |

#### `password_resets`

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | PK |
| `user_id` | UUID | FK → users.id |
| `token` | VARCHAR | Unique reset token |
| `expires_at` | TIMESTAMP | Token expiry |
| `used` | BOOLEAN | Whether token was consumed |

#### `activity_logs`

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | PK |
| `user_id` | UUID | FK → users.id (nullable for system actions) |
| `action` | VARCHAR | Action identifier (e.g., `'login'`, `'chat'`, `'upgrade'`) |
| `metadata` | JSONB | Additional context (IP, user agent, details) |
| `timestamp` | TIMESTAMP | DEFAULT NOW |

### 5b. MongoDB Collections

#### Content Hierarchy

**`boards`**
```json
{
  "_id": "ObjectId",
  "name": "AHSEC",
  "slug": "ahsec",
  "description": "Assam Higher Secondary Education Council",
  "created_at": "ISODate"
}
```

**`classes`**
```json
{
  "_id": "ObjectId",
  "board_id": "ref → boards._id",
  "name": "Class 12",
  "slug": "class-12",
  "description": "Higher Secondary 2nd Year"
}
```

**`streams`**
```json
{
  "_id": "ObjectId",
  "class_id": "ref → classes._id",
  "name": "Commerce",
  "slug": "commerce",
  "description": "Commerce stream",
  "icon": "emoji or URL"
}
```

**`subjects`**
```json
{
  "_id": "ObjectId",
  "stream_id": "ref → streams._id",
  "name": "Accountancy",
  "slug": "accountancy",
  "description": "...",
  "tags": ["journal entries", "ledger", "trial balance"],
  "thumbnailUrl": "URL",
  "status": "published",
  "chapter_count": 12,
  "paper_type": "theory",
  "has_document": true,
  "document_text": "extracted PDF text"
}
```

#### Educational Content

**`chapters`**
```json
{
  "_id": "ObjectId",
  "subject_id": "ref → subjects._id",
  "title": "Partnership Accounts",
  "slug": "partnership-accounts",
  "content": "# Partnership Accounts\n\nMarkdown content...",
  "topics": ["profit sharing", "admission of partner"],
  "order_index": 3,
  "notes_generated": true,
  "has_important_questions": true,
  "has_flashcards": true,
  "chapter_number": 3,
  "description": "Brief description"
}
```

**`syllabi`**
```json
{
  "_id": "ObjectId",
  "board_id": "ref",
  "class_id": "ref",
  "stream_id": "ref",
  "subject_id": "ref",
  "content": "Full syllabus text",
  "chapters": ["Chapter names"],
  "topics": ["Topic list"],
  "guidelines": "Exam guidelines"
}
```

**`flashcard_collections`**
```json
{
  "_id": "ObjectId",
  "subject_id": "ref",
  "chapter_id": "ref",
  "flashcards": [
    { "front": "What is a journal?", "back": "A book of original entry...", "type": "definition", "mnemonic": "J-O-U-R-N-A-L" }
  ],
  "total": 25,
  "pipeline_generated": true
}
```

**`ai_pyq_collections`**
```json
{
  "_id": "ObjectId",
  "chapter_id": "ref",
  "pyqs": [
    { "question": "...", "year": 2024, "marks": 5, "answer": "..." }
  ],
  "mark_wise": {
    "1": [{ "question": "...", "year": 2023 }],
    "2": [...],
    "5": [...],
    "10": [...]
  }
}
```

#### SEO & Discovery

**`topics`**
```json
{
  "_id": "ObjectId",
  "chapter_id": "ref",
  "title": "Partnership Deed",
  "slug": "partnership-deed",
  "status": "published",
  "order": 1
}
```

**`seo_pages`**
```json
{
  "_id": "ObjectId",
  "topic_id": "ref",
  "page_type": "notes|mcqs|important-questions|examples|syllabus",
  "slug": "partnership-deed-notes",
  "content_html": "<article>...</article>",
  "status": "published|draft",
  "meta_description": "...",
  "board_slug": "ahsec",
  "class_slug": "class-12",
  "subject_slug": "accountancy",
  "topic_slug": "partnership-deed"
}
```

**`cms_documents`**
```json
{
  "_id": "ObjectId",
  "type": "syllabus|post|blog|guide",
  "title": "Document Title",
  "seo_slug": "url-slug",
  "content": "Markdown source",
  "content_html": "Rendered HTML",
  "meta_description": "SEO description",
  "geo_tags": ["Assam", "Guwahati"],
  "schema_type": "Article|FAQPage|HowTo"
}
```

**Analytics & Tracking:**
- `analytics` — Event-level analytics: `event_type`, `timestamp`, `subject_id`, `user_id`
- `page_views` — Per-page view tracking: `date`, `visitor_id`, `session_id`, `timestamp`, `is_bot`
- `sessions` — Visitor session tracking: `session_id` (unique), `visitor_id`, `last_ping`, `start_time`
- `roadmap` — Product roadmap items: `id`, `title`, `description`, `phase`, `status`, `effort`, `impact`, `priority`, `category`
- `topic_pyq_collections` — Topic-level PYQ data: `chapter_id`, `subject_id`

#### System & Operations

**`api_config`** — Single document storing all API keys and config:
```json
{
  "groq": { "api_keys": ["..."], "default_model": "llama-3.3-70b-versatile" },
  "payment": {
    "razorpay_key_id": "...", "razorpay_key_secret": "...",
    "stripe_key": "...", "stripe_secret": "..."
  },
  "email": { "resend_api_key": "...", "from_email": "..." },
  "push_vapid": { "public_key": "...", "private_key": "...", "email": "..." },
  "google_auth": { "client_id": "...", "client_secret": "..." }
}
```

**`plan_config`** — Pricing and credit limits:
```json
{
  "free":    { "credits_limit": 30, "daily_reset": true,  "price_inr": 0,    "price_usd": 0 },
  "starter": { "credits_limit": 300, "daily_reset": false, "price_inr": 9900, "price_usd": 199 },
  "pro":     { "credits_limit": 4000, "daily_reset": false, "price_inr": 99900, "price_usd": 1299 }
}
```
Note: `price_inr` is in paise (₹99 = 9900 paise), `price_usd` is in cents ($1.99 = 199 cents).

**`payments`**
```json
{
  "_id": "ObjectId",
  "user_id": "UUID string",
  "plan": "starter|pro",
  "provider": "razorpay|stripe",
  "status": "created|paid|failed",
  "amount_paise": 9900,
  "razorpay_payment_id": "...",
  "stripe_session_id": "...",
  "created_at": "ISODate"
}
```

**`push_subscriptions`**
```json
{
  "_id": "ObjectId",
  "user_id": "UUID string",
  "endpoint": "https://fcm.googleapis.com/...",
  "subscription_info": { "keys": { "p256dh": "...", "auth": "..." } }
}
```

**`exam_schedule`**
```json
{
  "_id": "ObjectId",
  "board": "AHSEC",
  "class_name": "Class 12",
  "subject": "Accountancy",
  "exam_date": "ISODate",
  "active": true,
  "notified_for": ["2026"]
}
```

### 5c. Redis Keys

| Key Pattern | TTL | Purpose |
|---|---|---|
| `session:{user_id}` | 30 min | Cached user session data |
| `ratelimit:{ip}:{window}` | Sliding window | IP-based rate limit counter |
| `ratelimit:user:{user_id}:{window}` | Sliding window | User-based rate limit counter |
| `ai_cache:{query_hash}` | Configurable | Cached AI response for identical queries |

---

## 6. AI Chat System (Syra)

### 6a. Chat Flow

The complete flow for a user message:

1. **User sends message** via `POST /api/ai/chat/stream` (SSE endpoint). The frontend opens a fetch stream with `credentials: 'include'`.

2. **Phase 0 (Auth)** and **Phase 1 (RAG/Syllabus resolution)** run in parallel:
   - Phase 0: Validates JWT, checks credit balance, rejects with `402` if exhausted
   - Phase 1: Resolves user's board/class/stream context, finds relevant syllabus and content

3. **Query Classification:** The query is classified into one of 15+ intents:
   - `syllabus`, `pyq`, `notes`, `important_topics`, `flashcards`, `definition`, `example`, `comparison`, `formula`, `diagram`, `summary`, `question_answer`, `essay`, `general_academic`, etc.

4. **Context Gathering:** Uses the Tiered Grounding Strategy (see 6b) to assemble relevant context

5. **System Prompt Construction:** Dynamic system prompt built (up to 100k characters) incorporating:
   - User's academic profile (board, class, stream)
   - Resolved syllabus context
   - RAG-retrieved content chunks
   - Intent-specific instructions

6. **Response Streaming:** Response is streamed via SSE with these event types:
   - `{ content: "token" }` — Streaming text tokens
   - `{ conversation_id: "id" }` — New/existing conversation ID
   - `{ rag_source: "library|web|none" }` — Source attribution
   - `{ rag_chunks: N }` — Number of RAG chunks used
   - `{ rag_subject_name, rag_chapter_name, ctx_board_name, ctx_class_name, ctx_stream_name }` — Context metadata
   - `{ error: "message" }` — Error event
   - `{ event: "syrabit_done", credits_used_total, remaining_credits, sources }` — Completion event
   - `data: [DONE]` — Stream termination

7. **Credit Deduction:** 1 credit deducted atomically per successful response. Credits are refunded on failed streams.

**Frontend Streaming Implementation:**
- Uses `ReadableStream` with `reader.read()` loop
- RAF-based batching: Accumulates tokens between animation frames so React re-renders at most 60x/sec
- Messages stored as `{id, role, content, streaming, timestamp, rag_source, rag_chunks, sources, ...}` in component state

### 6b. Tiered Grounding Strategy

Context is gathered from multiple tiers, each progressively broader:

| Tier | Name | Source | Description |
|---|---|---|---|
| **Tier 0** | Immediate | Page context / upload | Current library page content the user is viewing, or uploaded document/PDF (`document_id` param). Also includes `card_context` — the subject card with chapter syllabus visible on the chat page. |
| **Tier 1** | Syllabus | MongoDB `syllabi` | Resolves user's `board_id` / `class_id` / `stream_id` → injects official curriculum structure, chapter list, and exam guidelines |
| **Tier 2** | Internal Library | MongoDB `seo_pages`, `chapters`, `cms_documents` | Vector similarity search + full-text search against internal content. Merges and deduplicates results. |
| **Tier 3** | Web Search | DuckDuckGo / Tavily | Safe web search with scoped query if internal data is insufficient. Only triggered when Tier 0-2 don't provide adequate coverage. |

### 6c. RAG Pipeline

| Component | Implementation |
|---|---|
| **Embedding Model** | Google Vertex AI `text-multilingual-embedding-002` |
| **Chunk Size** | ~600 characters |
| **Chunking Strategy** | Split by headings and sentence boundaries with 2-sentence overlap between chunks |
| **Storage** | MongoDB Atlas Vector Search on `seo_pages` and `chunks` collections |
| **Retrieval** | Vector similarity search (cosine distance) against embedded content |
| **Deduplication** | Merges results from vector hits + full-text MongoDB search, removes duplicate content |
| **Reranking** | Voyage AI reranker applied to candidate results for improved relevance |

### 6d. Trust Layer & Safety

1. **Academic Scope Guard:** The AI only answers questions related to Assam Board curriculum. Non-academic queries (politics, entertainment, personal advice, etc.) are politely declined with a redirect to academic topics.

2. **Source Attribution:** Handled by the system (not the LLM) to prevent hallucinations. The `rag_source` field in SSE events tells the frontend where the context came from (library, web, or none).

3. **Intent Validation:** Post-generation check — if the AI response contains phrases indicating it doesn't know the answer, the system triggers graceful degradation (tries next tier or provides a helpful fallback message).

4. **No External Link Injection:** The AI does not include external links in responses — all source references point to internal Syrabit.ai content pages.

### 6e. LLM Infrastructure

**Smart Key Pool:** Load-balances API requests across all configured provider keys. Distributes calls to avoid per-key rate limits.

**Speed Tier Ordering (fastest first):**
1. Cerebras — Ultra-fast Llama inference
2. Groq — Fast Llama 3.1/3.3 inference
3. Fireworks AI — DeepSeek, Qwen models
4. Sarvam AI — Regional language models
5. Google Gemini — Vertex AI
6. OpenRouter — Fallback aggregator

**Cloudflare AI Gateway:**
- Routes LLM requests through Cloudflare for caching, analytics, and automatic fallback
- Caches identical requests to reduce latency and cost
- Provides request logging and token usage analytics

**Fallback Behavior:**
- If the primary provider fails mid-stream, the system automatically retries with the next provider in the speed-priority order
- The user does not see the failover — streaming continues seamlessly
- Identical queries within a 15ms window are batched/deduped to prevent duplicate API calls

**Model Selection:**
The frontend provides a `ModelSelector` component allowing users to choose models. The default model is `openai/gpt-oss-20b`. The selected model is sent as part of the chat request payload.

### 6f. Credit System

| Plan | Credits | Reset | Price |
|---|---|---|---|
| Free | 30 / day | Daily reset | ₹0 / $0 |
| Starter | 300 / month | Monthly | ₹99 / $1.99 |
| Pro | 4000 / month | Monthly | ₹999 / $12.99 |

**Implementation Details:**
- 1 credit = 1 AI response (regardless of response length)
- Atomic credit deduction in PostgreSQL using `UPDATE ... SET credits_used = credits_used + 1` to prevent race conditions
- Credits refunded on failed streams (error in LLM response)
- Frontend displays a credit progress bar with color coding:
  - Normal: Violet
  - Low (≤5 remaining): Amber warning
  - Exhausted (0 remaining): Red alert banner with "Upgrade" CTA
- `402 Payment Required` returned when credits exhausted
- Frontend shows toast with upgrade action button on 402

---

## 7. Content Pipeline & Admin Panel

### 7a. Admin Dashboard Sections

The admin panel (`/admin`) uses a sidebar navigation with 6 groups and 20 sections:

| Group | Section ID | Label | Component | Description |
|---|---|---|---|---|
| **MAIN** | `dashboard` | Dashboard | `AdminDashboard` | Overview metrics, quick actions |
| | `roadmap` | Roadmap | `AdminRoadmap` | Product roadmap and feature tracking |
| **CONTENT** | `contenthub` | Content Editor | `AdminContentHub` | 3-tab content workflow (Editor → CMS → Blog) |
| | `seomanager` | SEO Manager | `AdminSeoManager` | 10-tab SEO management suite |
| | `vertex` | Vertex AI Studio | `AdminVertexPanel` | 10 AI-powered tools |
| | `automation` | Automation | `AdminAutomation` | Automated content workflows |
| **AUDIENCE** | `users` | Users | `AdminUsers` | User management |
| | `conversations` | Conversations | `AdminConversations` | View all user chat conversations |
| **INSIGHTS** | `analytics` | Analytics | `AdminAnalytics` | 8-tab analytics dashboard |
| | `monetization` | Monetization | `AdminMonetization` | Revenue and payment management |
| | `plans` | Plans & Credits | `AdminPlans` | Plan configuration and credit management |
| | `intelligence` | Intelligence | `AdminIntelligence` | Data intelligence and insights |
| **COMMS** | `notifications` | Notifications | `AdminNotifications` | Push notification management |
| **SYSTEM** | `apiconfig` | API Config | `AdminApiConfig` | API keys and provider configuration |
| | `googleauth` | Google Auth | `AdminGoogleAuth` | Google OAuth setup |
| | `settings` | Site Settings | `AdminSettings` | App name, tagline, maintenance mode, registration toggle |
| | `ratelimits` | Rate Limits | `AdminRateLimits` | Rate limiting configuration |
| | `activitylog` | Activity Log | `AdminActivityLog` | System activity audit trail |
| | `health` | Health / Uptime | `AdminHealth` | System health monitoring |

**Admin Authentication Flow:**
1. Admin navigates to `/admin` → `AdminGuard` checks for valid admin session
2. On mount, calls `adminVerify(storedToken)` to validate the admin JWT
3. If valid: renders admin panel, stores `adminName`, `adminEmail`, and refreshed `access_token`
4. If invalid: redirects to `/admin/login`
5. Session keep-alive pings `/admin/verify` every 20 minutes
6. System status badge dynamically shows "All Systems Operational" / "Setup Required" / "Maintenance Mode"

**AdminContentHub Workflow:**

The Content Hub provides a 3-tab content creation workflow with shared context:

1. **Content Editor** (`AdminContentEditor`) — Write and edit chapter-level markdown content with a hierarchy tree (Board → Class → Stream → Subject → Chapter)
2. **CMS / Docs** (`AdminCmsDocEditor`) — Manage published pages, SEO documents, and blog posts
3. **Blog Publisher** (`BlogPublishWizard`) — 5-step SEO & GEO-rich blog publish wizard

Cross-tab context sharing uses `hubContext` (persisted in localStorage for 2 hours):
```json
{
  "boardId": "", "boardName": "",
  "classId": "", "className": "",
  "streamId": "", "streamName": "",
  "subjectId": "", "subjectName": ""
}
```

**Auto-Generate Full Subject Pipeline:**
When a subject is selected in Content Hub, two pipeline buttons appear:
- **Auto-Generate Full Subject** — Generates all content (notes, MCQs, blogs) from scratch
- **SEO Polish** — Reuses existing notes, only re-publishes blogs and PYQ pages

Both trigger `PipelineProgressPanel` which shows real-time progress.

**AdminSeoManager Tabs:**

| Tab | Purpose |
|---|---|
| Pipeline | Subject-level content coverage overview and batch generation |
| Review | Quality review queue for generated content |
| SEO Pages | Browse/filter all published and draft SEO pages |
| Topics | Manage topic entities, extract new topics from content |
| Insights | AI-powered content improvement suggestions |
| Generate | Generate content for selected topics × page types |
| Pilot | Preview SEO pages before publishing |
| Int. Links | Internal link analysis and injection tool |
| Schema | JSON-LD structured data management per page |
| Sitemap | Sitemap generation, validation, and meta refresh |

**AdminAnalytics Tabs:**

| Tab | Purpose |
|---|---|
| Overview | Real-time visitors, total users, total conversations |
| Daily Stats | Time-series charts (Recharts) for daily metrics |
| Funnel | User conversion funnel (signup → onboard → chat → paid) |
| Heatmap | Content engagement heatmap |
| SEO Pages | SEO page performance metrics |
| Revenue | MRR, ARPU, LTV calculations |
| Predictions | Predictive analytics (growth projections) |
| Conversions | Page-level conversion tracking |

Integrates with GA4 (Google Analytics 4) — can connect via OAuth, test connection, and pull real-time data.

**AdminVertexPanel (Vertex AI Studio) Tools:**

| Tool | Purpose |
|---|---|
| Semantic Search | Vector similarity search across all content |
| Translation | Translate content between languages (via Sarvam AI) |
| Quality Scorer | AI-powered content quality scoring |
| Topic Suggester | Suggest new topics based on syllabus gaps |
| SEO Meta Generator | Generate meta descriptions and titles |
| Content Gaps | Identify missing content in the library |
| Vision OCR | Extract text from images (Google Cloud Vision) |
| NLP Concepts | Entity and keyword extraction (Cloud Natural Language) |
| Flashcard Generator | Generate flashcards from chapter content |
| MCQ Generator | Generate multiple-choice questions from content |

### 7b. Content Generation Pipeline

The automated content pipeline generates complete subject content with these steps:

1. **Chapter Notes Generation** — Auto-generates 400-700 word notes per chapter using LLM
2. **Mark-Wise Question Generation** — Creates questions categorized by marks (1, 2, 3, 5, 10 marks)
3. **Flashcard & Mnemonic Generation** — Creates flashcard collections with front/back pairs, types, and mnemonics
4. **PYQ Processing Pipeline:**
   - PDF upload of previous year question papers
   - Gemini Vision OCR extracts text from scanned PDFs
   - AI extraction parses questions, marks, years
   - SEO-optimized HTML output for each PYQ collection
5. **Blog Publishing:**
   - 5-step wizard: Scope → Draft → AI Enrichment → SEO Meta → Publish
   - AI enrichment adds geo tags, schema markup, and internal links
6. **Thumbnail Studio** — AI-powered subject/chapter cover image generation

---

## 8. SEO Strategy

### Programmatic SEO Pages

Pages are auto-generated for high-intent educational topics from the syllabus:

**Route Structure:** `/:board/:classSlug/:subjectSlug/:topicSlug/:pageType`

**Page Types:**
| Type | Description |
|---|---|
| `notes` | Detailed topic notes (default if no `:pageType`) |
| `mcqs` | Multiple choice questions |
| `important-questions` | Important exam questions |
| `examples` | Solved examples |
| `syllabus` | Syllabus overview |

### SEO Implementation

| Feature | Implementation |
|---|---|
| **Dynamic Meta Tags** | `react-helmet-async` via `PageMeta` component — sets `<title>`, `<meta description>`, Open Graph tags, `<meta keywords>`, canonical URL |
| **JSON-LD Structured Data** | Injected on all content pages — types include `Article`, `FAQPage`, `HowTo`, `BreadcrumbList` |
| **Sitemap** | Auto-generated `sitemap.xml` from all published `seo_pages` |
| **Internal Linking** | Analysis tool in Admin SEO Manager identifies and injects contextual internal links between related pages |
| **Breadcrumb Navigation** | All content pages show breadcrumbs: Home → Board → Class → Subject → Topic |
| **Blog SEO Workflow** | 5-step wizard with AI-powered meta generation, geo-tagging (Assam, Guwahati, etc.), and schema markup |
| **Content Quality Scoring** | Vertex AI Studio scores content quality and suggests improvements before publishing |
| **Coverage Tracking** | SEO Manager tracks `{topics} × {page_types}` matrix and reports coverage percentage |

---

## 9. Payments & Monetization

### Razorpay (INR — Primary Gateway for Indian Payments)

| Plan | Price | Credits |
|---|---|---|
| Starter | ₹99 | 300 / month |
| Pro | ₹999 | 4000 / month + full document access |

- Razorpay integration with server-side order creation
- Webhook integration for payment verification
- Payment records stored in MongoDB `payments` collection

### Stripe (USD — International Payments)

| Plan | Price | Credits |
|---|---|---|
| Starter | $1.99 | 300 / month |
| Pro | $12.99 | 4000 / month + full document access |

- Stripe Checkout Sessions for payment flow
- `payment/success` and `payment/cancel` redirect pages
- Webhook integration for async payment confirmation

### Credit Top-Ups

- Users can purchase additional credits beyond their plan limits
- Top-up purchases processed through the same Razorpay/Stripe gateways

### Plan Configuration

- Plan details stored in MongoDB `plan_config` collection
- Configurable via Admin Panel → Plans & Credits section
- Prices stored in smallest currency unit (paise for INR, cents for USD)

---

## 10. PWA & Mobile Experience

### 10a. PWA Configuration

**`manifest.json` Key Properties:**

| Property | Value |
|---|---|
| `name` | "Syrabit.ai — AHSEC AI Exam Prep" |
| `short_name` | "Syrabit.ai" |
| `display` | `standalone` |
| `display_override` | `["standalone", "minimal-ui", "browser"]` |
| `orientation` | `any` |
| `background_color` | `#06060e` |
| `theme_color` | `#7c3aed` |
| `lang` | `en-IN` |
| `categories` | `["education", "productivity"]` |
| `start_url` | `/library` |
| `scope` | `/` |

**Home Screen Shortcuts:**
1. "Open Library" → `/library`
2. "Start Chat" → `/chat`

**Icons:** 72x72, 96x96, 128x128, 144x144, 152x152, 192x192 (maskable), 384x384, 512x512 (maskable)

### 10b. Service Worker

**File:** `public/sw.js`
**Cache Version:** `syrabit-v3.1-pwa`

**Pre-cached Static Assets (on install):**
- `/manifest.json`
- `/offline.html`
- `/icons/icon-192x192.png`
- `/icons/icon-512x512.png`

**Caching Strategies:**

| Request Type | Strategy | Details |
|---|---|---|
| Navigation (HTML) | Network-first | Falls back to cache, then `/offline.html` |
| Static Assets (images, fonts) | Cache-first | Serves from cache immediately, updates in background |
| API `/api/content/` | Network-first with cache | Caches successful GET responses for offline reading |
| Other GET requests | Network-first with cache fallback | — |

**Exclusions (bypass service worker entirely):**
- `/ai/chat/stream` — AI streaming (real-time, never cached)
- `/ai/chat` — Chat API
- `/api/cms/` — CMS APIs (avoids body-stream errors)
- Non-GET requests — Never cached

**Background Sync:**
- `chat-sync` tag registered for offline message delivery (logged but not fully implemented)

**Push Notifications:**
- Handles `push` events — shows notification with title, body, icon, badge
- Handles `notificationclick` — opens the target URL

**Cache Versioning:**
- Old caches auto-deleted on activation
- `skipWaiting()` and `clients.claim()` for immediate activation

### 10c. Mobile UX

**Bottom Navigation Bar:**
- 4 tabs: Browser (`/library`), Chat (`/chat`), History (`/history`), Profile (`/profile`)
- Glassmorphic blur: `blur(28px) saturate(1.6)` with `rgba(5,4,14,0.90)` background
- Active tab: Violet highlight (`#a78bfa`) with drop-shadow glow and active dot indicator
- Minimum touch target: `44px × 44px`
- Safe-area inset padding: `paddingBottom: env(safe-area-inset-bottom, 0px)`

**Route Preloading:**
- `onTouchStart` and `onMouseEnter` on nav items trigger lazy chunk preloading
- `pageImports` map provides preload functions for each route
- `prefetchRoute` utility preloads route data

**Chat Input:**
- Auto-expanding textarea (max 160px height)
- `textarea.style.height = 'auto'; textarea.style.height = Math.min(scrollHeight, 160) + 'px'`

**Performance:**
- Hardware-accelerated CSS animations (`transform`, `opacity`)
- `prefers-reduced-motion` support — disables all animations
- RAF-based token batching limits React re-renders to 60fps during AI streaming
- Code splitting via `React.lazy()` on all page components
- `DeferredFallback` delays loading spinner by 300ms to avoid flash

---

## 11. Third-Party Integrations Summary

| Service | Purpose | Integration Point |
|---|---|---|
| **Groq** | Primary LLM inference (Llama 3.1/3.3 models) | Backend `llm.py` |
| **Google Gemini / Vertex AI** | Embeddings (`text-multilingual-embedding-002`), Vision OCR, content enhancement | Backend `rag.py`, Admin Vertex Panel |
| **Sarvam AI** | Regional language support, translation, TTS | Backend, Admin Translation tool |
| **Fireworks AI** | DeepSeek/Qwen model inference | Backend `llm.py` |
| **Cerebras** | Ultra-fast Llama inference | Backend `llm.py` |
| **Voyage AI** | RAG result reranking | Backend `rag.py` |
| **OpenRouter / OpenAI / xAI** | Fallback LLM providers | Backend `llm.py` |
| **MongoDB Atlas** | Content database + vector search | Backend `db_ops.py` |
| **Redis (Upstash)** | Sessions, rate limiting, AI response caching | Backend `cache.py` |
| **PostgreSQL** | Users, conversations, activity logs | Backend `db_ops.py` |
| **Supabase** | Legacy data mirror for durability | Backend `db_ops.py` |
| **Razorpay** | INR payments (Starter ₹99, Pro ₹999) | Backend `routes/admin_monetization.py` |
| **Stripe** | USD payments (Starter $1.99, Pro $12.99) | Backend `routes/admin_monetization.py` |
| **Google Analytics 4** | Frontend page tracking + backend event tracking | Frontend `analytics.js`, Admin Analytics |
| **PostHog** | Product analytics and user behavior tracking | Frontend |
| **Resend** | Transactional emails (password reset, welcome) | Backend `routes/auth.py` |
| **Web Push (pywebpush)** | Browser push notifications (VAPID) | Backend, Service Worker |
| **Cloudflare AI Gateway** | LLM routing, caching, fallback orchestration | Backend `llm.py` |
| **DuckDuckGo / Tavily** | Web search for AI context (Tier 3 grounding) | Backend `routes/ai_chat.py` |
| **Google OAuth 2.0** | Social login ("Sign in with Google") | Backend `routes/auth.py`, Frontend Login/Signup |
| **Playwright / Trafilatura** | Web scraping and content extraction for RAG | Backend |

---

## 12. Key Business Rules

1. **Credit System:** 1 credit = 1 AI response. Free tier credits reset daily (30/day). Paid tier credits are monthly quotas (Starter: 300, Pro: 4000). Credit deduction is atomic in PostgreSQL to prevent race conditions. Credits are refunded on failed AI streams.

2. **Academic Scope Guard:** The AI assistant ("Syra") only answers questions related to the Assam Board curriculum (AHSEC, SEBA, Degree level). Non-academic queries are politely declined with a suggestion to ask an academic question instead.

3. **Content Hierarchy:** All content follows a strict hierarchy:
   ```
   Board → Class → Stream → Subject → Chapter → Topic
   ```
   This hierarchy is enforced in both MongoDB (content storage) and the admin CMS interface. Subject selection in the Content Hub propagates across all tabs.

4. **Dual-Auth System:** Separate JWT secrets for students (`JWT_SECRET`) and admins (`ADMIN_JWT_SECRET`). Admin routes require the `is_admin` flag and a valid admin JWT. Admin sessions use httpOnly cookies with 20-minute keep-alive refresh.

5. **Data Durability:** User data (accounts, conversations) is written to both PostgreSQL (primary) and Supabase (mirror) for redundancy. If PostgreSQL write succeeds but Supabase fails, the operation still succeeds — Supabase is a best-effort mirror.

6. **Rate Limiting:** Plan-aware rate limiting via Redis sliding windows:
   - Free users: Stricter request limits (lower requests/minute)
   - Paid users: Relaxed limits proportional to plan tier
   - IP-based limits apply to all users regardless of plan
   - Returns `429 Too Many Requests` with `Retry-After` header

7. **AI Fallback Chain:** If the primary LLM provider (Cerebras/Groq) fails, the system automatically tries the next provider in speed-priority order:
   ```
   Cerebras → Groq → Fireworks → Sarvam → Gemini → OpenRouter
   ```
   The failover is transparent to the user — streaming continues without interruption. Cloudflare AI Gateway handles routing and caching at the infrastructure level.

8. **Landing Page Auto-Redirect:** The landing page (`/`) auto-redirects authenticated users to `/library`. Unauthenticated users see the landing page for 3 seconds before being redirected to `/chat`.

9. **Content Pipeline Idempotency:** The "SEO Polish" pipeline reuses existing notes and only re-generates blog/PYQ pages, while "Auto-Generate Full Subject" creates everything from scratch. Both report progress in real-time via the `PipelineProgressPanel`.

10. **Admin System Status:** The admin dashboard header dynamically displays system health:
    - "All Systems Operational" (green) — All DB connections and LLM providers healthy
    - "Setup Required" (amber) — One or more dependencies not configured
    - "Maintenance Mode" (red) — `maintenance_mode` enabled in site settings

---

*End of Developer Handoff Document*
