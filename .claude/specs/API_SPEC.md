# SPEC: API Specification

## Status
**Draft** — v0.1

## Context

This document defines the complete API contract for the Doctor AI Agent SaaS platform. Every microservice endpoint, request schema, response schema, error format, pagination convention, and routing rule is specified here.

The API is exposed through a single **API Gateway** (`apps/api-gateway`) which handles auth, rate limiting, and routing. All external clients (frontend, mobile, third-party integrations) talk to the gateway — never directly to services.

**Key principles:**
- RESTful conventions with cursor-based pagination
- All endpoints prefixed with `/api/v1/`
- Auth via `Authorization: Bearer <JWT>` (verified by gateway)
- Tenant context derived from JWT, injected as internal headers
- Error responses follow RFC 9457 Problem Details
- POST endpoints support `Idempotency-Key` header for safe retries

## Requirements

1. **Complete endpoint inventory** — Every REST endpoint across all 6 microservices must be specified with path, method, auth requirements, role permissions, request/response schemas, and error codes.
2. **Consistent pagination** — All list endpoints use cursor-based pagination with `limit` and `cursor` query parameters.
3. **Consistent error format** — Every error response follows RFC 9457 Problem Details.
4. **Gateway route map** — Clear mapping of URL prefixes to backend services.
5. **Service health endpoints** — Every service exposes `/health` (liveness) and `/health/ready` (readiness).
6. **Idempotency** — All POST endpoints support `Idempotency-Key` header.

## Design

### 1. Gateway Route Map

The API Gateway routes requests based on URL prefix:

| URL Prefix | Target Service | Port | Service Name |
|------------|---------------|------|--------------|
| `/api/v1/appointments` | Appointment Service | 8001 | `appointment-service` |
| `/api/v1/patients` | Patient Service | 8002 | `patient-service` |
| `/api/v1/doctors` | Doctor Service | 8003 | `doctor-service` |
| `/api/v1/billing` | Billing Service | 8004 | `billing-service` |
| `/api/v1/ai` | AI Agent Service | 8005 | `ai-agent-service` |
| `/api/v1/team` | API Gateway (inline) | 8000 | `api-gateway` |
| `/api/v1/auth` | API Gateway (inline) | 8000 | `api-gateway` |
| `/api/v1/internal` | API Gateway (inline) | 8000 | `api-gateway` |

Note: Notification Service (`8006`) has **no public REST endpoints** — it only consumes Kafka events and sends emails/WhatsApp/SMS.

### 2. Authentication & Authorization

**All endpoints** except health checks, docs, and the auth webhook require a valid JWT.

| Header | Value | Description |
|--------|-------|-------------|
| `Authorization` | `Bearer <jwt>` | Supabase JWT (verified by gateway) |
| `Idempotency-Key` | `<UUID>` | Optional. For safe POST retries (24h window) |
| `X-Request-ID` | `<UUID>` | Optional. For request tracing |

**Permission-to-endpoint mapping** (enforced at gateway):

| Permission String | Endpoint Pattern | Allowed Roles |
|------------------|------------------|---------------|
| `appointments:read` | `GET /api/v1/appointments` | admin, doctor, receptionist, viewer |
| `appointments:write` | `POST /api/v1/appointments` | admin, doctor, receptionist |
| `appointments:delete` | `DELETE /api/v1/appointments/{id}` | admin |
| `patients:read` | `GET /api/v1/patients` | admin, doctor, receptionist, viewer |
| `patients:write` | `POST /api/v1/patients` | admin, doctor, receptionist |
| `patients:clinical:read` | `GET /api/v1/patients/{id}/records` | admin, doctor |
| `patients:clinical:write` | `POST /api/v1/patients/{id}/records` | admin, doctor |
| `medical_summaries:write` | `POST /api/v1/ai/summary` | admin, doctor |
| `billing:read` | `GET /api/v1/billing/*` | admin |
| `billing:write` | `POST /api/v1/billing/*` | admin |
| `team:manage` | `POST /api/v1/team/*` | admin |
| `ai:chat` | `GET /api/v1/ai/chat/*` | admin, doctor, receptionist |

### 3. Pagination

All list endpoints use **cursor-based pagination**:

```
GET /api/v1/appointments?limit=20&cursor=eyJsYXN0X2lkIjogInV1aWQifQ==
```

**Request params:**
- `limit` — Max items per page (default: 20, max: 100)
- `cursor` — Base64-encoded JSON cursor from the previous response's `next_cursor`

**Response shape:**
```json
{
  "items": [...],
  "next_cursor": "eyJsYXN0X2lkIjogInV1aWQifQ==",
  "has_more": true
}
```

The cursor encodes `{ last_id: UUID, last_sort_value: any }` so the service can resume from where it left off.

### 4. Error Format (RFC 9457)

```json
{
  "type": "https://api.doctorai.com/errors/error-type",
  "title": "Human-Readable Title",
  "status": 400,
  "detail": "Specific details about this error instance.",
  "instance": "/api/v1/patients",
  "errors": {
    "field_name": ["validation error details"]
  }
}
```

**Error types:**

| HTTP | type URI | When |
|------|----------|------|
| 400 | `/errors/validation-error` | Request body validation failed |
| 401 | `/errors/missing-token` | No auth header |
| 401 | `/errors/invalid-token` | Expired or malformed JWT |
| 403 | `/errors/insufficient-permissions` | Role lacks required permission |
| 403 | `/errors/no-tenant` | JWT missing tenant_id |
| 404 | `/errors/not-found` | Resource doesn't exist |
| 409 | `/errors/appointment-conflict` | Double-booking a time slot |
| 409 | `/errors/resource-conflict` | Other conflict (duplicate, etc.) |
| 422 | `/errors/business-rule-violation` | Can't cancel past appointment, etc. |
| 429 | `/errors/rate-limited` | Rate limit exceeded |
| 502 | `/errors/upstream-error` | Backend service unreachable |
| 503 | `/errors/service-unavailable` | Rate limiter down (auth endpoints only) |

---

