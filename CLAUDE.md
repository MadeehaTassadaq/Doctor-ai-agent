# Doctor AI Agent SaaS — Project Constitution

## ═══════════════════════════════════════════
## IDENTITY & PURPOSE
## ═══════════════════════════════════════════

**Project:** Doctor AI Agents for Clinic Management & Appointment Booking SaaS
**Vision:** A production-grade, multi-tenant, cloud-native healthcare SaaS platform where AI agents assist clinics with appointment booking, patient triage, medical summaries, and workflow automation.
**Methodology:** Spec-Driven Development (SDD) — specs are the primary artifact; code is generated output.

This constitution is the IMMUTABLE source of truth. Every subagent, every session, every line of code must conform to these principles. When in doubt, consult this document first.

## ═══════════════════════════════════════════
## TECH STACK (IMMUTABLE)
## ═══════════════════════════════════════════

| Layer | Technology | Notes |
|-------|-----------|-------|
| Frontend | Next.js 15 App Router + TypeScript | Server Components, Server Actions |
| UI | Tailwind CSS + ShadCN UI | Component-first, dark mode support |
| Backend API | FastAPI (Python) | Async, Pydantic validation, auto-docs |
| Database | Supabase PostgreSQL | Managed Postgres with RLS |
| ORM | SQLAlchemy 2.0 (async) + Supabase Python Client | Type-safe queries, Alembic migrations |
| Auth | Supabase Auth | JWT, RLS integration, RBAC |
| AI Agents | OpenAI Agents SDK | Multi-agent orchestration, handoffs, guardrails |
| AI Models | OpenAI (GPT-4o etc.) | Structured outputs, function calling, streaming |
| Vector DB | Pinecone | RAG for medical knowledge |
| Messaging | Kafka (or Redpanda) | Event-driven architecture |
| Cache/Queue | Redis | Caching, sessions, rate limiting, BullMQ |
| File Storage | Supabase Storage / AWS S3 | Prescriptions, reports, scans |
| Payments | Stripe | SaaS subscriptions, billing |
| Containers | Docker | Multi-stage builds, <100MB images |
| Orchestration | Kubernetes | Deployments, HPA/KEDA, Ingress |
| CI/CD | GitHub Actions + ArgoCD | GitOps workflow |
| Observability | Prometheus + Grafana + Loki | Metrics, logs, traces |

## ═══════════════════════════════════════════
## ARCHITECTURE PRINCIPLES
## ═══════════════════════════════════════════

### 1. Monorepo Structure
All services live in `/apps/*` within a single repository. Shared packages in `/packages/*`.

### 2. Microservices Topology
```
/apps
  /web                    — Next.js 15 frontend (TypeScript)
  /appointment-service    — FastAPI: Appointment CRUD, scheduling
  /patient-service        — FastAPI: Patient management
  /doctor-service         — FastAPI: Doctor profiles, schedules
  /notification-service   — FastAPI: Email, WhatsApp, SMS
  /ai-agent-service       — FastAPI + OpenAI Agents SDK orchestration
  /billing-service        — FastAPI: Stripe subscriptions
  /api-gateway            — FastAPI: Request routing, auth, rate limiting
```

### 3. Multi-Tenancy
Every table MUST have a `tenant_id` column. All queries MUST filter by tenant. Supabase RLS enforces tenant isolation at the database level.

### 4. Event-Driven Architecture
Services communicate asynchronously via Kafka topics. NEVER call services synchronously for cross-service workflows. Use:
- `appointment.created`
- `appointment.cancelled`
- `payment.completed`
- `report.generated`
- `patient.registered`
- `notification.send`

### 5. API Design
- RESTful endpoints with consistent naming: `/api/v1/{resource}`
- Request validation via Pydantic v2 models (FastAPI native)
- Pagination: cursor-based for lists, `limit` + `cursor`
- Error responses follow RFC 9457 (Problem Details, via Pydantic)
- Rate limiting per tenant, per endpoint
- Auto-generated OpenAPI docs at `/docs` and `/redoc`
- Health check endpoint at `/health` (liveness) and `/health/ready` (readiness)
- Async handlers with `async def` everywhere; no blocking calls

### 6. Database Principles
- SQLAlchemy 2.0 async with Alembic for migrations (auto-generated from model changes)
- Supabase Python client for RLS-enabled client-side queries (when accessing from trusted services)
- Row Level Security (RLS) for tenant isolation
- Soft deletes (`deleted_at`) for all patient data
- Audit logging via triggers on all mutations
- Indexes on: `tenant_id`, `foreign_keys`, `status`, `created_at`

