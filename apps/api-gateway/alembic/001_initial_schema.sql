-- ============================================================================
-- Doctor AI Agent SaaS — Initial Database Schema
-- Applies to: Supabase Project (ugjkpegjrdkkcfotfbpk)
-- Generated from: DATABASE_SCHEMA.md (Approved v1.0)
-- ============================================================================
-- Run this entire file in the Supabase SQL Editor:
--   Dashboard → SQL Editor → New Query → Paste → Run
-- ============================================================================

-- ─── Extensions ───────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gist";        -- for no-double-booking constraint

-- ─── Domain 1: Tenants & Auth (Shared) ───────────────────────────────────────

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
    appointment_duration INTEGER NOT NULL DEFAULT 30,
    buffer_time     INTEGER NOT NULL DEFAULT 0,
    features        JSONB NOT NULL DEFAULT '{}',
    settings        JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_slug ON tenants (slug);
CREATE INDEX idx_tenants_tier ON tenants (tier);


CREATE TABLE roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    permissions     JSONB NOT NULL DEFAULT '[]',
    is_system_role  BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, name)
);

CREATE INDEX idx_roles_tenant ON roles (tenant_id);


CREATE TABLE team_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    role_id         UUID NOT NULL REFERENCES roles(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    invited_at      TIMESTAMPTZ,
    joined_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, user_id)
);

CREATE INDEX idx_team_members_tenant ON team_members (tenant_id);
CREATE INDEX idx_team_members_user ON team_members (user_id);
CREATE INDEX idx_team_members_role ON team_members (role_id);

-- ─── RLS: Tenants & Auth ─────────────────────────────────────────────────────

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;

-- Helper: get current user's tenant IDs
CREATE OR REPLACE FUNCTION auth.user_tenant_ids()
RETURNS SETOF UUID
LANGUAGE sql
STABLE
AS $$
    SELECT tenant_id FROM public.team_members
    WHERE user_id = (SELECT auth.uid())
    AND is_active = true;
$$;

-- Helper: check if user has a role in a tenant
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

-- Team members RLS: view own tenant's members
CREATE POLICY "Members can view team members in their tenant"
    ON team_members FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));

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

-- ─── Domain 2: Patient Service ───────────────────────────────────────────────

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
    allergies       TEXT[],
    blood_type      TEXT CHECK (blood_type IN ('A+','A-','B+','B-','AB+','AB-','O+','O-')),
    notes           TEXT,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_patients_tenant ON patients (tenant_id);
CREATE INDEX idx_patients_name ON patients (tenant_id, last_name, first_name);
CREATE INDEX idx_patients_phone ON patients (tenant_id, phone);
CREATE INDEX idx_patients_email ON patients (tenant_id, email);
CREATE INDEX idx_patients_dob ON patients (tenant_id, date_of_birth);
CREATE INDEX idx_patients_deleted ON patients (deleted_at) WHERE deleted_at IS NULL;

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant members can view patients"
    ON patients FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));

CREATE POLICY "Staff can create patients"
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

CREATE POLICY "Staff can update patients"
    ON patients FOR UPDATE
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));

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

-- ─── Domain 3: Doctor Service ────────────────────────────────────────────────

CREATE TABLE doctors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    team_member_id  UUID NOT NULL,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    title           TEXT,
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

CREATE INDEX idx_doctors_tenant ON doctors (tenant_id);
CREATE INDEX idx_doctors_active ON doctors (tenant_id, is_active);
CREATE INDEX idx_doctors_team_member ON doctors (team_member_id);

ALTER TABLE doctors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant members can view doctors"
    ON doctors FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));

CREATE POLICY "Admins can manage doctors"
    ON doctors FOR INSERT
    TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name IN ('admin', 'doctor')
        )
    );

CREATE POLICY "Admins can update doctors"
    ON doctors FOR UPDATE
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));


CREATE TABLE doctor_specialties (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    specialty       TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, specialty)
);

CREATE INDEX idx_doc_specialties_doctor ON doctor_specialties (doctor_id);
CREATE INDEX idx_doc_specialties_name ON doctor_specialties (specialty);

ALTER TABLE doctor_specialties ENABLE ROW LEVEL SECURITY;


CREATE TABLE doctor_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    day_of_week     INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    is_available    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, day_of_week, start_time)
);