## 5. Patient Service (`/api/v1/patients` → `patient-service:8002`)

### 5.1 List Patients

```
GET /api/v1/patients?limit=20&cursor={cursor}&search={query}&status={status}
```

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Optional. Search by name, phone, email (ILIKE on first/last name, phone, email) |
| `limit` | integer | Max results (default 20, max 100) |
| `cursor` | string | Pagination cursor |

**Permissions:** `patients:read` (admin, doctor, receptionist, viewer)

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "first_name": "John",
      "last_name": "Doe",
      "date_of_birth": "1990-01-15",
      "gender": "male",
      "phone": "+1234567890",
      "email": "john@example.com",
      "address": "123 Main St",
      "emergency_contact_name": "Jane Doe",
      "emergency_contact_phone": "+1987654321",
      "health_card_number": "HCN-12345",
      "insurance_provider": "Blue Cross",
      "insurance_policy_number": "POL-98765",
      "allergies": ["Penicillin", "Peanuts"],
      "blood_type": "A+",
      "notes": "Patient prefers afternoon appointments",
      "created_by": "uuid",
      "created_at": "2026-05-24T10:00:00Z",
      "updated_at": "2026-05-24T10:00:00Z"
    }
  ],
  "next_cursor": "base64-encoded-cursor",
  "has_more": false
}
```

### 5.2 Create Patient

```
POST /api/v1/patients
```

**Permissions:** `patients:write` (admin, doctor, receptionist)

**Request body:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "date_of_birth": "1990-01-15",
  "gender": "male",
  "phone": "+1234567890",
  "email": "john@example.com",
  "address": "123 Main St",
  "emergency_contact_name": "Jane Doe",
  "emergency_contact_phone": "+1987654321",
  "health_card_number": "HCN-12345",
  "insurance_provider": "Blue Cross",
  "insurance_policy_number": "POL-98765",
  "allergies": ["Penicillin"],
  "blood_type": "A+",
  "notes": "Patient prefers afternoon appointments"
}
```

**Validation rules:**
- `first_name`, `last_name` — required, 1-100 chars
- `phone` — optional, E.164 format if provided
- `email` — optional, valid email format if provided
- `gender` — optional, one of: `male`, `female`, `other`, `prefer_not_to_say`
- `blood_type` — optional, one of: `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`
- `date_of_birth` — optional, must be in the past
- `allergies` — optional array of strings, max 50 items
- `health_card_number` — optional, unique per tenant

**Response `201`:**
```json
{
  "id": "uuid",
  "first_name": "John",
  "last_name": "Doe",
  "date_of_birth": "1990-01-15",
  "gender": "male",
  "phone": "+1234567890",
  "email": "john@example.com",
  "address": "123 Main St",
  "emergency_contact_name": "Jane Doe",
  "emergency_contact_phone": "+1987654321",
  "health_card_number": "HCN-12345",
  "insurance_provider": "Blue Cross",
  "insurance_policy_number": "POL-98765",
  "allergies": ["Penicillin"],
  "blood_type": "A+",
  "notes": "Patient prefers afternoon appointments",
  "created_by": "uuid",
  "created_at": "2026-05-24T10:00:00Z",
  "updated_at": "2026-05-24T10:00:00Z"
}
```

**Errors:**
| Status | Type | When |
|--------|------|------|
| 400 | validation-error | Invalid field values |
| 409 | resource-conflict | Duplicate health_card_number in tenant |

**Kafka event published:** `patient.registered`

### 5.3 Get Patient

```
GET /api/v1/patients/{id}
```

**Permissions:** `patients:read` (admin, doctor, receptionist, viewer)

**Response `200`:** Same shape as individual patient in list response.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Patient doesn't exist in this tenant |

### 5.4 Update Patient

```
PATCH /api/v1/patients/{id}
```

**Permissions:** `patients:write` (admin, doctor, receptionist)

**Request body:** Same fields as Create, all optional (partial update).

**Response `200`:** Full patient object after update.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Patient doesn't exist |
| 400 | validation-error | Invalid field values |

**Kafka event published:** `patient.updated`

### 5.5 Soft-Delete Patient

```
DELETE /api/v1/patients/{id}
```

**Permissions:** Only `admin` (checked at service level, not gateway).

**Notes:** Sets `deleted_at` timestamp. Patient data is never hard-deleted.

**Response `204`:** No content.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Patient doesn't exist |

### 5.6 List Medical Records

```
GET /api/v1/patients/{patient_id}/records?limit=20&cursor={cursor}&type={record_type}
```

**Permissions:** `patients:clinical:read` (admin, doctor)

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `type` | string | Optional filter: `note`, `diagnosis`, `lab_result`, `prescription`, `imaging` |
| `limit` | integer | Max results |
| `cursor` | string | Pagination cursor |

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "appointment_id": "uuid",
      "record_type": "diagnosis",
      "title": "Seasonal Allergies",
      "description": "Patient presents with typical seasonal allergy symptoms...",
      "diagnosis": "Allergic rhinitis (J30.9)",
      "prescription": {
        "medications": [
          {"name": "Cetirizine", "dosage": "10mg", "frequency": "once daily", "duration": "30 days"}
        ]
      },
      "attachments": [
        {"file_url": "https://storage.example.com/...", "file_type": "pdf", "uploaded_at": "2026-05-24T10:00:00Z"}
      ],
      "created_by": "uuid",
      "created_at": "2026-05-24T10:00:00Z",
      "updated_at": "2026-05-24T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

### 5.7 Create Medical Record

```
POST /api/v1/patients/{patient_id}/records
```

**Permissions:** `patients:clinical:write` (admin, doctor)

**Request body:**
```json
{
  "appointment_id": "uuid",
  "record_type": "diagnosis",
  "title": "Seasonal Allergies",
  "description": "Patient presents with typical seasonal allergy symptoms...",
  "diagnosis": "Allergic rhinitis (J30.9)",
  "prescription": {
    "medications": [
      {"name": "Cetirizine", "dosage": "10mg", "frequency": "once daily", "duration": "30 days"}
    ]
  },
  "attachments": []
}
```

