# SPEC: System Architecture

## Status
**Approved**

## Context

This document defines the overall system architecture for the Doctor AI Agent SaaS platform — a production-grade, multi-tenant, cloud-native healthcare platform where AI agents assist clinics with appointment booking, patient triage, medical summaries, and workflow automation.

The platform serves multiple clinics (tenants), each with their own doctors, patients, staff, and clinical data. AI agents assist with routine tasks but never make autonomous clinical decisions — human-in-the-loop is required for all critical actions.

This spec is the foundation document. Every subsequent spec (database, API, services, AI agents, deployment) derives its constraints from this architecture.

## Requirements

### Functional Requirements

1. **Multi-Tenant Clinic Management** — Each clinic is a tenant with isolated data. Clinics manage doctors, patients, appointments, billing, and staff.
2. **Appointment Booking** — Patients book appointments with doctors. AI Booking Agent assists with scheduling, rescheduling, cancellations, and availability queries.
3. **Patient Triage** — AI Triage Agent collects symptoms and urgency level before routing to appropriate care.
4. **Medical Summaries** — AI Medical Summary Agent generates structured SOAP notes from doctor dictation/notes.
5. **FAQ & Knowledge Base** — AI FAQ Agent answers clinic/hospital questions via RAG over medical knowledge base.
6. **Follow-up Automation** — AI Follow-Up Agent sends reminders and follow-up messages after appointments.
7. **Billing & Subscriptions** — Stripe-powered SaaS billing with tiered plans (per-seat or per-clinic pricing).
8. **Notifications** — Email and WhatsApp notifications for appointment confirmations, reminders, and follow-ups.
9. **Audit Logging** — Every data mutation is logged for HIPAA-inspired compliance.
10. **Real-Time Streaming** — AI agent responses streamed to the frontend for chat UX.

### Non-Functional Requirements

1. **Tenant Isolation** — Strict data isolation between clinics at application, database, and storage layers.
2. **High Availability** — 99.9% uptime for core services (appointment booking, patient data access).
3. **Scalability** — Horizontal scaling for services. Support 100+ clinics at launch, designed for 1000+.
4. **Latency** — API responses <200ms p95 for non-AI endpoints. AI streaming responses <2s to first token.
5. **Security** — HIPAA-inspired: encryption at rest and in transit, audit trails, access control, data isolation.
6. **Observability** — Metrics, logs, and traces for every service. Alerting on SLO breaches.
7. **Disaster Recovery** — RPO <5 minutes, RTO <30 minutes for critical services.

## Design

### 1. Overall Architecture Philosophy

```
                    ┌──────────────────────────────────────┐
                    │           Cloudflare / DNS            │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │         Ingress Controller            │
                    │         (Kubernetes Ingress)          │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │          API Gateway                 │
                    │     (FastAPI - apps/api-gateway)     │
                    │  Auth / Rate Limiting / Routing      │
                    └──┬───────┬───────┬───────┬──────────┘
                       │       │       │       │
          ┌────────────┼───────┼───────┼───────┼─────────────┐
          │            │       │       │       │             │
    ┌─────▼────┐ ┌────▼───┐ ┌─▼──────┐ ┌────▼───┐ ┌────────▼───┐
    │Appointment│ │Patient │ │ Doctor │ │Notifica│ │  Billing   │
    │ Service   │ │Service │ │ Service│ │ Service│ │  Service   │
    └─────┬─────┘ └────┬───┘ └──┬─────┘ └────┬───┘ └────────┬───┘
          │            │        │            │              │
          └────────────┼────────┼────────────┼──────────────┘
                       │        │            │
          ┌────────────▼────────▼────────────▼──────────────┐
          │              Message Bus (Kafka)                 │
          │  appointment.created │ patient.registered │ ...  │
          └────────────────────────┬───────────────────────┘
                                   │
          ┌────────────────────────▼───────────────────────┐
          │            AI Agent Service                     │
          │  (FastAPI + OpenAI Agents SDK Orchestrator)    │
          │  Triage │ Booking │ MedicalSummary │ FAQ        │
          │  FollowUp                                       │
          └────────────────────────┬───────────────────────┘
                                   │
          ┌────────────────────────▼───────────────────────┐
          │            Vector DB (Pinecone)                 │
          │  Medical knowledge / FAQ embeddings             │
          └────────────────────────────────────────────────┘
```

