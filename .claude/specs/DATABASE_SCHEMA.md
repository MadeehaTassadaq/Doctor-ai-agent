# SPEC: Database Schema

## Status
**Approved**

## Context

This document defines the complete database schema for the Doctor AI Agent SaaS platform. It covers all tables, relationships, indexes, Row-Level Security (RLS) policies, audit triggers, and migration strategy across every service domain.

This schema is designed for **multi-tenant isolation** (shared schema + `tenant_id` column + PostgreSQL RLS), **soft deletes** for clinical data, **audit logging** for HIPAA-inspired compliance, and **async-first** access via SQLAlchemy 2.0.

## Requirements

1. **Tenant Isolation** — Every tenant-scoped table has a `tenant_id` column. RLS policies prevent cross-tenant access.
2. **Soft Deletes** — All clinical data uses `deleted_at` timestamps. Hard deletes are never performed on patient data.
3. **Audit Trail** — Every INSERT, UPDATE, and DELETE on clinical tables is recorded in an immutable audit log.
4. **UUID Primary Keys** — All tables use UUID v4 primary keys to prevent enumeration and support distributed ID generation.
5. **Timestamps** — Every table has `created_at` and `updated_at`. Clinical tables also have `deleted_at`.
6. **Indexed Foreign Keys** — Every FK column and every `tenant_id` column is indexed for query performance.
7. **RLS Enforcement** — RLS policies use the `tenants` join pattern + JWT claims for tenant-scoped access.
8. **Alembic Migrations** — All schema changes are managed via Alembic auto-generated migrations, reviewed manually.
9. **Eventual Consistency** — Cross-service data consistency is handled via Kafka events, not DB foreign keys across service boundaries.

## Schema Domains

The schema is organized into 7 domains, each owned by a microservice. Services NEVER directly access another service's tables — they communicate via Kafka events or REST APIs.

```
┌─────────────────────────────────────────────────────────────┐
│                    Shared / Cross-Cutting                     │
│  tenants │ audit_logs │ team_members │ roles                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Patient Service     │  Doctor Service    │ Appointment Svc   │
│  ───────────────     │  ─────────────     │ ─────────────     │
│  patients            │  doctors           │ appointments       │
│  medical_records     │  doctor_schedules  │ appointment_slots  │
│  triage_forms        │  doctor_specialties│ appointment_reminders
│                      │                    │                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  AI Agent Service    │  Billing Service   │ Notification Svc  │
│  ───────────────     │  ─────────────     │ ─────────────     │
│  conversations       │  subscriptions     │ notification_log   │
│  conversation_msgs   │  invoices          │                    │
│  medical_summaries   │  payments          │                    │
│  faq_knowledge_base  │                    │                    │
├─────────────────────────────────────────────────────────────┤
│                    Pinecone Vector DB                         │
│  medical_kb_embeddings (index)                                │
└─────────────────────────────────────────────────────────────┘
```

## Table Definitions

---

### Domain 1: Tenants & Auth (Shared)

#### `tenants`

The core tenant record. Each row = one clinic/hospital. All tenant-scoped tables reference this.

```sql
CREATE TABLE tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    tier            TEXT NOT NULL DEFAULT 'free'
                    CHECK (tier IN ('free', 'pro', 'enterprise')),
    logo_url        TEXT,
    phone           TEXT,
    address         TEXT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    working_days    TEXT[] NOT NULL DEFAULT ARRAY['Mon','Tue','Wed','Thu','Fri'],
    open_time       TIME NOT NULL DEFAULT '09:00',
    close_time      TIME NOT NULL DEFAULT '17:00',
    appointment_duration INTEGER NOT NULL DEFAULT 30,  -- minutes
    buffer_time     INTEGER NOT NULL DEFAULT 0,         -- minutes between slots
    features        JSONB NOT NULL DEFAULT '{}',         -- feature flags per tier
    settings        JSONB NOT NULL DEFAULT '{}',         -- clinic-specific config
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_tenants_slug ON tenants (slug);
CREATE INDEX idx_tenants_tier ON tenants (tier);
```

**RLS:** No RLS on tenants table itself (used for authentication lookup). Access controlled at application layer.

---

#### `roles`

