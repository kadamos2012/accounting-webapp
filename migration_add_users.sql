-- ============================================================
-- migration_add_users.sql
-- شغّليه فى Supabase -> SQL Editor -> Run (مرة واحدة بس، مش محتاجة
-- تعيدي تشغيل schema_postgres.sql كامل تانى - ده بس بيضيف الجداول
-- الجديدة اللي محتاجينها لنظام المستخدمين وسجل النشاط)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_log_username ON activity_log(username);
CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at);