**Validation rules:**
- `title` — required, 1-200 chars
- `record_type` — required, one of: `note`, `diagnosis`, `lab_result`, `prescription`, `imaging`
- `appointment_id` — optional, must reference an existing appointment in this tenant
- `prescription` — JSONB, validated at service layer for structure

**Response `201`:** Full medical record object.

---



## 6. Appointment Service (`/api/v1/appointments` → `appointment-service:8001`)

### 6.1 List Appointments

```
GET /api/v1/appointments?status={status}&doctor_id={uuid}&patient_id={uuid}&date_from={date}&date_to={date}&limit=20&cursor={cursor}
```

**Permissions:** `appointments:read` (admin, doctor, receptionist, viewer)

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter: `scheduled`, `confirmed`, `in_progress`, `completed`, `cancelled`, `no_show` |
| `doctor_id` | UUID | Filter by doctor |
| `patient_id` | UUID | Filter by patient |
| `date_from` | date | Start of date range (inclusive) |
| `date_to` | date | End of date range (inclusive) |
| `limit` | integer | Max results |
| `cursor` | string | Pagination cursor |

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "doctor_id": "uuid",
      "slot_start": "2026-05-25T14:00:00Z",
      "slot_end": "2026-05-25T14:30:00Z",
      "status": "scheduled",
      "type": "in_person",
      "cancellation_reason": null,
      "rescheduled_from": null,
      "notes": "Patient mentioned possible allergy symptoms",
      "created_by": "uuid",
      "created_at": "2026-05-20T10:00:00Z",
      "updated_at": "2026-05-20T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

**Filter behavior:**
- `status` — if omitted, returns all non-deleted appointments
- `doctor_id` / `patient_id` — if omitted, returns for all doctors/patients in tenant
- `date_from` / `date_to` — inclusive range on `slot_start`
- If tenant role is `doctor`, the service SHOULD additionally filter to only this doctor's appointments (defense-in-depth)

### 6.2 Create Appointment

```
POST /api/v1/appointments
```

**Permissions:** `appointments:write` (admin, doctor, receptionist)

**Request body:**
```json
{
  "patient_id": "uuid",
  "doctor_id": "uuid",
  "slot_start": "2026-05-25T14:00:00Z",
  "slot_end": "2026-05-25T14:30:00Z",
  "type": "in_person",
  "notes": "Patient mentioned possible allergy symptoms"
}
```

**Validation rules:**
- `patient_id` — required, must exist in this tenant
- `doctor_id` — required, must exist in this tenant and be active
- `slot_start` — required, must be in the future
- `slot_end` — required, must be after `slot_start`
- `type` — required, one of: `in_person`, `video`, `phone`
- No overlap with existing appointments for the same doctor (exclusion constraint)
- `slot_end - slot_start` must align with tenant's `appointment_duration` setting (allows ±5 min tolerance)

**Response `201`:**
```json
{
  "id": "uuid",
  "patient_id": "uuid",
  "doctor_id": "uuid",
  "slot_start": "2026-05-25T14:00:00Z",
  "slot_end": "2026-05-25T14:30:00Z",
  "status": "scheduled",
  "type": "in_person",
  "created_by": "uuid",
  "created_at": "2026-05-24T10:00:00Z",
  "updated_at": "2026-05-24T10:00:00Z"
}
```

**Errors:**
| Status | Type | When |
|--------|------|------|
| 400 | validation-error | Invalid data |
| 404 | not-found | patient_id or doctor_id doesn't exist |
| 409 | appointment-conflict | Time slot overlaps with existing appointment |
| 422 | business-rule-violation | slot_start in past, or duration mismatch |

**Kafka event published:** `appointment.created`

### 6.3 Get Appointment

```
GET /api/v1/appointments/{id}
```

**Permissions:** `appointments:read`

**Response `200`:** Full appointment object.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Appointment doesn't exist |

### 6.4 Update Appointment

```
PATCH /api/v1/appointments/{id}
```

**Permissions:** `appointments:write`

**Request body:** Partial update. Allowed fields:
- `status` — for status transitions (see below)
- `type` — appointment type
- `notes` — free text notes
- `cancellation_reason` — required if status = `cancelled`

**Status transition rules:**
```
scheduled ──► confirmed ──► in_progress ──► completed
    │                                              │
    ├──► cancelled                                  │
    └──► no_show ◄──────────────────────────────────┘
```
Illegal transitions should return 422.

**Response `200`:** Full appointment after update.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Appointment doesn't exist |
| 422 | business-rule-violation | Invalid status transition |
| 400 | validation-error | Missing cancellation_reason for cancelled |

**Kafka events published:**
- `appointment.cancelled` (when status → `cancelled`)
- `appointment.rescheduled` (when slot_start/slot_end changes — use cases: reschedule is a PATCH that changes time)
- No event published for other status changes

### 6.5 Cancel Appointment

```
DELETE /api/v1/appointments/{id}?reason={reason}
```

**Permissions:** `appointments:write` (admin, doctor, receptionist)

**Query param:**
| Param | Type | Description |
|-------|------|-------------|
| `reason` | string | Required. Reason for cancellation |

**Notes:** This is a soft-cancel — sets status to `cancelled` and records reason. Equivalent to PATCH status=cancelled but more explicit.

**Response `200`:**
```json
{
  "id": "uuid",
  "status": "cancelled",
  "cancellation_reason": "Patient requested cancellation"
}
```

**Kafka event published:** `appointment.cancelled`

### 6.6 Get Available Slots

```
GET /api/v1/appointments/slots?doctor_id={uuid}&date={date}
```

**Permissions:** `appointments:read`

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `doctor_id` | UUID | Required. Filter by doctor |
| `date` | date | Required. Get slots for this specific date |

**Response `200`:**
```json
{
  "doctor_id": "uuid",
  "date": "2026-05-25",
  "slots": [
    {"start": "09:00", "end": "09:30"},
    {"start": "09:30", "end": "10:00"},
    {"start": "10:00", "end": "10:30"},
    {"start": "11:00", "end": "11:30"}
  ]
}
```