Predefined roles within a tenant. Every tenant gets the same default roles on creation.

```sql
CREATE TABLE roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    permissions     JSONB NOT NULL DEFAULT '[]',     -- array of permission strings
    is_system_role  BOOLEAN NOT NULL DEFAULT false,  -- system roles can't be deleted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, name)
);

-- Index
CREATE INDEX idx_roles_tenant ON roles (tenant_id);
```

**Default roles (created per tenant on signup):**
- `admin` — full access
- `doctor` — appointments, patient records, medical summaries
- `receptionist` — appointments, patient registration, basic patient data
- `viewer` — read-only access to appointments and schedules

---

#### `team_members`

Links auth users to tenants with a role. A user can belong to multiple tenants (e.g., a doctor working at two clinics).

```sql
CREATE TABLE team_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,                    -- auth.users.id (Supabase Auth)
    role_id         UUID NOT NULL REFERENCES roles(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    invited_at      TIMESTAMPTZ,
    joined_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, user_id)
);

-- Indexes
CREATE INDEX idx_team_members_tenant ON team_members (tenant_id);
CREATE INDEX idx_team_members_user ON team_members (user_id);
CREATE INDEX idx_team_members_role ON team_members (role_id);
```

**RLS Policies:**

```sql
-- Members can view their own tenant's members
CREATE POLICY "Members can view team members in their tenant"
    ON team_members FOR SELECT
    TO authenticated
    USING (tenant_id IN (
        SELECT tenant_id FROM team_members WHERE user_id = (SELECT auth.uid())
    ));

-- Admins can manage team members
CREATE POLICY "Admins can insert team members"
    ON team_members FOR INSERT
    TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name = 'admin'
        )
    );

CREATE POLICY "Admins can update team members"
    ON team_members FOR UPDATE
    TO authenticated
    USING (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name = 'admin'
        )
    );
```

---

### Domain 2: Patient Service

#### `patients`

```sql
CREATE TABLE patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    date_of_birth   DATE,
    gender          TEXT CHECK (gender IN ('male', 'female', 'other', 'prefer_not_to_say')),
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    emergency_contact_name    TEXT,
    emergency_contact_phone   TEXT,
    health_card_number       TEXT,
    insurance_provider       TEXT,
    insurance_policy_number  TEXT,
    allergies       TEXT[],                         -- array of allergy descriptions
    blood_type      TEXT CHECK (blood_type IN ('A+','A-','B+','B-','AB+','AB-','O+','O-')),
    notes           TEXT,
    created_by      UUID NOT NULL,                  -- team_members.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ                     -- soft delete
);

-- Indexes
CREATE INDEX idx_patients_tenant ON patients (tenant_id);
CREATE INDEX idx_patients_name ON patients (tenant_id, last_name, first_name);
CREATE INDEX idx_patients_phone ON patients (tenant_id, phone);
CREATE INDEX idx_patients_email ON patients (tenant_id, email);
CREATE INDEX idx_patients_dob ON patients (tenant_id, date_of_birth);
CREATE INDEX idx_patients_deleted ON patients (deleted_at) WHERE deleted_at IS NULL;
```

**RLS:**

```sql
CREATE POLICY "Tenant members can view patients"
    ON patients FOR SELECT
    TO authenticated
    USING (tenant_id IN (
        SELECT tenant_id FROM team_members WHERE user_id = (SELECT auth.uid())
    ));

CREATE POLICY "Doctors and admins can create patients"
    ON patients FOR INSERT
    TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name IN ('admin', 'doctor', 'receptionist')
        )
    );

CREATE POLICY "Doctors and admins can update patients"
    ON patients FOR UPDATE
    TO authenticated
    USING (tenant_id IN (
        SELECT tenant_id FROM team_members WHERE user_id = (SELECT auth.uid())
    ));

-- Soft delete: only admins
CREATE POLICY "Admins can soft-delete patients"
    ON patients FOR UPDATE
    TO authenticated
    USING (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name = 'admin'
        )
    );
```

---

#### `medical_records`

Clinical notes, diagnoses, and treatments linked to a patient and optionally to an appointment.