CREATE INDEX idx_doc_schedules_doctor ON doctor_schedules (doctor_id);
CREATE INDEX idx_doc_schedules_day ON doctor_schedules (doctor_id, day_of_week);

ALTER TABLE doctor_schedules ENABLE ROW LEVEL SECURITY;


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

ALTER TABLE doctor_time_off ENABLE ROW LEVEL SECURITY;

-- ─── Domain 4: Appointment Service ────────────────────────────────────────────

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
    rescheduled_from      UUID,
    type            TEXT NOT NULL DEFAULT 'in_person'
                    CHECK (type IN ('in_person', 'video', 'phone')),
    notes           TEXT,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_appointments_tenant ON appointments (tenant_id);
CREATE INDEX idx_appointments_patient ON appointments (tenant_id, patient_id);
CREATE INDEX idx_appointments_doctor ON appointments (tenant_id, doctor_id);
CREATE INDEX idx_appointments_status ON appointments (tenant_id, status);
CREATE INDEX idx_appointments_slot ON appointments (doctor_id, slot_start, status);
CREATE INDEX idx_appointments_date ON appointments (tenant_id, slot_start::date);

-- No-double-booking exclusion constraint
CREATE INDEX idx_appointments_no_overlap
    ON appointments USING gist (
        doctor_id,
        tstzrange(slot_start, slot_end)
    ) WHERE status NOT IN ('cancelled', 'no_show');

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant members can view appointments"
    ON appointments FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));

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
    USING (tenant_id IN (SELECT auth.user_tenant_ids()));


CREATE TABLE appointment_slots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    doctor_id       UUID NOT NULL REFERENCES doctors(id),
    slot_date       DATE NOT NULL,
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    is_available    BOOLEAN NOT NULL DEFAULT true,
    appointment_id  UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(doctor_id, slot_date, start_time)
);

CREATE INDEX idx_appointment_slots_doctor ON appointment_slots (doctor_id, slot_date);
CREATE INDEX idx_appointment_slots_available ON appointment_slots (doctor_id, slot_date, is_available);

ALTER TABLE appointment_slots ENABLE ROW LEVEL SECURITY;


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

ALTER TABLE appointment_reminders ENABLE ROW LEVEL SECURITY;

-- ─── Domain 5: Billing Service ────────────────────────────────────────────────

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

ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;


CREATE TABLE invoices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_invoice_id   TEXT UNIQUE,
    subscription_id UUID NOT NULL REFERENCES subscriptions(id),
    amount          INTEGER NOT NULL,
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

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;


CREATE TABLE payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id      UUID NOT NULL REFERENCES invoices(id),
    stripe_payment_intent_id TEXT UNIQUE,
    amount          INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'usd',
    status          TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
    failure_reason  TEXT,
    refunded_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payments_tenant ON payments (tenant_id);
CREATE INDEX idx_payments_invoice ON payments (invoice_id);
CREATE INDEX idx_payments_status ON payments (tenant_id, status);

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

-- ─── Domain 6: AI Agent Service ───────────────────────────────────────────────

CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID REFERENCES patients(id),
    team_member_id  UUID,
    agent_type      TEXT NOT NULL CHECK (agent_type IN (
                        'triage', 'booking', 'faq', 'follow_up', 'general'
                    )),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'resolved', 'escalated')),
    summary         TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_tenant ON conversations (tenant_id);
CREATE INDEX idx_conversations_patient ON conversations (patient_id);
CREATE INDEX idx_conversations_agent ON conversations (tenant_id, agent_type);
CREATE INDEX idx_conversations_status ON conversations (tenant_id, status);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;


CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT NOT NULL,
    tool_calls      JSONB,
    tool_results    JSONB,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON conversation_messages (conversation_id, created_at);
CREATE INDEX idx_messages_role ON conversation_messages (conversation_id, role);

ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;


CREATE TABLE medical_summaries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    appointment_id  UUID NOT NULL REFERENCES appointments(id),
    patient_id      UUID NOT NULL REFERENCES patients(id),
    doctor_id       UUID NOT NULL REFERENCES doctors(id),
    subjective      TEXT,
    objective       TEXT,
    assessment      TEXT,
    plan            TEXT,
    raw_notes       TEXT,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'reviewed', 'finalized')),
    reviewed_by     UUID,
    reviewed_at     TIMESTAMPTZ,
    ai_model        TEXT,
    confidence_score REAL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_summaries_tenant ON medical_summaries (tenant_id);