Slots are computed from `doctor_schedules` (weekly recurring), minus `doctor_time_off`, minus already-booked appointments. Only future slots are returned.

### 6.7 Generate Slots

```
POST /api/v1/appointments/slots/generate?doctor_id={uuid}&date_from={date}&date_to={date}
```

**Permissions:** `appointments:write` (admin, receptionist)

**Notes:** Generates appointment slots for a date range based on the doctor's schedule. This is typically called when a doctor's schedule is updated or when initializing a new doctor.

**Response `200`:**
```json
{
  "doctor_id": "uuid",
  "date_from": "2026-05-25",
  "date_to": "2026-05-31",
  "slots_generated": 42
}
```

---

## 7. Doctor Service (`/api/v1/doctors` → `doctor-service:8003`)

### 7.1 List Doctors

```
GET /api/v1/doctors?is_active={bool}&specialty={text}&limit=20&cursor={cursor}
```

**Permissions:** `patients:read` (admin, doctor, receptionist, viewer)

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `is_active` | boolean | Optional. Filter by active status |
| `specialty` | string | Optional. Filter by specialty name |

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "team_member_id": "uuid",
      "first_name": "Jane",
      "last_name": "Smith",
      "title": "Dr.",
      "license_number": "LIC-12345",
      "bio": "Board-certified cardiologist with 15 years of experience.",
      "profile_image_url": "https://storage.example.com/...",
      "phone": "+1234567890",
      "email": "jane.smith@clinic.com",
      "specialties": ["Cardiology", "Internal Medicine"],
      "is_active": true,
      "created_at": "2026-05-24T10:00:00Z",
      "updated_at": "2026-05-24T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

The `specialties` field is a computed array from the `doctor_specialties` join table.

### 7.2 Get Doctor

```
GET /api/v1/doctors/{id}
```

**Permissions:** `patients:read`

**Response `200`:** Full doctor object with specialties array.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | Doctor doesn't exist in this tenant |

### 7.3 Create Doctor

```
POST /api/v1/doctors
```

**Permissions:** `team:manage` (admin)

**Request body:**
```json
{
  "team_member_id": "uuid",
  "first_name": "Jane",
  "last_name": "Smith",
  "title": "Dr.",
  "license_number": "LIC-12345",
  "bio": "Board-certified cardiologist.",
  "profile_image_url": "https://...",
  "phone": "+1234567890",
  "email": "jane.smith@clinic.com",
  "specialties": ["Cardiology", "Internal Medicine"]
}
```

**Validation rules:**
- `team_member_id` — required, must reference a valid team_member with role `doctor` or `admin`
- `license_number` — optional, unique per tenant
- `specialties` — optional array of strings, each 3-100 chars
- `phone` — optional, E.164 format

**Response `201`:** Full doctor object.

### 7.4 Update Doctor

```
PATCH /api/v1/doctors/{id}
```

**Permissions:** `team:manage` (admin)

**Request body:** Partial update of doctor fields + specialties.

**Response `200`:** Full doctor after update.

### 7.5 Get Doctor Schedule

```
GET /api/v1/doctors/{id}/schedule
```

**Permissions:** `appointments:read`

**Response `200`:**
```json
{
  "doctor_id": "uuid",
  "weekly_schedule": [
    {
      "day_of_week": 1,
      "day_name": "Monday",
      "start_time": "09:00",
      "end_time": "17:00",
      "is_available": true
    },
    {
      "day_of_week": 2,
      "day_name": "Tuesday",
      "start_time": "09:00",
      "end_time": "17:00",
      "is_available": true
    }
  ],
  "time_off": [
    {
      "id": "uuid",
      "start_date": "2026-06-01",
      "end_date": "2026-06-05",
      "reason": "Vacation",
      "is_approved": true
    }
  ]
}
```

### 7.6 Update Doctor Schedule

```
PATCH /api/v1/doctors/{id}/schedule
```

**Permissions:** `appointments:write` (admin, doctor)

**Request body:** Partial update — only send the days that change. Unspecified days remain unchanged.
```json
{
  "weekly_schedule": [
    {
      "day_of_week": 3,
      "start_time": "09:00",
      "end_time": "12:00",
      "is_available": true
    }
  ]
}
```

**Notes:** This is a partial merge — only the submitted days are updated. Existing schedule entries for non-submitted days are preserved. To mark a day as unavailable, set `is_available: false` rather than omitting it.

**Response `200`:** Full updated schedule (all days, including unchanged ones).

### 7.7 Add Time Off

```
POST /api/v1/doctors/{id}/time-off
```

**Permissions:** `appointments:write` (admin, doctor)

**Request body:**
```json
{
  "start_date": "2026-06-01",
  "end_date": "2026-06-05",
  "reason": "Vacation"
}
```

**Response `201`:**
```json
{
  "id": "uuid",
  "doctor_id": "uuid",
  "start_date": "2026-06-01",
  "end_date": "2026-06-05",
  "reason": "Vacation",
  "is_approved": false,
  "created_at": "2026-05-24T10:00:00Z"
}
```

Time off requires admin approval (`is_approved`). Unapproved time off still blocks slot generation but can be overridden.

### 7.8 Approve Time Off

```
PATCH /api/v1/doctors/{id}/time-off/{time_off_id}
```

**Permissions:** `team:manage` (admin)

**Request body:**
```json
{
  "is_approved": true
}
```

**Response `200`:** Updated time off record.

---

## 8. Billing Service (`/api/v1/billing` → `billing-service:8004`)

### 8.1 Get Current Subscription

```
GET /api/v1/billing/subscription
```

**Permissions:** `billing:read` (admin)