```sql
CREATE TABLE medical_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    appointment_id  UUID,                            -- nullable: can add record outside appointment
    record_type     TEXT NOT NULL DEFAULT 'note'
                    CHECK (record_type IN ('note', 'diagnosis', 'lab_result', 'prescription', 'imaging')),
    title           TEXT NOT NULL,
    description     TEXT,
    diagnosis       TEXT,
    prescription    JSONB,                           -- structured prescription data
    attachments     JSONB DEFAULT '[]',               -- array of { file_url, file_type, uploaded_at }
    created_by      UUID NOT NULL,                    -- team_members.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_medical_records_tenant ON medical_records (tenant_id);
CREATE INDEX idx_medical_records_patient ON medical_records (tenant_id, patient_id);
CREATE INDEX idx_medical_records_appointment ON medical_records (appointment_id);
CREATE INDEX idx_medical_records_type ON medical_records (tenant_id, record_type);
CREATE INDEX idx_medical_records_created ON medical_records (tenant_id, created_at DESC);
```

**RLS:** Same tenant-scoped pattern as `patients`. Only `admin` and `doctor` roles can INSERT/UPDATE.

---

#### `triage_forms`

Pre-appointment triage intake forms submitted by patients.

```sql
CREATE TABLE triage_forms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID REFERENCES patients(id),   -- nullable for walk-in/new patients
    appointment_id  UUID,                            -- linked after booking
    symptoms        JSONB NOT NULL,                   -- structured symptom data
    urgency_level   TEXT CHECK (urgency_level IN ('low', 'medium', 'high', 'emergency')),
    pain_level      INTEGER CHECK (pain_level >= 0 AND pain_level <= 10),
    duration_days   INTEGER,
    has_fever       BOOLEAN,
    existing_conditions  TEXT[],
    medications     TEXT[],
    notes           TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed', 'actioned')),
    reviewed_by     UUID,                            -- team_members.id (doctor who reviewed)
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_triage_tenant ON triage_forms (tenant_id);
CREATE INDEX idx_triage_patient ON triage_forms (patient_id);
CREATE INDEX idx_triage_urgency ON triage_forms (tenant_id, urgency_level);
CREATE INDEX idx_triage_status ON triage_forms (tenant_id, status);
```

---

### Domain 3: Doctor Service

#### `doctors`

Doctor profiles extending the auth user with clinical information.

```sql
CREATE TABLE doctors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    team_member_id  UUID NOT NULL,                    -- references team_members.id
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    title           TEXT,                              -- Dr., Prof., etc.
    license_number  TEXT,
    bio             TEXT,
    profile_image_url TEXT,
    phone           TEXT,
    email           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_doctors_tenant ON doctors (tenant_id);
CREATE INDEX idx_doctors_active ON doctors (tenant_id, is_active);
CREATE INDEX idx_doctors_team_member ON doctors (team_member_id);
```

---

#### `doctor_specialties`

Many-to-many: doctors ↔ specialties.

```sql
CREATE TABLE doctor_specialties (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    specialty       TEXT NOT NULL,                     -- e.g., 'Cardiology', 'Pediatrics'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, specialty)
);

CREATE INDEX idx_doc_specialties_doctor ON doctor_specialties (doctor_id);
CREATE INDEX idx_doc_specialties_name ON doctor_specialties (specialty);
```

---

#### `doctor_schedules`

Recurring weekly availability pattern for each doctor.

```sql
CREATE TABLE doctor_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    day_of_week     INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Sun
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    is_available    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, day_of_week, start_time)
);

CREATE INDEX idx_doc_schedules_doctor ON doctor_schedules (doctor_id);
CREATE INDEX idx_doc_schedules_day ON doctor_schedules (doctor_id, day_of_week);
```

---

#### `doctor_time_off`

Specific date ranges when a doctor is unavailable (vacation, conference, sick day).

```sql
CREATE TABLE doctor_time_off (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    reason          TEXT,
    is_approved     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_date_range CHECK (end_date >= start_date)
);

CREATE INDEX idx_doc_timeoff_doctor ON doctor_time_off (doctor_id);
CREATE INDEX idx_doc_timeoff_dates ON doctor_time_off (doctor_id, start_date, end_date);
```

---

### Domain 4: Appointment Service

#### `appointments`