The platform follows a **microservices topology** where each bounded context is an independent FastAPI service. Services communicate asynchronously via Kafka for cross-domain workflows (e.g., appointment created → notification sent). The API Gateway is the single entry point for all client requests, handling authentication, rate limiting, and routing.

### 2. Service Boundaries

| Service | Domain | Owns | Key Events Published |
|---------|--------|------|---------------------|
| **API Gateway** | Entry point | Auth, routing, rate limiting | — |
| **Appointment Service** | Scheduling | Appointments, slots, calendars | `appointment.created`, `appointment.cancelled`, `appointment.rescheduled` |
| **Patient Service** | Patient data | Patient profiles, medical history, triage forms | `patient.registered`, `patient.updated` |
| **Doctor Service** | Provider data | Doctor profiles, schedules, specialties | `doctor.availability.updated` |
| **Notification Service** | Communication | Email, WhatsApp, SMS templates | — (consumes events) |
| **Billing Service** | Payments | Subscriptions, invoices, Stripe integration | `payment.completed`, `subscription.changed` |
| **AI Agent Service** | AI orchestration | Triage, booking assistant, summaries, FAQ, follow-ups | `report.generated`, `followup.scheduled` |

### 3. Multi-Tenancy Strategy

**Approach: Shared schema with tenant_id column + PostgreSQL Row-Level Security (RLS)**

This is the recommended starting point for a healthcare SaaS with <1000 tenants. Each tenant is a clinic.

```
Every table: tenant_id UUID NOT NULL REFERENCES tenants(id)
Every query: WHERE tenant_id = current_tenant
RLS: Enforced at database level as defense-in-depth
```

**Tenant Context Flow:**
1. User authenticates → JWT contains `tenant_id` and `role` claims
2. API Gateway verifies JWT → injects `X-Tenant-ID` header internally
3. FastAPI middleware extracts tenant_id → sets PostgreSQL session variable
4. RLS policies use `current_setting('app.current_tenant_id')` for enforcement
5. Repository layer also filters by `tenant_id` as application-level enforcement

**Tenant tiers:**
- `tenant_tier` on the `tenants` table: `free`, `pro`, `enterprise`
- Different rate limits, storage quotas, and feature flags per tier
- Rate limiting keys are tenant-namespaced: `ratelimit:{tenant_id}:{endpoint}:{minute}`

### 4. Communication Patterns

#### 4.1 Synchronous — REST over HTTP (via API Gateway)

Client → API Gateway → Service. Used for CRUD operations where immediate response is required.

```
GET /api/v1/appointments?status=scheduled&limit=20&cursor=abc123
POST /api/v1/patients
PUT /api/v1/doctors/{id}/schedule
```

#### 4.2 Asynchronous — Kafka Event Bus

Services publish events to Kafka topics. Other services consume events they're interested in. NEVER call services synchronously for cross-service workflows.

**Event Topics:**

| Topic | Key Schema | Producer | Consumers |
|-------|-----------|----------|-----------|
| `appointment.created` | `{tenant_id}:{appointment_id}` | Appointment Service | Notification Service, AI Agent Service |
| `appointment.cancelled` | `{tenant_id}:{appointment_id}` | Appointment Service | Notification Service, AI Agent Service |
| `appointment.rescheduled` | `{tenant_id}:{appointment_id}` | Appointment Service | Notification Service |
| `patient.registered` | `{tenant_id}:{patient_id}` | Patient Service | AI Agent Service |
| `patient.updated` | `{tenant_id}:{patient_id}` | Patient Service | — |
| `payment.completed` | `{tenant_id}:{invoice_id}` | Billing Service | Notification Service |
| `subscription.changed` | `{tenant_id}` | Billing Service | API Gateway (feature flags) |
| `report.generated` | `{tenant_id}:{report_id}` | AI Agent Service | Notification Service |
| `notification.send` | `{tenant_id}:{notification_id}` | Any | Notification Service |