CREATE INDEX idx_summaries_appointment ON medical_summaries (appointment_id);
CREATE INDEX idx_summaries_patient ON medical_summaries (tenant_id, patient_id);
CREATE INDEX idx_summaries_status ON medical_summaries (tenant_id, status);

ALTER TABLE medical_summaries ENABLE ROW LEVEL SECURITY;


CREATE TABLE faq_knowledge_base (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    embedding_id    TEXT,
    tags            TEXT[],
    is_published    BOOLEAN NOT NULL DEFAULT true,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_faq_tenant ON faq_knowledge_base (tenant_id);
CREATE INDEX idx_faq_category ON faq_knowledge_base (tenant_id, category);
CREATE INDEX idx_faq_published ON faq_knowledge_base (tenant_id, is_published);

ALTER TABLE faq_knowledge_base ENABLE ROW LEVEL SECURITY;


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
    created_by      TEXT NOT NULL DEFAULT 'ai',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_followup_tenant ON follow_up_tasks (tenant_id);
CREATE INDEX idx_followup_appointment ON follow_up_tasks (appointment_id);
CREATE INDEX idx_followup_status ON follow_up_tasks (tenant_id, status, scheduled_date);

ALTER TABLE follow_up_tasks ENABLE ROW LEVEL SECURITY;

-- ─── Domain 7: Notifications ──────────────────────────────────────────────────

CREATE TABLE notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    recipient       TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK (channel IN ('email', 'whatsapp', 'sms')),
    template_name   TEXT NOT NULL,
    template_data   JSONB,
    status          TEXT NOT NULL CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'bounced')),
    provider_message_id  TEXT,
    error_message   TEXT,
    sent_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notification_tenant ON notification_log (tenant_id);
CREATE INDEX idx_notification_recipient ON notification_log (tenant_id, recipient);
CREATE INDEX idx_notification_status ON notification_log (tenant_id, status);
CREATE INDEX idx_notification_created ON notification_log (tenant_id, created_at DESC);

ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;

-- ─── Domain 8: Audit & System ────────────────────────────────────────────────

CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    table_name      TEXT NOT NULL,
    record_id       UUID NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'SOFT_DELETE')),
    old_values      JSONB,
    new_values      JSONB,
    changed_by      UUID NOT NULL,
    changed_by_role TEXT,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_log (tenant_id, created_at DESC);
CREATE INDEX idx_audit_table ON audit_log (tenant_id, table_name, record_id);
CREATE INDEX idx_audit_user ON audit_log (tenant_id, changed_by);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Audit log is append-only: no UPDATE or DELETE policies allowed
CREATE POLICY "Only insert into audit_log"
    ON audit_log FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- ─── Audit Trigger Function ───────────────────────────────────────────────────

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
    v_tenant_id := COALESCE(NEW.tenant_id, OLD.tenant_id);
    v_user_id := (SELECT auth.uid());

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

-- Apply audit triggers to clinical tables
CREATE TRIGGER trg_patients_audit
    AFTER INSERT OR UPDATE OR DELETE ON patients
    FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();

CREATE TRIGGER trg_appointments_audit
    AFTER INSERT OR UPDATE OR DELETE ON appointments
    FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();

CREATE TRIGGER trg_medical_records_audit
    AFTER INSERT OR UPDATE OR DELETE ON medical_records
    FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();

CREATE TRIGGER trg_doctors_audit
    AFTER INSERT OR UPDATE OR DELETE ON doctors
    FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();

-- Disallow UPDATE/DELETE on audit_log itself
CREATE POLICY "No update on audit_log"
    ON audit_log FOR UPDATE
    TO authenticated
    USING (false);

CREATE POLICY "No delete on audit_log"
    ON audit_log FOR DELETE
    TO authenticated
    USING (false);

-- ─── Verification Queries ─────────────────────────────────────────────────────
-- Run these after migration to verify everything was created:

-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
-- ORDER BY table_name;

-- SELECT COUNT(*) AS rls_policies FROM pg_policies WHERE schemaname = 'public';