```sql
CREATE TABLE appointments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID NOT NULL REFERENCES patients(id),
    doctor_id       UUID NOT NULL REFERENCES doctors(id),
    slot_start      TIMESTAMPTZ NOT NULL,
    slot_end        TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'scheduled'
                    CHECK (status IN (
                        'scheduled', 'confirmed', 'in_progress',
                        'completed', 'cancelled', 'no_show', 'rescheduled'
                    )),
    cancellation_reason   TEXT,
    rescheduled_from      UUID,                        -- previous appointment if rescheduled
    type            TEXT NOT NULL DEFAULT 'in_person'
                    CHECK (type IN ('in_person', 'video', 'phone')),
    notes           TEXT,
    created_by      UUID NOT NULL,                     -- team_members.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_appointments_tenant ON appointments (tenant_id);
CREATE INDEX idx_appointments_patient ON appointments (tenant_id, patient_id);
CREATE INDEX idx_appointments_doctor ON appointments (tenant_id, doctor_id);
CREATE INDEX idx_appointments_status ON appointments (tenant_id, status);
CREATE INDEX idx_appointments_slot ON appointments (doctor_id, slot_start, status);
CREATE INDEX idx_appointments_date ON appointments (tenant_id, slot_start::date);
```

**Constraint — no double-booking:**
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE INDEX idx_appointments_no_overlap
    ON appointments USING gist (
        doctor_id,
        tstzrange(slot_start, slot_end)
    ) WHERE status NOT IN ('cancelled', 'no_show');
```

**RLS:**

```sql
CREATE POLICY "Tenant members can view appointments"
    ON appointments FOR SELECT
    TO authenticated
    USING (tenant_id IN (
        SELECT tenant_id FROM team_members WHERE user_id = (SELECT auth.uid())
    ));

CREATE POLICY "Staff can create appointments"
    ON appointments FOR INSERT
    TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name IN ('admin', 'doctor', 'receptionist')
        )
    );

CREATE POLICY "Staff can update appointments"
    ON appointments FOR UPDATE
    TO authenticated
    USING (tenant_id IN (
        SELECT tenant_id FROM team_members WHERE user_id = (SELECT auth.uid())
    ));
```

---

#### `appointment_slots`

Pre-generated time slots for online booking. Generated from `doctor_schedules` + `doctor_time_off`.

```sql
CREATE TABLE appointment_slots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    doctor_id       UUID NOT NULL REFERENCES doctors(id),
    slot_date       DATE NOT NULL,
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    is_available    BOOLEAN NOT NULL DEFAULT true,
    appointment_id  UUID,                              -- set when booked
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, slot_date, start_time)
);

CREATE INDEX idx_appointment_slots_doctor ON appointment_slots (doctor_id, slot_date);
CREATE INDEX idx_appointment_slots_available ON appointment_slots (doctor_id, slot_date, is_available);
```

---

#### `appointment_reminders`

Tracks reminder status for each appointment.

```sql
CREATE TABLE appointment_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id  UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    reminder_type   TEXT NOT NULL CHECK (reminder_type IN ('email', 'whatsapp', 'sms')),
    scheduled_for   TIMESTAMPTZ NOT NULL,
    sent_at         TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed', 'cancelled')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reminders_appointment ON appointment_reminders (appointment_id);
CREATE INDEX idx_reminders_status ON appointment_reminders (status, scheduled_for)
    WHERE status = 'pending';
```

---

### Domain 5: Billing Service

#### `subscriptions`

Tracks each tenant's SaaS subscription.

```sql
CREATE TABLE subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_subscription_id  TEXT UNIQUE,
    stripe_customer_id      TEXT,
    plan_tier       TEXT NOT NULL CHECK (plan_tier IN ('free', 'pro', 'enterprise')),
    status          TEXT NOT NULL DEFAULT 'trialing'
                    CHECK (status IN ('trialing', 'active', 'past_due', 'canceled', 'incomplete')),
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    trial_end       TIMESTAMPTZ,
    canceled_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id)
);