**Response `200`:**
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "plan_tier": "pro",
  "status": "active",
  "current_period_start": "2026-05-01T00:00:00Z",
  "current_period_end": "2026-06-01T00:00:00Z",
  "trial_end": null,
  "canceled_at": null,
  "created_at": "2026-04-15T00:00:00Z"
}
```

### 8.2 Create Checkout Session

```
POST /api/v1/billing/checkout
```

**Permissions:** `billing:write` (admin)

**Request body:**
```json
{
  "plan_tier": "pro",
  "success_url": "https://app.doctorai.com/dashboard/billing/success",
  "cancel_url": "https://app.doctorai.com/dashboard/billing/cancel"
}
```

**Response `201`:**
```json
{
  "checkout_url": "https://checkout.stripe.com/cs_...",
  "session_id": "cs_..."
}
```

### 8.3 List Invoices

```
GET /api/v1/billing/invoices?limit=20&cursor={cursor}
```

**Permissions:** `billing:read` (admin)

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "stripe_invoice_id": "in_...",
      "amount": 2900,
      "currency": "usd",
      "status": "paid",
      "paid_at": "2026-05-01T10:00:00Z",
      "pdf_url": "https://invoice.stripe.com/...",
      "period_start": "2026-05-01T00:00:00Z",
      "period_end": "2026-06-01T00:00:00Z",
      "created_at": "2026-05-01T00:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

### 8.4 Get Invoice

```
GET /api/v1/billing/invoices/{id}
```

**Permissions:** `billing:read` (admin)

**Response `200`:** Full invoice object.

### 8.5 Stripe Webhook

```
POST /api/v1/billing/webhook
```

**Permissions:** No auth (verified by Stripe signature). Must NOT go through the auth middleware.

**Notes:** This endpoint is registered as a public route in the gateway (bypassed from auth middleware) and handles Stripe events like `checkout.session.completed`, `invoice.paid`, `subscription.updated`.

**Events handled:**
| Stripe Event | Action |
|-------------|--------|
| `checkout.session.completed` | Activate subscription, update tenant tier |
| `invoice.paid` | Mark invoice as paid, create payment record |
| `invoice.payment_failed` | Mark invoice as open, update subscription status |
| `customer.subscription.updated` | Sync subscription status changes |
| `customer.subscription.deleted` | Downgrade to free tier |

**Response `200`:**
```json
{
  "received": true
}
```

---

## 9. AI Agent Service (`/api/v1/ai` → `ai-agent-service:8005`)

### 9.1 Chat via SSE

```
GET /api/v1/ai/chat/stream?conversation_id={uuid}
```

**Permissions:** `ai:chat` (admin, doctor, receptionist)

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `conversation_id` | UUID | Optional. Resume existing conversation. New one created if omitted. |
| `message` | string | Required. The user's message (URL-encoded) |

Wait — SSE is a GET connection that stays open. The actual message flow:

**Connection:**
```
GET /api/v1/ai/chat/stream?conversation_id={uuid}
```
Establishes an SSE connection. The conversation_id is the ongoing conversation. If omitted, a new conversation is created server-side.

**Sending a message:** After connection, the client sends messages via a companion endpoint:
```
POST /api/v1/ai/chat/message
{
  "conversation_id": "uuid",
  "message": "I need to reschedule my appointment"
}
```

**Receiving response:** On the SSE stream:
```
event: token
data: {"token": "I", "conversation_id": "uuid"}

event: token
data: {"token": " can", "conversation_id": "uuid"}

event: token
data: {"token": " help", "conversation_id": "uuid"}

event: done
data: {"conversation_id": "uuid", "agent_type": "booking", "requires_approval": true}