#### 4.3 Streaming — Server-Sent Events (SSE)

AI agent responses streamed to frontend via SSE through the API Gateway.

```
Client → SSE /api/v1/ai/chat/stream → API Gateway → AI Agent Service → OpenAI streaming
```

### 5. API Design

All APIs follow RESTful conventions, versioned under `/api/v1/`.

- **Base URL:** `https://api.doctorai.example.com/api/v1/`
- **Authentication:** Bearer JWT token in `Authorization` header
- **Tenant Context:** Derived from JWT claims (not a separate header for external clients)
- **Pagination:** Cursor-based for lists (`limit` + `cursor` query params)
- **Error Format:** RFC 9457 Problem Details
- **Rate Limiting:** Per-tenant, per-endpoint. Return `429 Too Many Requests` with `Retry-After` header.
- **Idempotency:** POST requests support `Idempotency-Key` header for safe retries.

### 6. Database Architecture

**Primary Database:** Supabase PostgreSQL (managed Postgres)

**Schema Strategy:** Single database, shared schema, `tenant_id` column on every tenant-scoped table.

**Key Design Points:**
- SQLAlchemy 2.0 async models with Alembic migrations
- Soft deletes (`deleted_at`) on all patient and clinical data
- Audit triggers on all mutation operations (INSERT, UPDATE, DELETE)
- Indexes on: `tenant_id`, all foreign keys, `status`, `created_at`, `deleted_at`
- RLS policies on every tenant-scoped table

**Vector Database:** Pinecone (serverless index) for medical knowledge RAG embeddings.

**Caching:** Redis for:
- Session storage
- Rate limiting counters
- Frequently accessed data (clinic info, doctor schedules)
- AI agent conversation state

### 7. AI Agent Architecture

**Framework:** OpenAI Agents SDK (Python)

**Pattern:** Single supervisor (TriageAgent) with handoffs to specialized sub-agents

```
                    ┌─────────────────────────┐
                    │     Triage Agent         │
                    │  (Router/Orchestrator)   │
                    └────┬──────┬──────┬──────┘
                         │      │      │
              ┌──────────┼──────┼──────┼──────────┐
              │          │      │      │          │
        ┌─────▼───┐ ┌───▼──┐ ┌─▼────┐ ┌▼──────┐ ┌▼──────┐
        │ Booking │ │Medical│ │ FAQ  │ │Follow │ │ Triage│
        │  Agent  │ │Summar│ │Agent │ │-Up    │ │ Agent │
        └─────────┘ └──────┘ └──────┘ │Agent  │ │(triage│
                                       └───────┘ │ sub)  │
                                                 └───────┘
```

**Key Primitives:**
- **`function_tool`** — Each agent exposes async Python functions as tools. Tools call core services (appointment, patient, doctor) via REST APIs.
- **Guardrails** — Input guardrails for PII filtering and abuse detection. Output guardrails for validation of structured outputs.
- **Structured Outputs** — All agent responses return Pydantic models via `output_type` parameter.
- **Human-in-the-Loop (Hybrid Risk Model)** — Three-tier approval based on risk level:
  - **Low risk** (FAQ answers, knowledge base queries, general info): Auto-execute. No approval needed.
  - **Medium risk** (rescheduling, follow-ups, triage assessments): Inline confirmation. Agent asks in chat: "I can reschedule to 3pm Tuesday. Confirm?" User responds yes/no before execution.
  - **High risk** (cancellations, prescriptions, diagnosis changes, billing actions): Async approval queue. Agent submits to a pending queue; doctor/staff reviews from a dashboard. Patient sees "pending approval" status until resolved.
- **Memory** — Conversation persistence via Redis (production). Sessions keyed by `{tenant_id}:{conversation_id}`.
- **RAG** — Custom vector search for medical knowledge base queries via Pinecone.