CREATE INDEX idx_subscriptions_tenant ON subscriptions (tenant_id);
CREATE INDEX idx_subscriptions_stripe ON subscriptions (stripe_subscription_id);
CREATE INDEX idx_subscriptions_status ON subscriptions (status);
```

---

#### `invoices`

```sql
CREATE TABLE invoices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_invoice_id   TEXT UNIQUE,
    subscription_id UUID NOT NULL REFERENCES subscriptions(id),
    amount          INTEGER NOT NULL,                  -- cents
    currency        TEXT NOT NULL DEFAULT 'usd',
    status          TEXT NOT NULL CHECK (status IN ('draft', 'open', 'paid', 'uncollectible', 'void')),
    paid_at         TIMESTAMPTZ,
    pdf_url         TEXT,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_invoices_tenant ON invoices (tenant_id);
CREATE INDEX idx_invoices_subscription ON invoices (subscription_id);
CREATE INDEX idx_invoices_status ON invoices (tenant_id, status);
```

---

#### `payments`

```sql
CREATE TABLE payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id      UUID NOT NULL REFERENCES invoices(id),
    stripe_payment_intent_id TEXT UNIQUE,
    amount          INTEGER NOT NULL,                  -- cents
    currency        TEXT NOT NULL DEFAULT 'usd',
    status          TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
    failure_reason  TEXT,
    refunded_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payments_tenant ON payments (tenant_id);
CREATE INDEX idx_payments_invoice ON payments (invoice_id);
CREATE INDEX idx_payments_status ON payments (tenant_id, status);
```

---

### Domain 6: AI Agent Service

#### `conversations`

AI chat conversations between users and the AI agent system.

```sql
CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID REFERENCES patients(id),     -- nullable for staff conversations
    team_member_id  UUID,                              -- staff user if applicable
    agent_type      TEXT NOT NULL CHECK (agent_type IN (
                        'triage', 'booking', 'faq', 'follow_up', 'general'
                    )),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'resolved', 'escalated')),
    summary         TEXT,                              -- AI-generated conversation summary
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_tenant ON conversations (tenant_id);
CREATE INDEX idx_conversations_patient ON conversations (patient_id);
CREATE INDEX idx_conversations_agent ON conversations (tenant_id, agent_type);
CREATE INDEX idx_conversations_status ON conversations (tenant_id, status);
```

---

#### `conversation_messages`

Individual messages within a conversation.

```sql
CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT NOT NULL,
    tool_calls      JSONB,                             -- tool call data if role='tool'
    tool_results    JSONB,                             -- results if from a tool call
    metadata        JSONB DEFAULT '{}',                 -- token count, model, latency
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON conversation_messages (conversation_id, created_at);
CREATE INDEX idx_messages_role ON conversation_messages (conversation_id, role);
```

---

#### `medical_summaries`

AI-generated SOAP note summaries from doctor notes.

```sql
CREATE TABLE medical_summaries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    appointment_id  UUID NOT NULL REFERENCES appointments(id),
    patient_id      UUID NOT NULL REFERENCES patients(id),
    doctor_id       UUID NOT NULL REFERENCES doctors(id),
    -- SOAP fields
    subjective      TEXT,                              -- patient's reported symptoms
    objective       TEXT,                              -- observed signs, vitals
    assessment      TEXT,                              -- diagnosis / assessment
    plan            TEXT,                              -- treatment plan
    -- Metadata
    raw_notes       TEXT,                              -- original doctor dictation/notes
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'reviewed', 'finalized')),
    reviewed_by     UUID,                              -- doctor who reviewed/approved
    reviewed_at     TIMESTAMPTZ,
    ai_model        TEXT,                              -- model used for generation
    confidence_score REAL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_summaries_tenant ON medical_summaries (tenant_id);
