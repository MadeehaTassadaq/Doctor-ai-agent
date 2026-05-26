-- ============================================================================
-- Fix migration issues:
--   1. Create helper functions in `public` schema (auth schema not writable)
--   2. Add missing `medical_records` table
--   3. Fix RLS policies to use public helper functions
--   4. Fix index using date() function instead of ::
-- ============================================================================

-- ─── Fix 1: Helper functions in public schema ─────────────────────────────────

CREATE OR REPLACE FUNCTION public.user_tenant_ids()
RETURNS SETOF UUID
LANGUAGE sql
STABLE
AS $$
    SELECT tenant_id FROM public.team_members
    WHERE user_id = (SELECT auth.uid())
    AND is_active = true;
$$;

CREATE OR REPLACE FUNCTION public.user_has_role(p_tenant_id UUID, p_role_name TEXT)
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

-- ─── Fix 2: Drop failed RLS policies and recreate ─────────────────────────────

-- Team members (fix existing ones were created without the helper)
DROP POLICY IF EXISTS "Members can view team members in their tenant" ON team_members;
DROP POLICY IF EXISTS "Staff can create patients" ON patients;
DROP POLICY IF EXISTS "Staff can update patients" ON patients;
DROP POLICY IF EXISTS "Tenant members can view patients" ON patients;
DROP POLICY IF EXISTS "Admins can soft-delete patients" ON patients;
DROP POLICY IF EXISTS "Tenant members can view doctors" ON doctors;
DROP POLICY IF EXISTS "Admins can manage doctors" ON doctors;
DROP POLICY IF EXISTS "Admins can update doctors" ON doctors;
DROP POLICY IF EXISTS "Tenant members can view appointments" ON appointments;
DROP POLICY IF EXISTS "Staff can create appointments" ON appointments;
DROP POLICY IF EXISTS "Staff can update appointments" ON appointments;

-- Recreate all RLS policies using public helper
CREATE POLICY "Members can view team members in their tenant"
    ON team_members FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

CREATE POLICY "Tenant members can view patients"
    ON patients FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

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
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

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

CREATE POLICY "Tenant members can view doctors"
    ON doctors FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

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
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

CREATE POLICY "Tenant members can view appointments"
    ON appointments FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

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
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

-- ─── Fix 3: Fix index syntax ::date → date() ──────────────────────────────────

DROP INDEX IF EXISTS idx_appointments_date;
CREATE INDEX idx_appointments_date ON appointments (tenant_id, date(slot_start));

-- ─── Fix 4: Add missing medical_records table ─────────────────────────────────

CREATE TABLE medical_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    appointment_id  UUID,
    record_type     TEXT NOT NULL DEFAULT 'note'
                    CHECK (record_type IN ('note', 'diagnosis', 'lab_result', 'prescription', 'imaging')),
    title           TEXT NOT NULL,
    description     TEXT,
    diagnosis       TEXT,
    prescription    JSONB,
    attachments     JSONB DEFAULT '[]',
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_medical_records_tenant ON medical_records (tenant_id);
CREATE INDEX idx_medical_records_patient ON medical_records (tenant_id, patient_id);
CREATE INDEX idx_medical_records_appointment ON medical_records (appointment_id);
CREATE INDEX idx_medical_records_type ON medical_records (tenant_id, record_type);
CREATE INDEX idx_medical_records_created ON medical_records (tenant_id, created_at DESC);

ALTER TABLE medical_records ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant members can view medical records"
    ON medical_records FOR SELECT
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

CREATE POLICY "Doctors and admins can create medical records"
    ON medical_records FOR INSERT
    TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tm.tenant_id FROM team_members tm
            JOIN roles r ON tm.role_id = r.id
            WHERE tm.user_id = (SELECT auth.uid())
            AND r.name IN ('admin', 'doctor')
        )
    );

CREATE POLICY "Doctors and admins can update medical records"
    ON medical_records FOR UPDATE
    TO authenticated
    USING (tenant_id IN (SELECT public.user_tenant_ids()));

-- Add audit trigger for medical_records
CREATE TRIGGER trg_medical_records_audit
    AFTER INSERT OR UPDATE OR DELETE ON medical_records
    FOR EACH ROW EXECUTE FUNCTION public.trigger_audit_log();

-- ─── Verify ───────────────────────────────────────────────────────────────────

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;

SELECT COUNT(*) AS rls_policies_count FROM pg_policies WHERE schemaname = 'public';
