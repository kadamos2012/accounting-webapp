-- ============================================================
-- schema_postgres.sql
-- شغّلي الكود ده كامل فى Supabase -> SQL Editor -> New query -> Run
-- بيبني كل الجداول المطلوبة للنظام (نسخة PostgreSQL من قاعدة البيانات)
-- ============================================================

-- ============ جداول القوائم المرجعية ============
CREATE TABLE agents (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE airlines (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE visa_suppliers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE investment_suppliers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE partners (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    share_percentage REAL NOT NULL DEFAULT 0
);

-- ============ تعريف الباكدجات ============
CREATE TABLE package_definitions (
    id SERIAL PRIMARY KEY,
    package_code TEXT UNIQUE NOT NULL,
    includes_visa INTEGER NOT NULL DEFAULT 0,
    includes_investment INTEGER NOT NULL DEFAULT 0,
    includes_approval INTEGER NOT NULL DEFAULT 0,
    includes_ticket INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE package_rebooking_map (
    id SERIAL PRIMARY KEY,
    original_package TEXT NOT NULL,
    replacement_package TEXT NOT NULL
);

-- ============ جداول الأسعار والتكاليف ============
CREATE TABLE service_prices (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    package_code TEXT NOT NULL,
    component TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0
);

CREATE TABLE service_costs (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    package_code TEXT NOT NULL,
    component TEXT NOT NULL,
    category TEXT NOT NULL,
    cost REAL NOT NULL DEFAULT 0
);

CREATE TABLE ticket_prices (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    port TEXT NOT NULL,
    destination TEXT NOT NULL,
    price_adult REAL NOT NULL DEFAULT 0,
    price_female REAL NOT NULL DEFAULT 0,
    price_child REAL NOT NULL DEFAULT 0,
    price_infant REAL NOT NULL DEFAULT 0
);

CREATE TABLE ticket_costs (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    port TEXT NOT NULL,
    destination TEXT NOT NULL,
    airline TEXT NOT NULL,
    cost_adult REAL NOT NULL DEFAULT 0,
    cost_female REAL NOT NULL DEFAULT 0,
    cost_child REAL NOT NULL DEFAULT 0,
    cost_infant REAL NOT NULL DEFAULT 0
);

CREATE TABLE charter_bookings (
    id SERIAL PRIMARY KEY,
    flight_number TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    airline TEXT NOT NULL,
    total_cost REAL NOT NULL DEFAULT 0
);

CREATE TABLE investment_supplier_assignment (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    airline TEXT NOT NULL,
    supplier TEXT NOT NULL
);

-- ============ الجدول الرئيسي: المبيعات ============
CREATE TABLE sales (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    date_of_birth TEXT,
    national_id TEXT NOT NULL,
    passport_number TEXT,
    port TEXT,
    destination TEXT,
    flight_number TEXT,
    departure_date TEXT NOT NULL,
    submission_date TEXT NOT NULL,
    agent TEXT,
    investment_supplier TEXT,
    category TEXT,
    package_code TEXT NOT NULL,
    airline TEXT,

    service_price REAL DEFAULT 0,
    ticket_price REAL DEFAULT 0,
    total_sales REAL DEFAULT 0,

    visa_cost REAL DEFAULT 0,
    investment_cost REAL DEFAULT 0,
    approval_cost REAL DEFAULT 0,
    service_cost_total REAL DEFAULT 0,
    ticket_cost REAL DEFAULT 0,
    total_cost REAL DEFAULT 0,
    net_profit REAL DEFAULT 0,

    booking_status TEXT NOT NULL DEFAULT 'عادى',
    no_show_penalty REAL DEFAULT 0,
    linked_row_id INTEGER REFERENCES sales(id),

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sales_national_id ON sales(national_id);
CREATE INDEX idx_sales_agent ON sales(agent);
CREATE INDEX idx_sales_airline ON sales(airline);
CREATE INDEX idx_sales_investment_supplier ON sales(investment_supplier);
CREATE INDEX idx_sales_submission_date ON sales(submission_date);
CREATE INDEX idx_sales_departure_date ON sales(departure_date);
CREATE INDEX idx_sales_package_code ON sales(package_code);

-- ============ الخزنة ============
CREATE TABLE treasury (
    id SERIAL PRIMARY KEY,
    transaction_date TEXT NOT NULL,
    description TEXT,
    movement_type TEXT NOT NULL,
    party_name TEXT,
    payment_method TEXT,
    related_agent TEXT,
    related_partner TEXT,
    incoming REAL DEFAULT 0,
    outgoing REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_treasury_date ON treasury(transaction_date);
CREATE INDEX idx_treasury_party ON treasury(party_name);
CREATE INDEX idx_treasury_type ON treasury(movement_type);

-- ============ الأرصدة الافتتاحية ============
CREATE TABLE opening_balances_agents (
    agent_name TEXT PRIMARY KEY,
    gross_sales REAL DEFAULT 0,
    discount REAL DEFAULT 0,
    collected REAL DEFAULT 0
);

CREATE TABLE opening_balances_visa (
    supplier_name TEXT PRIMARY KEY,
    gross_purchases REAL DEFAULT 0,
    discount REAL DEFAULT 0,
    paid REAL DEFAULT 0
);

CREATE TABLE opening_balances_investment (
    supplier_name TEXT PRIMARY KEY,
    gross_purchases REAL DEFAULT 0,
    discount REAL DEFAULT 0,
    paid REAL DEFAULT 0
);

CREATE TABLE opening_balances_airlines (
    airline_name TEXT PRIMARY KEY,
    gross_revenue REAL DEFAULT 0,
    gross_cost REAL DEFAULT 0,
    discount REAL DEFAULT 0,
    paid REAL DEFAULT 0
);

-- ============ سعر البيع الإجمالى ============
CREATE TABLE total_sell_prices (
    id SERIAL PRIMARY KEY,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    package_code TEXT NOT NULL,
    port TEXT NOT NULL,
    destination TEXT NOT NULL,
    category TEXT NOT NULL,
    total_price REAL NOT NULL DEFAULT 0
);

CREATE INDEX idx_total_sell_lookup
    ON total_sell_prices(package_code, port, destination, category, date_from, date_to);

-- ============ سجل عمليات الاستيراد ============
CREATE TABLE import_log (
    id SERIAL PRIMARY KEY,
    import_date TIMESTAMP DEFAULT NOW(),
    source_file TEXT,
    rows_added INTEGER,
    rows_skipped INTEGER,
    performed_by TEXT,
    min_id INTEGER,
    max_id INTEGER
);

-- ============ المستخدمين وسجل النشاط ============
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_activity_log_username ON activity_log(username);
CREATE INDEX idx_activity_log_created ON activity_log(created_at);