event: error
data: {"conversation_id": "uuid", "error": "Service unavailable"}
```

**SSE Event types:**
| Event | Data | When |
|-------|------|------|
| `token` | `{ token, conversation_id }` | Streaming text token |
| `tool_start` | `{ tool_name, conversation_id, arguments }` | Agent is about to call a tool |
| `tool_result` | `{ tool_name, conversation_id, result_summary }` | Tool call completed |
| `handoff` | `{ from_agent, to_agent, conversation_id }` | Agent handoff occurred |
| `approval_required` | `{ approval_id, action_type, details, conversation_id }` | Human-in-the-loop approval needed |
| `done` | `{ conversation_id, agent_type, requires_approval }` | Response complete |
| `error` | `{ conversation_id, error }` | Error during processing |

### 9.2 Send Chat Message

```
POST /api/v1/ai/chat/message
```

**Permissions:** `ai:chat`

**Request body:**
```json
{
  "conversation_id": "uuid",
  "message": "I need to reschedule my appointment for tomorrow"
}
```

**Validation:**
- `conversation_id` — required. If the conversation doesn't exist, create it
- `message` — required, 1-5000 chars

**Response `202`:**
```json
{
  "conversation_id": "uuid",
  "status": "processing"
}
```

The actual response arrives via the SSE stream (9.1).

### 9.3 Create Conversation

```
POST /api/v1/ai/chat/conversations
```

**Permissions:** `ai:chat`

**Request body:**
```json
{
  "patient_id": "uuid",
  "agent_type": "general"
}
```

**Agent types:**
- `general` — TriageAgent decides routing
- `triage` — Symptom collection and urgency assessment
- `booking` — Appointment booking assistant
- `faq` — Knowledge base Q&A
- `follow_up` — Follow-up scheduling

**Response `201`:**
```json
{
  "id": "uuid",
  "agent_type": "general",
  "status": "active",
  "created_at": "2026-05-24T10:00:00Z"
}
```

### 9.4 Get Conversations

```
GET /api/v1/ai/chat/conversations?status={status}&limit=20&cursor={cursor}
```

**Permissions:** `ai:chat`

**Response `200`:** Paginated list of conversations with last message preview.

### 9.5 Get Conversation Messages

```
GET /api/v1/ai/chat/conversations/{id}/messages?limit=50&cursor={cursor}
```

**Permissions:** `ai:chat`

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "role": "user",
      "content": "I need to reschedule my appointment",
      "tool_calls": null,
      "tool_results": null,
      "created_at": "2026-05-24T10:00:00Z"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "I can help you reschedule. Which appointment would you like to change?",
      "tool_calls": null,
      "created_at": "2026-05-24T10:00:01Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

### 9.6 Generate Medical Summary

```
POST /api/v1/ai/summary
```

**Permissions:** `medical_summaries:write` (admin, doctor)

**Request body:**
```json
{
  "appointment_id": "uuid",
  "patient_id": "uuid",
  "doctor_id": "uuid",
  "raw_notes": "Patient complains of persistent headache for 2 weeks. Pain is throbbing, located in temporal region. No vision changes. BP 120/80. Prescribed ibuprofen 400mg TID for 7 days. Follow up in 2 weeks if no improvement."
}
```

**Response `201`:**
```json
{
  "id": "uuid",
  "appointment_id": "uuid",
  "status": "draft",
  "subjective": "Patient reports persistent throbbing headache in temporal region for 2 weeks. No vision changes.",
  "objective": "BP: 120/80. No focal neurological deficits.",
  "assessment": "Tension-type headache (G44.209). Rule out migraine.",
  "plan": "Ibuprofen 400mg TID for 7 days. Follow up in 2 weeks if no improvement.",
  "confidence_score": 0.92,
  "created_at": "2026-05-24T10:00:00Z"
}
```

**Notes:** The summary is generated as a draft. A doctor must review and finalize it (PATCH to change status to `finalized`).

### 9.7 Update Medical Summary

```
PATCH /api/v1/ai/summary/{id}
```

**Permissions:** `medical_summaries:write` (admin, doctor)

**Request body:** Partial update. Key use case: doctor reviews and corrects the AI-generated summary.
```json
{
  "subjective": "Corrected subjective notes...",
  "assessment": "Corrected assessment...",
  "status": "finalized"
}
```

**Status transitions:**
```
draft ──► reviewed ──► finalized
```

**Response `200`:** Full summary after update.

### 9.8 Get Medical Summary

```
GET /api/v1/ai/summary/{id}
```
```
GET /api/v1/ai/summary?appointment_id={uuid}
```

**Permissions:** `patients:clinical:read` (admin, doctor)

**Response `200`:** Full medical summary.

### 9.9 List FAQ (Knowledge Base)

```
GET /api/v1/ai/faq?category={category}&search={query}&limit=20&cursor={cursor}
```

**Permissions:** `ai:chat`

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `category` | string | Filter: `general`, `billing`, `hours`, `services` |
| `search` | string | Full-text search on question and answer |

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "category": "hours",
      "question": "What are your opening hours?",
      "answer": "We are open Monday to Friday, 9 AM to 5 PM.",
      "tags": ["hours", "general"],
      "created_at": "2026-05-24T10:00:00Z",
      "updated_at": "2026-05-24T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

### 9.10 Create FAQ Entry

```
POST /api/v1/ai/faq
```

**Permissions:** `team:manage` (admin)

**Request body:**
```json
{
  "category": "hours",
  "question": "What are your opening hours?",
  "answer": "We are open Monday to Friday, 9 AM to 5 PM.",
  "tags": ["hours", "general"]
}
```

**Validation:**
- `category` — required, one of: `general`, `billing`, `hours`, `services`
- `question` — required, 5-500 chars
- `answer` — required, 10-5000 chars
- `tags` — optional array of strings, max 10 items

**Response `201`:** Full FAQ entry.

### 9.11 Update FAQ Entry

```
PATCH /api/v1/ai/faq/{id}
```

**Permissions:** `team:manage`

**Response `200`:** Updated FAQ entry.

### 9.12 Delete FAQ Entry

```
DELETE /api/v1/ai/faq/{id}
```

**Permissions:** `team:manage`

**Response `204`:** No content.

### 9.13 Create Triage Form

```
POST /api/v1/ai/triage
```

**Permissions:** `ai:chat` (admin, doctor, receptionist) — Triage is initiated by or with the assistance of the AI Triage Agent. Can be submitted by any authenticated team member on behalf of a patient.

**Request body:**
```json
{
  "patient_id": "uuid",
  "symptoms": [
    {"name": "Headache", "duration_days": 3, "severity": "moderate"},
    {"name": "Fever", "duration_days": 2, "severity": "mild"}
  ],
  "pain_level": 6,
  "duration_days": 3,
  "has_fever": true,
  "existing_conditions": ["Asthma"],
  "medications": ["Ventolin"],
  "notes": "Symptoms started after hiking trip"
}
```

**Response `201`:**
```json
{
  "id": "uuid",
  "patient_id": "uuid",
  "urgency_level": "medium",
  "status": "pending",
  "created_at": "2026-05-24T10:00:00Z"
}
```

The `urgency_level` is calculated server-side by the Triage Agent based on symptom severity, pain level, and duration.

**Errors:**
| Status | Type | When |
|--------|------|------|
| 404 | not-found | patient_id doesn't exist |
| 400 | validation-error | Invalid symptoms structure |

### 9.14 List Triage Forms

```
GET /api/v1/ai/triage?status={status}&urgency={urgency}&limit=20&cursor={cursor}
```

**Permissions:** `patients:clinical:read` (admin, doctor)

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter: `pending`, `reviewed`, `actioned` |
| `urgency` | string | Filter: `low`, `medium`, `high`, `emergency` |
| `limit` | integer | Max results |
| `cursor` | string | Pagination cursor |

**Response `200`:** Paginated list of triage forms.

---

## 10. Team Management (`/api/v1/team` → Gateway inline)

### 10.1 Invite Team Member

```
POST /api/v1/team/invite
```

**Permissions:** `team:manage` (admin, enforced at gateway via RBAC)

**Request body:**
```json
{
  "email": "newdoctor@clinic.com",
  "role": "doctor"
}
```

**Validation:**
- `email` — required, valid email
- `role` — required, one of: `admin`, `doctor`, `receptionist`, `viewer`

**Response `201`:**
```json
{
  "id": "uuid",
  "email": "newdoctor@clinic.com",
  "role": "doctor",
  "status": "invited",
  "invited_at": "2026-05-24T10:00:00Z"
}
```

**Flow:**
1. Admin creates invite → record in `team_members` with `is_active=false`, `invited_at` set
2. User signs up via Supabase Auth → webhook triggers → gateway checks for pending invite
3. If invite exists: activate `team_member`, set JWT `app_metadata`
4. If no invite: reject signup (invite-only mode)

### 10.2 List Team Members

```
GET /api/v1/team/members?limit=20&cursor={cursor}
```

**Permissions:** `team:manage`

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "email": "doctor@clinic.com",
      "role": "doctor",
      "is_active": true,
      "invited_at": "2026-05-20T10:00:00Z",
      "joined_at": "2026-05-21T10:00:00Z",
      "created_at": "2026-05-20T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

### 10.3 Update Team Member Role

```
PATCH /api/v1/team/members/{id}
```

**Permissions:** `team:manage` (admin)

**Request body:**
```json
{
  "role": "receptionist"
}
```

**Response `200`:** Updated team member.

---

## 11. Health Endpoints (Gateway inline)

### 11.1 Liveness

```
GET /health
```

**No auth required.**

**Response `200`:**
```json
{
  "status": "healthy"
}
```

### 11.2 Readiness

```
GET /health/ready
```

**No auth required.**

**Response `200` (all good):**
```json
{
  "status": "ready",
  "database": true,
  "redis": true
}
```

**Response `200` (degraded):**
```json
{
  "status": "degraded",
  "database": true,
  "redis": false
}
```

---

## 12. Service Health Endpoints (Per Service)

Every microservice exposes its own health endpoints (for Kubernetes probes). These are **not** routed through the gateway — K8s probes hit services directly.

```
GET /health        → Inline, returns {"status": "healthy"}
GET /health/ready  → Checks DB connection, returns {"status": "ready"|"degraded", "database": bool}
```

---

## 13. Auth Webhook (Gateway inline)

### 13.1 Supabase Auth Webhook

```
POST /api/v1/auth/webhook
```

**No auth** (HMAC signature verified). Must be excluded from auth middleware.

**Request:** Sent by Supabase Auth on `user.signup` event.

**Response `200`:**
```json
{
  "status": "ok",
  "tenant_id": "uuid",
  "message": "User activated successfully"
}
```

---

## 14. Internal Endpoints (Gateway inline)

### 14.1 Verify Internal Token

```
POST /api/v1/internal/verify
```

**Permissions:** Internal services only (validated via `X-Internal-Auth` header).

Used by services to validate requests coming through the gateway. For MVP, uses a shared internal token.

**Response `200`:**
```json
{
  "valid": true,
  "tenant_id": "uuid",
  "user_id": "uuid",
  "role": "doctor"
}
```

---

## 15. Kafka Events (Produced by Services)

| Event | Producer | Payload | When |
|-------|----------|---------|------|
| `appointment.created` | Appointment Service | `{ tenant_id, appointment_id, patient_id, doctor_id, slot_start, slot_end, status, created_at }` | New appointment created |
| `appointment.cancelled` | Appointment Service | `{ tenant_id, appointment_id, patient_id, doctor_id, slot_start, slot_end, reason, cancelled_at }` | Appointment cancelled |
| `appointment.rescheduled` | Appointment Service | `{ tenant_id, appointment_id, patient_id, doctor_id, old_slot_start, new_slot_start, new_slot_end, rescheduled_at }` | Appointment time changed |
| `patient.registered` | Patient Service | `{ tenant_id, patient_id, first_name, last_name, email, phone, created_at }` | New patient created |
| `patient.updated` | Patient Service | `{ tenant_id, patient_id, changed_fields: [...], updated_at }` | Patient profile updated |
| `payment.completed` | Billing Service | `{ tenant_id, invoice_id, payment_id, amount, currency, paid_at }` | Payment succeeded |
| `subscription.changed` | Billing Service | `{ tenant_id, old_tier, new_tier, changed_at }` | Plan tier changed |
| `report.generated` | AI Agent Service | `{ tenant_id, summary_id, appointment_id, patient_id, doctor_id, generated_at }` | Medical summary generated |
| `followup.scheduled` | AI Agent Service | `{ tenant_id, followup_id, patient_id, appointment_id, task_type, scheduled_date }` | Follow-up task created |
| `notification.send` | Any service | `{ tenant_id, recipient, channel, template_name, template_data }` | Send notification request |

## Out of Scope

1. **Real-time WebSocket endpoints** — Not needed for MVP. The SSE streaming for AI chat is sufficient.
2. **Bulk operations** — No batch create/update/delete endpoints. Each resource is CRUD'd individually.
3. **File upload endpoints** — File uploads go directly to Supabase Storage (presigned URLs). No gateway proxy needed.
4. **Export/import endpoints** — CSV/JSON export will be added in Phase 2.
5. **Admin-only supertenant endpoints** — Platform-wide admin console (view all tenants, etc.) is Phase 2.
6. **Webhook for appointment reminders** — Notification Service handles scheduling internally based on Kafka events, not via REST.
7. **Public patient-facing API** — Patient portal endpoints (booking without login) will be a separate spec if needed.

## Data Flow

### Flow: Book Appointment (Full End-to-End)

```
1. Receptionist → Frontend → POST /api/v1/appointments
   Auth: Bearer <receptionist-jwt>
   Body: { patient_id, doctor_id, slot_start, slot_end, type }