### 8. Frontend Architecture

**Framework:** Next.js 15 App Router + TypeScript

**Data Flow:**
1. Next.js Server Components fetch initial data from FastAPI API Gateway
2. Client Components use typed API client for interactive operations
3. Server Actions for lightweight mutations (form submissions)
4. Heavy/async workflows delegated to FastAPI services via API Gateway
5. AI chat streams via SSE through the API Gateway

**Page Structure (Multi-tenant, per-clinic):**

```
/                    → Landing page (public)
/login               → Auth
/dashboard           → Clinic dashboard (tenant-scoped)
/dashboard/appointments → Appointment management
/dashboard/patients     → Patient records
/dashboard/doctors      → Doctor management
/dashboard/ai           → AI assistant chat interface
/dashboard/settings     → Clinic settings
/dashboard/billing      → Subscription management
```

### 9. Deployment Architecture

**Containerization:** Docker multi-stage builds (<100MB images)
**Orchestration:** Kubernetes (single cluster initially, multi-cluster for HA later)
**CI/CD:** GitHub Actions → Build images → Push to registry → ArgoCD sync

**Kubernetes Resource Design:**

```
Each service:
├── Deployment (with HPA based on CPU/memory/custom metrics)
├── Service (ClusterIP)
├── ConfigMap (app config, non-sensitive)
├── Secret (DB credentials, API keys — sealed with SealedSecrets)
└── ServiceMonitor (Prometheus scraping config)

Shared:
├── Ingress Controller (nginx-ingress or Traefik)
├── Cert-Manager (Let's Encrypt TLS)
├── Prometheus Stack (Grafana, AlertManager, Loki)
└── Kafka Cluster (Strimzi operator or Confluent Operator)
```

**Environment Tiers:**
- `dev` — Single replica, shared resources, feature flags for in-progress work
- `staging` — Production-like, with mock external services
- `prod` — HA configuration (3+ replicas), HPA, PDB, multi-AZ

### 10. Observability Stack

| Signal | Tool | Details |
|--------|------|---------|
| Metrics | Prometheus | Request rate, error rate, latency (RED metrics), per-endpoint, per-service |
| Dashboards | Grafana | Service-level dashboards, tenant-level dashboards |
| Logs | Loki via Promtail | Structured JSON logs via `structlog`, aggregated in Grafana |
| Traces | OpenTelemetry | Distributed tracing across service boundaries, Kafka message tracing |
| Alerts | AlertManager | PagerDuty integration for critical alerts (p99 latency, error budget) |
| Uptime | Status page | External synthetic monitoring for core endpoints |

**Key SLOs:**
- Availability: 99.9% (monthly)
- API p95 latency: <200ms
- AI first-token latency: <2s
- Error rate: <0.1% of all requests

### 11. Security Architecture

| Layer | Measure |
|-------|---------|
| Transport | TLS 1.3 everywhere (in-cluster and external) |
| Auth | JWT with RS256, short-lived (15min access, 7d refresh) |
| Tenant Isolation | Application-layer filtering + PostgreSQL RLS |
| Data at Rest | AES-256 encryption (managed by cloud provider) |
| Secrets | SealedSecrets for GitOps, Vault for dynamic secrets |
| API Security | Rate limiting, CORS, CSP headers, request size limits |
| Audit | Immutable audit log for all data mutations |
| PII | Encryption of PII fields at application level, masking in logs |

### 12. File Storage

**Storage Backend:** Supabase Storage / AWS S3

**Directory Structure (tenant-scoped):**
```
{tenant_id}/
  prescriptions/{patient_id}/{uuid}.pdf
  reports/{appointment_id}/{uuid}.pdf
  scans/{patient_id}/{uuid}.png
  avatars/{doctor_id}/{uuid}.jpg
```

## Out of Scope