CREATE INDEX idx_summaries_appointment ON medical_summaries (appointment_id);
CREATE INDEX idx_summaries_patient ON medical_summaries (tenant_id, patient_id);
CREATE INDEX idx_summaries_status ON medical_summaries (tenant_id, status);
```

---

#### `faq_knowledge_base`

Clinic-specific FAQ entries indexed for RAG retrieval. May also reference a shared medical knowledge base.

```sql
CREATE TABLE faq_knowledge_base (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,                     -- 'general', 'billing', 'hours', 'services'
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    embedding_id    TEXT,                              -- Pinecone vector ID
    tags            TEXT[],
    is_published    BOOLEAN NOT NULL DEFAULT true,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_faq_tenant ON faq_knowledge_base (tenant_id);
CREATE INDEX idx_faq_category ON faq_knowledge_base (tenant_id, category);
CREATE INDEX idx_faq_published ON faq_knowledge_base (tenant_id, is_published);
```

---

#### `follow_up_tasks`

AI-scheduled follow-ups after appointments.

```sql
CREATE TABLE follow_up_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    appointment_id  UUID NOT NULL REFERENCES appointments(id),
    patient_id      UUID NOT NULL REFERENCES patients(id),
    task_type       TEXT NOT NULL CHECK (task_type IN (
                        'medication_reminder', 'follow_up_visit',
                        'lab_result_check', 'general_checkin'
                    )),
    scheduled_date  DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'completed', 'skipped', 'cancelled')),
    notes           TEXT,
    completed_at    TIMESTAMPTZ,
    created_by      TEXT NOT NULL DEFAULT 'ai',        -- 'ai' or team_member UUID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_followup_tenant ON follow_up_tasks (tenant_id);
CREATE INDEX idx_followup_appointment ON follow_up_tasks (appointment_id);
CREATE INDEX idx_followup_status ON follow_up_tasks (tenant_id, status, scheduled_date);
```

---

### Domain 7: Notifications

#### `notification_log`

Immutable log of all sent notifications.

```sql
CREATE TABLE notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    recipient       TEXT NOT NULL,                     -- email address or phone number
    channel         TEXT NOT NULL CHECK (channel IN ('email', 'whatsapp', 'sms')),
    template_name   TEXT NOT NULL,                     -- 'appointment_confirmation', etc.
    template_data   JSONB,                             -- variables used in the template
    status          TEXT NOT NULL CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'bounced')),
    provider_message_id  TEXT,                         -- SendGrid/Twilio message ID
    error_message   TEXT,
    sent_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notification_tenant ON notification_log (tenant_id);
CREATE INDEX idx_notification_recipient ON notification_log (tenant_id, recipient);
CREATE INDEX idx_notification_status ON notification_log (tenant_id, status);
CREATE INDEX idx_notification_created ON notification_log (tenant_id, created_at DESC);
```

---

### Domain 8: Audit & System

#### `audit_log`

Immutable, append-only audit trail for all data mutations on clinical tables.

```sql
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    table_name      TEXT NOT NULL,
    record_id       UUID NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'SOFT_DELETE')),
    old_values      JSONB,                             -- previous row state (null for INSERT)
    new_values      JSONB,                             -- new row state (null for DELETE)
    changed_by      UUID NOT NULL,                     -- team_members.id
    changed_by_role TEXT,                               -- role at time of change
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partition by month for performance at scale
CREATE INDEX idx_audit_tenant ON audit_log (tenant_id, created_at DESC);
CREATE INDEX idx_audit_table ON audit_log (tenant_id, table_name, record_id);
CREATE INDEX idx_audit_user ON audit_log (tenant_id, changed_by);
```

**Note:** `audit_log` has **no UPDATE or DELETE policies** — it is append-only by design. Only INSERT is permitted.

---

## RLS Helper Functions

Shared helper functions used across RLS policies:

```sql
-- Get the current user's tenant IDs
CREATE OR REPLACE FUNCTION auth.user_tenant_ids()
RETURNS SETOF UUID
LANGUAGE sql
STABLE
AS $$
    SELECT tenant_id FROM public.team_members
    WHERE user_id = (SELECT auth.uid())
    AND is_active = true;
$$;

-- Check if the current user has a specific role in a tenant
CREATE OR REPLACE FUNCTION auth.user_has_role(p_tenant_id UUID, p_role_name TEXT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.team_members tm
        JOIN public.roles r ON tm.role_id = r.id
        WHERE tm.user_id = (SELECT auth.uid())
        AND tm.tenant_id = p_tenant_id
        AND r.name = p_role_name
        AND tm.is_active = true
    );
$$;