2. Gateway:
   a. Verify JWT, extract tenant_id=X, role=receptionist
   b. Check RBAC: POST /appointments requires appointments:write
   c. Check rate limit: rl:{tenant_id}:general
   d. Inject headers: X-Tenant-ID, X-User-ID, X-User-Role
   e. Proxy to http://appointment-service:8001/api/v1/appointments

3. Appointment Service:
   a. Extract tenant_id from X-Tenant-ID header
   b. Verify patient_id exists in this tenant — queries patients table (shared DB, patient_id FK on appointments)
   c. Verify doctor_id exists and is active — queries doctors table (shared DB, doctor_id FK on appointments)
   d. Check doctor availability for the requested slot:
      — Query doctor_schedules to verify the time falls within the doctor's weekly schedule
      — Query doctor_time_off to verify the date is not blocked
      — All availability checks happen within the same database (shared PostgreSQL schema)
   e. Validate slot_start is in future
   f. Check no overlapping appointment (exclusion constraint on doctor_id + tstzrange)
   g. INSERT appointment with tenant_id from header
   h. Publish Kafka event: appointment.created
   i. Return 201 with appointment

4. Gateway:
   a. Forward response to client
   b. Headers: X-Request-ID, X-RateLimit-Remaining: 299

5. Frontend:
   a. Show success confirmation
   b. X seconds later, patient receives email/WhatsApp (handled by Notification Service consuming Kafka)