### 7. AI Agent Principles (OpenAI Agents SDK)
- **SDK**: OpenAI Agents SDK (Python) — lightweight, production-ready agent framework
- **Architecture**: Single supervisor agent with handoffs to specialized sub-agents
- **Agent Types**:
  - `TriageAgent` — Routes patient inquiries to the right specialist agent
  - `BookingAgent` — Handles appointment booking via function tools
  - `MedicalSummaryAgent` — Generates structured summaries from doctor notes
  - `FAQAgent` — Answers clinic/hospital questions via RAG
  - `FollowUpAgent` — Sends reminders and follow-up messages
- **Tools**: Each agent exposes async Python functions as tools decorated with `@function_tool`
- **Handoffs**: Agents hand off to each other using `handoffs` parameter with optional message filtering
- **Guardrails**: Input guardrails for abuse detection/PII filtering; output guardrails for validation
- **Structured Outputs**: Pydantic models for all agent responses via `output_type` parameter
- **Memory**: Conversation persistence via SQLite sessions (production: Redis/Postgres)
- **Tracing**: OpenAI tracing for debugging; OpenTelemetry export for production observability
- **RAG**: `FileSearchTool` for vector search over medical knowledge base
- **Human-in-the-loop**: Critical actions (prescriptions, diagnoses) require manual approval before execution
- **Streaming**: Real-time token streaming for chat UX via `Runner.run_streamed()`

## ═══════════════════════════════════════════
## CODING STANDARDS
## ═══════════════════════════════════════════

### TypeScript (Next.js Frontend)
- Strict mode. No `any`. Use `unknown` and type guards.
- Prefer `interface` over `type` for object shapes.
- Use `const` assertions for literal types.
- All functions MUST have explicit return types.
- Use branded types for IDs: `type PatientId = string & { __brand: 'Patient' }`

### Python (FastAPI Microservices)
- Python 3.12+. Type hints everywhere. Use `mypy --strict`.
- Use `async def` for all route handlers and database operations.
- Pydantic v2 models for all request/response schemas.
- Repository pattern for database access (not raw SQL in handlers).
- Dependency injection via FastAPI `Depends()` for auth, DB sessions, services.
- Service layer between routes and repositories — routes should NOT contain business logic.
- Use `structlog` for structured logging (JSON output).
- Alembic for database migrations (auto-generated).
- Poetry or `uv` for dependency management.
- All config via environment variables with Pydantic `BaseSettings`.
- Test with `pytest` + `httpx.AsyncClient` for API tests.

### React / Next.js (Frontend Only, `apps/web`)
- Use Server Components by default. Client Components only when needed (interactivity, browser APIs, state).
- Server Actions for lightweight mutations. Heavy workflows delegate to FastAPI services.
- Use `useTransition` for pending states, not `useState` + `useEffect`.
- Loading states: `loading.tsx` + `Suspense` boundaries.
- Error boundaries: `error.tsx` at every route segment.
- Next.js ONLY handles the frontend. All data goes through the FastAPI API Gateway.

### Next.js Frontend Structure (`apps/web`)
- Components in `@/components/{domain}/{ComponentName}.tsx`
- Page components in `@/app/{route}/page.tsx`
- Shared UI from ShadCN in `@/components/ui/`
- Custom hooks in `@/hooks/`
- Utilities in `@/lib/`
- Types in `@/types/`
- API client in `@/lib/api-client.ts` (typed fetch wrapper to FastAPI gateway)

### FastAPI Service Structure (each service in `apps/{service-name}/`)
```
apps/{service-name}/
├── app/
│   ├── __init__.py
│   ├── main.py              — FastAPI app factory
│   ├── config.py            — Pydantic BaseSettings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py    — Route definitions
│   │   │   └── deps.py      — Dependencies (auth, DB)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── domain.py        — Pydantic domain models
│   │   └── schemas.py       — Pydantic request/response schemas
│   ├── services/
│   │   ├── __init__.py
│   │   └── {service}.py     — Business logic layer
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── {repo}.py        — Database access layer
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py       — Async DB sessions
│   │   └── models.py        — SQLAlchemy ORM models
│   ├── messaging/
│   │   ├── __init__.py
│   │   └── producer.py      — Kafka producers
│   └── middleware/
│       ├── __init__.py
│       └── auth.py          — JWT verification middleware
├── tests/
├── alembic/                 — DB migrations
├── alembic.ini
├── pyproject.toml
├── Dockerfile
└── README.md
```

### Testing
- **Python (FastAPI services):** `pytest` + `pytest-asyncio` + `httpx.AsyncClient`
  - Unit tests per service/repository layer
  - Integration tests with test database (SQLite async or test Postgres)
  - API tests via `TestClient` or `AsyncClient`
  - Factory pattern for test data (use `factory_boy`)
