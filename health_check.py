"""
health_check.py - Scans the database for common data-integrity problems and
reports them clearly: zero prices, unknown packages, orphaned no-show
links, and reference-table gaps.
"""
from db import get_connection


def run_health_check():
    conn = get_connection()
    cur = conn.cursor()
    issues = []

    # 1) حجوزات بسعر بيع أو تكلفة صفر
    cur.execute("SELECT COUNT(*) FROM sales WHERE total_sales <= 0")
    zero_sales = cur.fetchone()[0]
    if zero_sales:
        issues.append(("Zero selling price", zero_sales,
                        "Bookings with total_sales = 0 - check total_sell_prices is filled in "
                        "for their package/route/category/date."))

    cur.execute("SELECT COUNT(*) FROM sales WHERE total_cost <= 0")
    zero_cost = cur.fetchone()[0]
    if zero_cost:
        issues.append(("Zero purchase cost", zero_cost,
                        "Bookings with total_cost = 0 - check service_costs/ticket_costs "
                        "are filled in."))

    # 2) باكدج مش موجود فى package_definitions
    cur.execute("""
        SELECT DISTINCT s.package_code, COUNT(*) FROM sales s
        LEFT JOIN package_definitions pd ON pd.package_code = s.package_code
        WHERE pd.id IS NULL
        GROUP BY s.package_code
    """)
    unknown_packages = cur.fetchall()
    for pkg, count in unknown_packages:
        issues.append((f"Unknown package: '{pkg}'", count,
                        "These bookings reference a package_code that doesn't exist in "
                        "package_definitions - their cost calculation will be wrong (treated "
                        "as including nothing)."))

    # 3) وكيل أو شركة طيران مستخدمين فى المبيعات لكن مش مسجّلين فى جداول المرجع
    cur.execute("""
        SELECT DISTINCT s.agent, COUNT(*) FROM sales s
        LEFT JOIN agents a ON a.name = s.agent
        WHERE a.id IS NULL AND s.agent != ''
        GROUP BY s.agent
    """)
    unknown_agents = cur.fetchall()
    for agent, count in unknown_agents:
        issues.append((f"Agent not in reference list: '{agent}'", count,
                        "Won't appear in Agent Accounts reports even though they have sales."))

    cur.execute("""
        SELECT DISTINCT s.airline, COUNT(*) FROM sales s
        LEFT JOIN airlines a ON a.name = s.airline
        WHERE a.id IS NULL AND s.airline != ''
        GROUP BY s.airline
    """)
    unknown_airlines = cur.fetchall()
    for airline, count in unknown_airlines:
        issues.append((f"Airline not in reference list: '{airline}'", count,
                        "Won't appear in Airline Accounts reports even though they have bookings."))

    # 4) روابط غياب/إعادة جدولة يتيمة (linked_row_id يشاور على صف محذوف)
    cur.execute("""
        SELECT COUNT(*) FROM sales s
        WHERE s.linked_row_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM sales s2 WHERE s2.id = s.linked_row_id)
    """)
    orphaned_links = cur.fetchone()[0]
    if orphaned_links:
        issues.append(("Orphaned no-show links", orphaned_links,
                        "These rows point to a linked_row_id that no longer exists (the other "
                        "side was deleted without clearing this link)."))

    conn.close()
    return issues


def print_report(issues):
    if not issues:
        print("✓ No issues found. Everything looks consistent.")
        return
    print(f"Found {len(issues)} issue type(s):\n")
    for title, count, explanation in issues:
        print(f"⚠ {title}: {count}")
        print(f"    {explanation}\n")


if __name__ == "__main__":
    issues = run_health_check()
    print_report(issues)