-- Enable RLS on all tenant-scoped tables (run per table)
-- ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
```

## Audit Trigger

PostgreSQL function + trigger for automatic audit logging. Applied to all clinical tables.

```sql
-- Master audit function
CREATE OR REPLACE FUNCTION public.trigger_audit_log()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_tenant_id UUID;
    v_user_id UUID;
    v_role_name TEXT;
BEGIN
    -- Extract tenant_id from the row (column must exist)
    v_tenant_id := COALESCE(NEW.tenant_id, OLD.tenant_id);
    v_user_id := (SELECT auth.uid());

    -- Get current user's role in this tenant
    SELECT r.name INTO v_role_name
    FROM public.team_members tm
    JOIN public.roles r ON tm.role_id = r.id
    WHERE tm.user_id = v_user_id
    AND tm.tenant_id = v_tenant_id
    LIMIT 1;

    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.audit_log (
            tenant_id, table_name, record_id, action,
            new_values, changed_by, changed_by_role
        ) VALUES (
            v_tenant_id, TG_TABLE_NAME, NEW.id, 'INSERT',
            row_to_json(NEW)::jsonb, v_user_id, v_role_name
        );
        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        -- Detect soft delete
        IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
            INSERT INTO public.audit_log (
                tenant_id, table_name, record_id, action,
                old_values, new_values, changed_by, changed_by_role
            ) VALUES (
                v_tenant_id, TG_TABLE_NAME, NEW.id, 'SOFT_DELETE',
                row_to_json(OLD)::jsonb, row_to_json(NEW)::jsonb,
                v_user_id, v_role_name
            );
        ELSE
            INSERT INTO public.audit_log (
                tenant_id, table_name, record_id, action,
                old_values, new_values, changed_by, changed_by_role
            ) VALUES (
                v_tenant_id, TG_TABLE_NAME, NEW.id, 'UPDATE',
                row_to_json(OLD)::jsonb, row_to_json(NEW)::jsonb,
                v_user_id, v_role_name
            );
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO public.audit_log (
            tenant_id, table_name, record_id, action,
            old_values, changed_by, changed_by_role
        ) VALUES (
            v_tenant_id, TG_TABLE_NAME, OLD.id, 'DELETE',
            row_to_json(OLD)::jsonb, v_user_id, v_role_name
        );
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$;

-- Apply trigger to clinical tables:
-- CREATE TRIGGER trg_patients_audit
--     AFTER INSERT OR UPDATE OR DELETE ON patients
--     FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();
--
-- CREATE TRIGGER trg_appointments_audit
--     AFTER INSERT OR UPDATE OR DELETE ON appointments
--     FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();
```

## Entity Relationship Summary

```
tenants 1──N team_members N──1 auth.users (via user_id)
tenants 1──N roles
tenants 1──N patients
tenants 1──N appointments
tenants 1──N doctors
tenants 1──N subscriptions
tenants 1──N conversations
tenants 1──N notification_log
tenants 1──N audit_log

doctors 1──N doctor_schedules
doctors 1──N doctor_time_off
doctors N──M doctor_specialties
doctors 1──N appointments

patients 1──N medical_records
patients 1──N appointments
patients 1──N triage_forms
patients 1──N conversations
patients 1──N follow_up_tasks

appointments 1──N appointment_reminders
appointments 1──1 medical_summaries
appointments 1──N follow_up_tasks