```

### Flow: Patient AI Chat

```
1. Patient → Frontend → GET /api/v1/ai/chat/stream (establish SSE)
   Auth: Bearer <patient-jwt>

2. Gateway:
   a. Verify JWT, extract tenant_id
   b. Check RBAC: ai:chat
   c. Check rate limit: rl:{tenant_id}:ai_chat
   d. Proxy to http://ai-service:8005/api/v1/ai/chat/stream
   e. Stream response back to client (passthrough)

3. Client → POST /api/v1/ai/chat/message
   Body: { conversation_id, message: "I need to book an appointment" }

4. AI Agent Service:
   a. Receive message, establish conversation context
   b. TriageAgent: classify intent → booking
   c. Handoff to BookingAgent
   d. BookingAgent: tools.get_available_slots(doctor_id, date)
     → Calls GET /api/v1/doctors/{id}/schedule (internal REST)
   e. BookingAgent: propose slots to user
   f. User: selects slot
   g. BookingAgent: tools.create_appointment(patient_id, doctor_id, slot)
     → Calls POST /api/v1/appointments (internal REST with internal JWT)
   h. Human-in-the-loop check: medium risk → inline confirmation
   i. SSE: stream approval request to user
   j. User: confirms
   k. Appointment created, Kafka event published

5. SSE stream: done event sent
```

## Error Handling

### Service Unavailable (502)

Returned by the gateway when the target service is unreachable:

```json
{
  "type": "https://api.doctorai.com/errors/upstream-error",
  "title": "Service Unavailable",
  "status": 502,
  "detail": "The appointment service is temporarily unavailable. Please retry.",
  "instance": "/api/v1/appointments"
}
```

### Service-Specific Error Details

Each service must define its own error types within the RFC 9457 format. Examples:

```json
// Appointment conflict (409)
{
  "type": "https://api.doctorai.com/errors/appointment-conflict",
  "title": "Appointment Time Conflict",
  "status": 409,
  "detail": "The requested time slot overlaps with an existing appointment for this doctor.",
  "instance": "/api/v1/appointments",
  "conflicting_appointment_id": "uuid"
}

// Business rule violation (422)
{
  "type": "https://api.doctorai.com/errors/business-rule-violation",
  "title": "Invalid Status Transition",
  "status": 422,
  "detail": "Cannot transition appointment status from 'cancelled' to 'confirmed'.",
  "instance": "/api/v1/appointments/uuid",
  "current_status": "cancelled",
  "requested_status": "confirmed"
}
```

## Testing

### Gateway Routing Tests
1. Each URL prefix routes to the correct service
2. Catch-all returns 404 for unknown prefixes
3. SSE stream endpoint returns correct content-type

### Patient Service Tests
1. CRUD operations with valid data return correct status codes
2. Tenant isolation: tenant A cannot access tenant B's patients
3. Search by name/phone/email returns correct results
4. Soft delete sets `deleted_at` and excludes from list queries
5. Medical records scoped to parent patient

### Appointment Service Tests
1. Create appointment with valid data returns 201
2. Double-booking same doctor+time returns 409
3. Invalid status transition returns 422
4. Cancel sets correct status and publishes event
5. Available slots excludes time off and booked slots
6. Pagination works correctly with cursor

### Doctor Service Tests
1. GET schedule returns weekly pattern + time off
2. PUT schedule replaces entire weekly schedule
3. Time off creation and approval flow
4. Filter by specialty works correctly

### AI Agent Service Tests
1. SSE stream establishes and streams tokens
2. Send message queues processing and returns 202
3. Conversation CRUD operations
4. Medical summary generation creates draft
5. Summary status transitions (draft → reviewed → finalized)
6. FAQ CRUD operations with search

### Billing Service Tests
1. Get subscription returns current plan
2. Create checkout returns Stripe URL
3. List invoices with correct pagination
4. Stripe webhook signature verification
5. Invoice paid → subscription status updated

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Gateway catch-all proxy pattern | Single route `/api/v1/{service}/{path}` maps to backend services. No per-endpoint routes in gateway. Services own their routing. | 2026-05 |
| Cursor pagination over offset | Stable under data changes (inserts don't shift pages). More efficient for large datasets. | 2026-05 |
| SSE for AI chat instead of WebSocket | Simpler infrastructure (no WebSocket state management), HTTP/2 compatible, unidirectional streaming is sufficient for chat UX. | 2026-05 |
| Companion POST endpoint for SSE messages | SSE is receive-only from client perspective. A separate POST endpoint sends messages; SSE delivers responses. Clean separation of concerns. | 2026-05 |
| No public REST API for Notification Service | Notifications are event-driven. No REST endpoints needed. Email/WhatsApp/SMS templates and sending are triggered by Kafka consumers. | 2026-05 |
| Stripe webhook bypasses auth middleware | Stripe signs webhooks with its own signature scheme. Gateway must allow this route without JWT. Verified by Stripe SDK. | 2026-05 |
| PATCH for partial updates, PUT for full replacement | PATCH updates specific fields (schedule, profile). PUT replaces entire resource (weekly schedule). REST convention. | 2026-05 |
| Doctor schedule returns both weekly + time off in single response | Reduces API calls for the common use case (viewing a doctor's full availability). | 2026-05 |
| Triage form endpoint under `/patients/triage` | Triage belongs to patient domain. Keeping it in Patient Service avoids cross-service calls for patient data during triage. | 2026-05 |

---

*This spec defines the complete API contract. Every service implementation must conform to these endpoint definitions, schemas, error formats, and pagination conventions. The gateway route map is the source of truth for request routing.*
