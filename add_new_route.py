"""
add_new_route.py - Adds a brand-new flight route (port + destination) to
BOTH pricing tables at once:
    1) ticket_costs   - purchase cost (what you pay the airline)
    2) total_sell_prices - what you charge the client (per package + category)

Why both are needed: the selling price and the purchase cost are two
SEPARATE tables now. Adding a route to only one of them means either the
client gets charged nothing (if sell price is missing) or costed nothing
(if purchase cost is missing) for that route.

Note: the OLD "Service_Prices"/"Ticket_Prices" tables from the original
Excel system are no longer used for pricing at all (the new selling-price
model replaced them) - you never need to touch them again.
"""
from db import get_connection

CATEGORIES = ["بالغ", "انثى", "طفل", "رضيع"]


def add_route(port, destination, airline, date_from="2020-01-01", date_to="2099-12-31"):
    conn = get_connection()
    cur = conn.cursor()

    # ---- يتحقق أولًا: هل خط السير ده (منفذ+وجهة) موجود بالفعل بأي شركة طيران تانية؟ ----
    # سعر البيع (total_sell_prices) غير مرتبط بشركة طيران معيّنة أصلًا - فلو خط
    # السير موجود، سعر البيع بتاعه موجود بالفعل ومفيش داعي نضيفه تانى
    cur.execute("SELECT COUNT(*) FROM total_sell_prices WHERE port=%s AND destination=%s",
                (port, destination))
    route_already_exists = cur.fetchone()[0] > 0

    # ---- ticket_costs: مرتبط بشركة الطيران تحديدًا - دايمًا نتأكد نضيفه لو مش موجود ----
    cur.execute("""
        SELECT id FROM ticket_costs WHERE port=%s AND destination=%s AND airline=%s
    """, (port, destination, airline))
    if cur.fetchone():
        print(f"Note: a ticket_costs row for {port} -> {destination} ({airline}) already exists - skipped.")
        cost_added = False
    else:
        cur.execute("""
            INSERT INTO ticket_costs(date_from, date_to, port, destination, airline,
                                      cost_adult, cost_female, cost_child, cost_infant)
            VALUES (%s,%s,%s,%s,%s,0,0,0,0)
        """, (date_from, date_to, port, destination, airline))
        print(f"Added ticket_costs row for {port} -> {destination} ({airline}) (all costs default to 0).")
        cost_added = True

    if route_already_exists:
        # ---- نفس خط السير، شركة طيران جديدة فقط: مفيش داعي نضيف سعر بيع تانى ----
        conn.commit()
        conn.close()
        print(f"\nهذا خط سير ({port} -> {destination}) موجود بالفعل - أضفنا بس تكلفة الشراء "
              f"الخاصة بشركة {airline} الجديدة. أسعار البيع لهذا الخط موجودة بالفعل ولا تحتاج "
              f"أي تعديل، إلا لو عايزة تغيّريها فعلًا.")
        print("\nالخطوة التالية:")
        print("  فقط املأ تكلفة الشراء الجديدة: export_ticket_costs_to_excel.py -> edit -> "
              "import_ticket_costs_from_excel.py")
        return {"scenario": "same_route_new_airline", "cost_added": cost_added}

    # ---- خط سير جديد تمامًا: نضيف سعر البيع لكل تركيبة (باكدج × فئة) ----
    cur.execute("SELECT package_code FROM package_definitions")
    packages = [r[0] for r in cur.fetchall()]

    added = 0
    for pkg in packages:
        for cat in CATEGORIES:
            cur.execute("""
                SELECT id FROM total_sell_prices
                WHERE package_code=%s AND port=%s AND destination=%s AND category=%s
            """, (pkg, port, destination, cat))
            if cur.fetchone():
                continue
            cur.execute("""
                INSERT INTO total_sell_prices(date_from, date_to, package_code, port, destination, category, total_price)
                VALUES (%s,%s,%s,%s,%s,%s,0)
            """, (date_from, date_to, pkg, port, destination, cat))
            added += 1

    conn.commit()
    conn.close()
    print(f"\nهذا خط سير جديد تمامًا - أُضيف {added} صف فى جدول سعر البيع "
          f"({len(packages)} باكدج × {len(CATEGORIES)} فئات)، كلهم بسعر افتراضى صفر.")
    print("\nالخطوات التالية:")
    print("  1. املأ تكلفة الشراء الحقيقية: export_ticket_costs_to_excel.py -> edit -> "
          "import_ticket_costs_from_excel.py")
    print("  2. املأ سعر البيع الحقيقى: export_sell_prices_to_excel.py -> edit -> "
          "import_sell_prices_from_excel.py")
    return {"scenario": "brand_new_route", "cost_added": cost_added, "sell_prices_added": added}


def main():
    print("=== Add a new flight route ===")
    port = input("المنفذ (e.g. مطار القاهره): ").strip()
    destination = input("جهة المغادرة (e.g. طرابلس): ").strip()
    airline = input("شركة الطيران: ").strip()
    add_route(port, destination, airline)


if __name__ == "__main__":
    main()
