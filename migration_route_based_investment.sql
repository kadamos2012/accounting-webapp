-- ============================================================
-- migration_route_based_investment.sql
-- شغّليه فى Supabase -> SQL Editor -> Run (مرة واحدة بس)
-- بيضيف إمكانية تحديد مورد الاستثمار بناءً على خط السير (منفذ+وجهة)
-- بالإضافة للطريقة الحالية (شركة الطيران) - الاتنين يفضلوا شغالين مع بعض.
-- الأولوية: شركة الطيران أولاً، وخط السير احتياطي لو مفيش تخصيص بالطيران.
-- ============================================================

ALTER TABLE investment_supplier_assignment ALTER COLUMN airline DROP NOT NULL;
ALTER TABLE investment_supplier_assignment ADD COLUMN IF NOT EXISTS port TEXT;
ALTER TABLE investment_supplier_assignment ADD COLUMN IF NOT EXISTS destination TEXT;
