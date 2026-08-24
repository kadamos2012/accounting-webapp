"""
recalculate_period.py - Re-runs the pricing/cost calculation for every
EXISTING client whose submission date falls within a chosen range, using
whatever prices/costs/package definitions are CURRENTLY in the database
(PostgreSQL / Supabase version).
"""
from pricing_engine import calculate_row
from db import get_connection


def recalculate(date_from, date_to, force=False):
    conn = get_connection()
    cur = conn.cursor()

    if not force:
        cur.execute("SELECT COALESCE(SUM(total_price), 0) FROM total_sell_prices")
        total_configured = cur.fetchone()[0]
        if total_configured == 0:
            conn.close()
            return {"updated": 0, "aborted": True,
                    "message": "جدول أسعار البيع فاضي بالكامل (كله أصفار). إعادة الحساب دلوقتي "
                               "هتصفّر سعر البيع لكل عميل فى الفترة دي. املأي الأسعار الحقيقية "
                               "الأول، أو لو قصدك تعيدي حساب التكلفة بس، فعّلي 'تجاوز التحذير'."}

    cur.execute("""
        SELECT id, name, date_of_birth, national_id, passport_number, port, destination,
               flight_number, departure_date, submission_date, agent, category, package_code
        FROM sales WHERE submission_date BETWEEN %s AND %s
    """, (date_from, date_to))
    rows = cur.fetchall()

    updated = 0
    for row in rows:
        (sale_id, name, dob, nid, passport, port, dest, flight, departure_date,
         submission_date, agent, category, package_code) = row
        recalculated = calculate_row(
            cur, name, dob, nid, passport, port, dest, flight, departure_date,
            submission_date, agent, category, package_code, row_already_in_db=True
        )
        cur.execute("""
            UPDATE sales SET
                service_price = %(service_price)s, ticket_price = %(ticket_price)s, total_sales = %(total_sales)s,
                visa_cost = %(visa_cost)s, investment_cost = %(investment_cost)s, approval_cost = %(approval_cost)s,
                service_cost_total = %(service_cost_total)s, ticket_cost = %(ticket_cost)s,
                total_cost = %(total_cost)s, net_profit = %(net_profit)s,
                airline = %(airline)s, investment_supplier = %(investment_supplier)s
            WHERE id = %(sale_id)s
        """, {**recalculated, "sale_id": sale_id})
        updated += 1

    conn.commit()
    conn.close()
    return {"updated": updated, "aborted": False}
