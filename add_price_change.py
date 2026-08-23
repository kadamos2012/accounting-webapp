"""
add_price_change.py - Adds a NEW selling price or purchase cost for an
EXISTING package, effective from a chosen date onward, WITHOUT touching the
old price's history (so past clients keep their old price, and only new
bookings from the effective date use the new one).

How it works: it finds any existing row(s) covering the effective date and
shortens their date_to to end right before it, then inserts a new row
starting at the effective date and running to 2099-12-31 with the new
price/cost.
"""
from datetime import date, timedelta
from db import get_connection


def _day_before(date_str):
    d = date.fromisoformat(date_str)
    return (d - timedelta(days=1)).isoformat()


def add_sell_price_change(package_code, port, destination, category, new_price,
                            effective_date):
    """سعر بيع جديد لباكدج/خط سير/فئة موجودين، سارى من تاريخ معيّن"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, date_from, date_to FROM total_sell_prices
        WHERE package_code=%s AND port=%s AND destination=%s AND category=%s
              AND date_to >= %s
    """, (package_code, port, destination, category, effective_date))
    overlapping = cur.fetchall()

    for rid, dfrom, dto in overlapping:
        if dfrom >= effective_date:
            # الصف بيبدأ أصلًا فى/بعد التاريخ الجديد - يتحذف بدل ما يتقصّر لصفر مدة
            cur.execute("DELETE FROM total_sell_prices WHERE id=%s", (rid,))
        else:
            cur.execute("UPDATE total_sell_prices SET date_to=%s WHERE id=%s",
                        (_day_before(effective_date), rid))

    cur.execute("""
        INSERT INTO total_sell_prices(date_from, date_to, package_code, port, destination, category, total_price)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (effective_date, "2099-12-31", package_code, port, destination, category, new_price))

    conn.commit()
    conn.close()
    print(f"New selling price {new_price:,.0f} for {package_code} / {port}->{destination} / {category}, "
          f"effective from {effective_date}. Old price(s) now end on {_day_before(effective_date)}.")
    print("Note: this does NOT retroactively change already-imported clients. To also update clients "
          "already booked AFTER the effective date with the old (now-incorrect) price, run "
          "recalculate_period.py for the relevant range.")


def add_service_cost_change(package_code, component, category, new_cost,
                              effective_date):
    """تكلفة شراء خدمة جديدة (تأشيرة/استثمار/موافقة)، سارية من تاريخ معيّن"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, date_from, date_to FROM service_costs
        WHERE package_code=%s AND component=%s AND category=%s AND date_to >= %s
    """, (package_code, component, category, effective_date))
    overlapping = cur.fetchall()

    for rid, dfrom, dto in overlapping:
        if dfrom >= effective_date:
            cur.execute("DELETE FROM service_costs WHERE id=%s", (rid,))
        else:
            cur.execute("UPDATE service_costs SET date_to=%s WHERE id=%s",
                        (_day_before(effective_date), rid))

    cur.execute("""
        INSERT INTO service_costs(date_from, date_to, package_code, component, category, cost)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (effective_date, "2099-12-31", package_code, component, category, new_cost))

    conn.commit()
    conn.close()
    print(f"New service cost {new_cost:,.0f} for {package_code} / {component} / {category}, "
          f"effective from {effective_date}.")


def add_ticket_cost_change(port, destination, airline, cost_adult, cost_female, cost_child,
                             cost_infant, effective_date):
    """تكلفة شراء تذاكر جديدة لخط سير/شركة طيران، سارية من تاريخ معيّن"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, date_from, date_to FROM ticket_costs
        WHERE port=%s AND destination=%s AND airline=%s AND date_to >= %s
    """, (port, destination, airline, effective_date))
    overlapping = cur.fetchall()

    for rid, dfrom, dto in overlapping:
        if dfrom >= effective_date:
            cur.execute("DELETE FROM ticket_costs WHERE id=%s", (rid,))
        else:
            cur.execute("UPDATE ticket_costs SET date_to=%s WHERE id=%s",
                        (_day_before(effective_date), rid))

    cur.execute("""
        INSERT INTO ticket_costs(date_from, date_to, port, destination, airline,
                                  cost_adult, cost_female, cost_child, cost_infant)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (effective_date, "2099-12-31", port, destination, airline,
          cost_adult, cost_female, cost_child, cost_infant))

    conn.commit()
    conn.close()
    print(f"New ticket cost for {port}->{destination} ({airline}), effective from {effective_date}.")
