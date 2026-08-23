"""
add_charter_booking.py - Records a charter flight booking (a full-flight
purchase from an airline). Once recorded, any client's ticket cost for that
exact flight number + departure date automatically uses this charter's
per-seat cost (total_cost divided by the number of ticket-inclusive
passengers on that flight) instead of the standard route-based cost table.
"""
from datetime import date
from db import get_connection


def add_booking(flight_number, departure_date, airline, total_cost):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM charter_bookings WHERE flight_number = %s AND departure_date = %s
    """, (flight_number, departure_date))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return {"success": False,
                "message": f"يوجد بالفعل حجز شارتر لهذه الرحلة والتاريخ (id={existing[0]})."}

    cur.execute("""
        INSERT INTO charter_bookings(flight_number, departure_date, airline, total_cost)
        VALUES (%s,%s,%s,%s)
    """, (flight_number, departure_date, airline, total_cost))
    conn.commit()
    conn.close()
    return {"success": True,
            "message": f"تم تسجيل حجز الشارتر: رحلة {flight_number} فى {departure_date}، "
                       f"شركة {airline}، بتكلفة إجمالية {total_cost:,.0f}."}


def update_booking(flight_number, departure_date, total_cost):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE charter_bookings SET total_cost = %s WHERE flight_number = %s AND departure_date = %s
    """, (total_cost, flight_number, departure_date))
    if cur.rowcount == 0:
        print("No charter booking found for this flight number + departure date.")
    else:
        conn.commit()
        print(f"Charter booking updated: new total cost {total_cost:,.0f}.")
    conn.close()


def list_bookings():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT flight_number, departure_date, airline, total_cost FROM charter_bookings ORDER BY departure_date")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No charter bookings recorded yet.")
    for r in rows:
        print(f"  Flight {r[0]} | {r[1]} | {r[2]} | Total cost: {r[3]:,.0f}")
    return rows


def recalculate_flight(flight_number, departure_date):
    """يعيد حساب تكلفة التذكرة لكل العملاء الموجودين بالفعل على رحلة معيّنة (مفيد
    بعد إضافة/تعديل حجز شارتر لرحلة عندها عملاء مُستوردين من قبل - إضافة الشارتر
    وحدها لا تُحدِّث الصفوف الموجودة تلقائيًا، لازم تشغيل هذه الدالة بعدها)"""
    from pricing_engine import calculate_row

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, date_of_birth, national_id, passport_number, port, destination,
               submission_date, agent, category, package_code
        FROM sales WHERE flight_number = %s AND departure_date = %s
    """, (flight_number, departure_date))
    rows = cur.fetchall()

    updated = 0
    for row in rows:
        (sale_id, name, dob, nid, passport, port, dest, submission_date, agent,
         category, package_code) = row
        recalculated = calculate_row(
            cur, name, dob, nid, passport, port, dest, flight_number, departure_date,
            submission_date, agent, category, package_code, row_already_in_db=True
        )
        cur.execute("""
            UPDATE sales SET
                service_price = %(service_price)s, ticket_price = %(ticket_price)s, total_sales = %(total_sales)s,
                visa_cost = %(visa_cost)s, investment_cost = %(investment_cost)s, approval_cost = %(approval_cost)s,
                service_cost_total = %(service_cost_total)s, ticket_cost = %(ticket_cost)s,
                total_cost = %(total_cost)s, net_profit = %(net_profit)s,
                investment_supplier = %(investment_supplier)s
            WHERE id = %(sale_id)s
        """, {**recalculated, "sale_id": sale_id})
        updated += 1

    conn.commit()
    conn.close()
    return {"updated": updated}



def main():
    print("=== Add a charter flight booking ===")
    flight_number = input("Flight number (exactly as it appears in client bookings, e.g. 'اير كايرو SM 231'): ").strip()
    departure_date = input("Departure date (YYYY-MM-DD): ").strip()
    airline = input("Airline name: ").strip()
    try:
        total_cost = float(input("Total cost of the whole charter: ").strip())
    except ValueError:
        print("Total cost must be a number.")
        return
    add_booking(flight_number, departure_date, airline, total_cost)

    recalc = input("\nRecalculate ticket cost for clients already on this flight%s (y/n): ").strip().lower()
    if recalc == "y":
        recalculate_flight(flight_number, departure_date)


if __name__ == "__main__":
    main()