subscriptions 1──N invoices
invoices 1──N payments
```

## Pinecone Vector Index

**Index Name:** `medical-kb-{tenant_id}` (one namespace per tenant within the index, or separate indexes for isolation)

**Configuration:**
- Dimension: 1536 (OpenAI `text-embedding-3-small`)
- Metric: cosine similarity
- pod_type: serverless

**Indexed Content:**
- `faq_knowledge_base.answer` embeddings
- Clinic-specific medical documents (uploaded PDFs)
- Shared medical knowledge base (procedures, drug info, common diagnoses)

**Metadata stored with each vector:**
```json
{
  "tenant_id": "uuid",
  "source_table": "faq_knowledge_base",
  "source_id": "uuid",
  "category": "general|billing|hours|services",
  "tags": ["cardiology", "pediatrics"],
  "is_published": true
}
```

## Redis Cache Keys

Used for caching, rate limiting, and AI session state.

| Key Pattern | Value | TTL | Purpose |
|-------------|-------|-----|---------|
| `session:{tenant_id}:{conversation_id}` | Conversation state (JSON) | 24h | AI agent memory |
| `ratelimit:{tenant_id}:{endpoint}:{minute}` | Counter (int) | 60s | Rate limiting |
| `cache:tenant:{tenant_id}:settings` | Tenant settings (JSON) | 5min | Tenant config cache |
| `cache:doctor:{doctor_id}:availability` | Available slots (JSON) | 1min | Slot availability cache |
| `idempotency:{key}` | Response (JSON) | 24h | Idempotency key store |

## Migration Strategy

**Tool:** Alembic (auto-generate from SQLAlchemy model changes)

**Workflow:**
1. Developer modifies SQLAlchemy models in `models/` directory
2. Run `alembic revision --autogenerate -m "description"`
3. Review generated migration file manually
4. Test migration on development database
5. Run on staging, verify
6. Apply to production (zero-downtime using concurrent index creation)

**Zero-downtime rules:**
- Never rename columns directly — add new, backfill, drop old
- New NOT NULL columns must have a DEFAULT
- Index creation uses `CREATE INDEX CONCURRENTLY`
- Data migrations are separate from DDL migrations
- RLS policy changes are applied as separate migration steps

## Out of Scope

1. **Full-text search indexes** — Will be added per query pattern analysis in production.
2. **TimescaleDB hypertables** — Not needed until audit_log exceeds 100M rows.
3. **Database-per-tenant** — Not needed until >1000 tenants with regulatory requirements.
4. **Column-level encryption** — Application-layer encryption of PII fields added in Phase 2 if required.

## Testing

### Schema Tests (pytest + SQLAlchemy)

1. **All required tables exist** — Verify every table in this spec exists in the database.
2. **All RLS policies are enabled** — Query `pg_policies` and verify expected policies.
3. **Tenant isolation (positive)** — User in tenant A can read tenant A's patients.
4. **Tenant isolation (negative)** — User in tenant A cannot read tenant B's patients.
5. **Audit trigger fires** — INSERT into `patients` creates a row in `audit_log`.
6. **Soft delete works** — UPDATE `deleted_at` on patient logs SOFT_DELETE in audit_log.
7. **No double-booking** — Inserting overlapping appointments for same doctor raises constraint violation.
8. **Cascade deletes** — Deleting a tenant cascades to all child records.

### RLS Policy Tests (pgTAP)

```sql
-- Example pgTAP test
BEGIN;
SELECT plan(3);

-- Test: authenticated user can see patients in their tenant
SET LOCAL role TO authenticated;
SET LOCAL "request.jwt.claims" TO '{"sub": "test-user-id"}';

SELECT is(
    (SELECT COUNT(*) FROM patients WHERE tenant_id = 'tenant-a-uuid'),
    5::bigint,
    'User sees patients in their own tenant'
);

SELECT is(
    (SELECT COUNT(*) FROM patients WHERE tenant_id = 'tenant-b-uuid'),
    0::bigint,
    'User cannot see patients in other tenant'
);

ROLLBACK;
```

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| UUID primary keys over SERIAL | Distributed ID generation, no enumeration, safer for multi-service | 2026-05 |
| btree_gist exclusion constraint for appointments | Prevents double-booking at database level, not just application | 2026-05 |
| JSONB for flexible fields (symptoms, prescriptions, features) | Medical data is inherently semi-structured; JSONB avoids excessive join tables | 2026-05 |
| Separate `triage_forms` table (not column on appointments) | Triage can exist before an appointment is booked; supports walk-in patients | 2026-05 |
| Append-only audit_log (no UPDATE/DELETE) | Immutable audit trail is a compliance requirement; no way to tamper with logs | 2026-05 |
| `team_members` join pattern (not JWT-only for tenant context) | Supports users belonging to multiple tenants; role changes take effect immediately (unlike JWT claims) | 2026-05 |
| Pinecone over pgvector for FAQ vectors | Managed service, no operational overhead, serverless scaling, separate from primary DB | 2026-05 |

---

*This spec defines the complete data foundation. All services must use these tables as the source of truth for their domain. Cross-service data access is via Kafka events or REST APIs — never direct database access to another service's tables.*