- **TypeScript (Next.js frontend):** Vitest for utilities, hooks; Playwright for E2E
- **AI Agent tests:** OpenAI Agents SDK test harness — mock `Runner` and `ModelProvider`, test individual agent tools, test handoff routing with mocked responses, test guardrail triggers
- Every spec must have a corresponding test file
- Minimum 80% code coverage target for services
- `pytest-cov` for Python coverage, `c8`/`istanbul` for TypeScript

### Git Conventions
- Branch: `{type}/{description}` (e.g., `feat/appointment-booking`)
- Commits: Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`)
- Each task implementation = one atomic commit

## ═══════════════════════════════════════════
## SDD WORKFLOW (HOW WE BUILD)
## ═══════════════════════════════════════════

### Four-Phase Workflow

**Phase 1 — Parallel Research**
Before writing any spec, research with subagents. Check existing code, libraries, best practices, and alternatives. Document findings.

**Phase 2 — Write Specification**
Every spec follows this template:
```markdown
# SPEC: {Title}
## Status
[Draft | Refining | Approved | Implemented]

## Context
Why this exists, what problem it solves.

## Requirements
- Bullet list of functional requirements
- Acceptance criteria

## Design
Detailed design decisions, trade-offs, rationale.

## Out of Scope
Explicitly what NOT to build.

## Interfaces
APIs, schemas, component props, types.

## Data Flow
How data moves through the system.

## Error Handling
What happens when things go wrong.

## Testing
How to verify this spec is implemented correctly.
```

**Phase 3 — Refinement via Interview**
Before implementing, use `AskUserQuestion` to surface ambiguities. Clarify at least 2-3 design decisions before writing code.

**Phase 4 — Task-Based Implementation**
Break spec into atomic tasks. Each task:
1. Create a Task in the task list
2. Implement via subagent
3. Verify against spec
4. Commit atomically

### Role Assignments
- **Main Agent (me):** Project lead. Read constitution, orchestrate phases, review output.
- **Subagents:** Devs. Each subagent gets full context + spec. Implements and returns.
- **User:** Product owner. Approves specs, makes design decisions via interview.

## ═══════════════════════════════════════════
## FILE ORGANIZATION
## ═══════════════════════════════════════════

```
/
├── CLAUDE.md                  ← THIS FILE: Project Constitution (source of truth)
├── .claude/
│   └── skills/                ← Custom Claude Code skills
│       ├── fastapi-service/   — Skill: Scaffold a new FastAPI microservice
│       ├── k8s-deploy/        — Skill: Deploy service to Kubernetes
│       └── openai-agents-sdk/ — Skill: Build OpenAI Agents SDK agents
├── .claude/specs/             ← All specification documents
│   ├── INDEX.md               ← Spec registry (index of all specs with status)
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── DATABASE_SCHEMA.md
│   ├── API_SPEC.md
│   ├── AI_AGENTS.md
│   └── KUBERNETES_ARCHITECTURE.md
├── apps/
│   ├── web/                   ← Next.js 15 frontend (TypeScript)
│   ├── appointment-service/   ← FastAPI microservice (Python)
│   ├── patient-service/       ← FastAPI microservice (Python)
│   ├── doctor-service/        ← FastAPI microservice (Python)
│   ├── notification-service/  ← FastAPI microservice (Python)
│   ├── ai-agent-service/      ← FastAPI + LangGraph (Python)
│   ├── billing-service/       ← FastAPI microservice (Python)
│   └── api-gateway/           ← FastAPI gateway (Python)
├── packages/
│   ├── shared-types/          ← Shared TypeScript types (for frontend)
│   ├── database/              ← Shared DB models, Alembic config
│   ├── kafka-events/          ← Event type definitions (Avro/Pydantic)
│   └── ui/                    ← Shared ShadCN UI components
├── k8s/
│   ├── base/                  ← Base K8s manifests (per service)
│   └── overlays/              ← Environment-specific overlays
├── docker/
│   ├── Dockerfile.nextjs      ← Frontend container
│   └── Dockerfile.fastapi     ← Base image for Python microservices
└── scripts/
    ├── dev-setup.sh
    └── seed.py
```

## ═══════════════════════════════════════════
## CRITICAL RULES
## ═══════════════════════════════════════════

1. **Constitution over conversation.** When Claude's suggestion contradicts this constitution, constitution wins.
2. **Specs before code.** No implementation without an approved spec. Period.
3. **Interview before implementation.** Always clarify ambiguities with the user before writing code.
4. **One task at a time.** Complete and verify each task before starting the next.
5. **Commit after each task.** Each completed task = one atomic git commit.
6. **Verification against spec.** After implementation, verify the output matches the spec's acceptance criteria.
7. **AI comes last.** Authentication → Database → SaaS architecture → Payments → Core features → AI agents. AI is the final layer.
8. **Healthcare compliance mindset.** Even at MVP stage, design for HIPAA-inspired security: encryption, audit logs, access control, data isolation.