1. **Telemedicine / Video Calls** — Not included in MVP. Separate service if added later.
2. **EHR/EMR Integration** — No direct integration with existing electronic health record systems. Data import/export via CSV/HL7 FHIR in a future phase.
3. **Mobile Native Apps** — Web-first PWA only. Native iOS/Android in future.
4. **Multi-Region Deployment** — Single-region initially. Multi-region in Phase 2.
5. **On-Premise Deployment** — Cloud-only (Kubernetes on cloud provider).
6. **Real-Time Collaboration** — No multi-user real-time editing of records.
7. **Voice/Phone Integration** — No Twilio voice or IVR. WhatsApp messaging only.

## Interfaces

### API Gateway External Endpoints

```
POST   /api/v1/auth/login               → Authenticate user, return JWT
POST   /api/v1/auth/refresh             → Refresh JWT
POST   /api/v1/auth/logout              → Invalidate session

GET    /api/v1/appointments             → List appointments (cursor paginated)
POST   /api/v1/appointments             → Create appointment
GET    /api/v1/appointments/{id}        → Get appointment details
PATCH  /api/v1/appointments/{id}        → Update appointment
DELETE /api/v1/appointments/{id}        → Soft-delete appointment

GET    /api/v1/patients                 → List patients
POST   /api/v1/patients                 → Register patient
GET    /api/v1/patients/{id}            → Get patient details
PATCH  /api/v1/patients/{id}            → Update patient

GET    /api/v1/doctors                  → List doctors (scoped to tenant)
GET    /api/v1/doctors/{id}/schedule    → Get doctor's availability

GET    /api/v1/ai/chat                  → SSE stream for AI agent chat
POST   /api/v1/ai/triage                → Submit triage intake
GET    /api/v1/ai/summary/{appointment_id} → Get AI-generated SOAP note

GET    /api/v1/billing/subscription     → Get current subscription
POST   /api/v1/billing/checkout         → Create Stripe checkout session
GET    /api/v1/billing/invoices         → List invoices

GET    /health           → Liveness check
GET    /health/ready     → Readiness check
```

### Event Schemas (Pydantic)

```python
class AppointmentCreatedEvent(BaseModel):
    event_type: Literal["appointment.created"]
    tenant_id: UUID
    appointment_id: UUID
    patient_id: UUID
    doctor_id: UUID
    slot_start: datetime
    slot_end: datetime
    status: str
    created_at: datetime

class PatientRegisteredEvent(BaseModel):
    event_type: Literal["patient.registered"]
    tenant_id: UUID
    patient_id: UUID
    name: str
    contact_email: str | None
    created_at: datetime
```

## Data Flow

### Flow 1: Patient Books Appointment (Happy Path)

```
Patient → Frontend → [1] POST /api/v1/appointments
  → API Gateway (validate JWT, extract tenant)
  → Appointment Service (create appointment, publish event)
  → Kafka: appointment.created
    → Notification Service (send confirmation email/WhatsApp)
    → AI Agent Service (log for follow-up scheduling)
  → Response: { appointment_id, status: "scheduled" }
  → Frontend (show confirmation)
```

### Flow 2: Patient Initiates AI Triage Chat

```
Patient → Frontend → [1] SSE GET /api/v1/ai/chat
  → API Gateway (validate JWT, extract tenant)
  → AI Agent Service (establish SSE connection)
  → TriageAgent (receive message, classify intent)
    → If booking intent: Handoff to BookingAgent
      → BookingAgent calls Appointment Service (via REST)
      → BookingAgent returns available slots
    → If symptoms: Collect symptoms via structured output
      → Return urgency assessment + recommended action
  → SSE stream response to frontend
  → Frontend renders streaming tokens
```

### Flow 3: Doctor Completes Appointment (Medical Summary)

```
Doctor → Frontend → [1] POST /api/v1/ai/summary
  → API Gateway → AI Agent Service
  → MedicalSummaryAgent
    → Parse doctor notes into structured SOAP format
    → Return { subjective, objective, assessment, plan }
  → Doctor reviews and approves
  → PATCH /api/v1/appointments/{id} (attach summary)
  → Kafka: report.generated
    → Patient Service (add to patient history)
```

## Error Handling

### Application Errors (RFC 9457)

All error responses follow RFC 9457 Problem Details format:

```json
{
  "type": "https://api.doctorai.example.com/errors/appointment-conflict",
  "title": "Appointment Time Conflict",
  "status": 409,
  "detail": "The requested time slot overlaps with an existing appointment for Dr. Smith.",
  "instance": "/api/v1/appointments",
  "errors": {
    "conflicting_appointment_id": "apt_123abc"
  }
}
```

### Error Categories

| HTTP Status | Category | Example |
|-------------|----------|---------|
| 400 | Validation Error | Invalid appointment time format |
| 401 | Authentication Error | Expired or invalid JWT |
| 403 | Authorization Error | User lacks permission for this action |
| 404 | Not Found | Patient ID doesn't exist |
| 409 | Conflict | Double-booking a time slot |
| 422 | Business Rule Violation | Can't cancel past appointment |
| 429 | Rate Limited | Too many requests from this tenant |
| 500 | Internal Error | Unhandled exception, database down |

### Resilience Patterns

- **Idempotency Keys** — POST endpoints accept `Idempotency-Key: <UUID>` header for safe retries
- **Retry with Backoff** — Kafka consumers use exponential backoff with dead-letter queues
- **Circuit Breaker** — Services calling external APIs (Stripe, OpenAI) have circuit breakers
- **Bulkhead** — Tenant-level isolation: one tenant's high load doesn't degrade others
- **Timeouts** — All external calls have timeouts (OpenAI: 30s, DB: 5s, internal: 3s)

## Testing

### Architecture Verification Tests

1. **Tenant Isolation Test** — Verify that tenant A cannot access tenant B's data at every layer (API, service, repository, RLS)
2. **Event Flow Test** — Verify that publishing `appointment.created` triggers correct downstream consumers
3. **Auth Flow Test** — Verify JWT authentication, refresh, and RBAC enforcement
4. **Rate Limiting Test** — Verify per-tenant rate limits are enforced independently
5. **Kafka Resilience Test** — Verify consumer resumes from last committed offset after crash

### Per-Service Tests

- Unit tests for repository and service layers (pytest, mock DB)
- Integration tests with test PostgreSQL + test Kafka
- API tests via `httpx.AsyncClient` against FastAPI TestClient
- Factory-based test data (`factory_boy`) with tenant-scoped fixtures

### AI Agent Tests

- Mock `Runner` and `ModelProvider` to test agent tool selection logic
- Test handoff routing with pre-recorded responses
- Test guardrail triggers with known abusive/PII inputs
- Test structured output parsing with malformed LLM responses

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Shared schema + RLS (not schema-per-tenant) | Cost-effective at projected scale (<1000 tenants), simpler operations, mature RLS in PostgreSQL | 2026-05 |
| FastAPI over Express/NestJS | Python-native for AI/ML ecosystem, async-first, auto-docs, Pydantic validation | 2026-05 |
| OpenAI Agents SDK over LangChain/LlamaIndex | Lightweight, native function tools, structured outputs, built-in handoffs — purpose-built for agent orchestration | 2026-05 |
| Kafka over RabbitMQ/SQS | Event streaming, replay, partitioning by tenant_id, strong ecosystem for healthcare event sourcing | 2026-05 |
| Next.js over pure SPA | SSR for SEO (landing pages), Server Components for data fetching, Server Actions for forms | 2026-05 |
| Pinecone over pgvector | Managed vector DB, no operational overhead, built for production scale | 2026-05 |
| Single API Gateway | Simplifies auth, rate limiting, and routing at MVP scale. Split into domain gateways if needed later. | 2026-05 |
| Hybrid risk-level HITL model | Low-risk auto-executes, medium-risk inline confirm, high-risk async approval queue. Balances UX speed with clinical safety. | 2026-05 |

---

*This spec is the foundation for all subsequent specs. Every service, database schema, API endpoint, and deployment configuration must conform to the architecture described here.*
