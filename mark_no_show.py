"""
mark_no_show.py - Marks a client as a no-show (غياب) and automatically
creates the linked rebooking row with the replacement package (PostgreSQL
/ Supabase version - returns a message dict instead of printing).
"""
from db import get_connection
from pricing_engine import calculate_row


def mark_no_show(national_id, departure_date, penalty):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, date_of_birth, passport_number, port, destination, flight_number,
               submission_date, agent, category, package_code, booking_status, linked_row_id
        FROM sales WHERE national_id = %s AND departure_date = %s
    """, (national_id, departure_date))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"success": False, "message": "لم يتم العثور على عميل بهذا الرقم القومى وتاريخ المغادرة."}

    (sale_id, name, dob, passport, port, dest, flight, submission_date,
     agent, category, package_code, current_status, linked_row_id) = row

    if current_status == "غياب (No Show)":
        conn.close()
        return {"success": False, "message": "هذا العميل مُسجَّل بالفعل كغياب."}

    cur.execute("""
        UPDATE sales SET booking_status = 'غياب (No Show)', no_show_penalty = %s,
                          investment_cost = 0, ticket_cost = %s
        WHERE id = %s
    """, (penalty, penalty, sale_id))

    cur.execute("SELECT visa_cost, approval_cost, total_sales FROM sales WHERE id = %s", (sale_id,))
    visa_cost, approval_cost, total_sales = cur.fetchone()
    new_service_cost_total = visa_cost + 0 + approval_cost
    new_total_cost = new_service_cost_total + penalty
    new_net_profit = total_sales - new_total_cost
    cur.execute("""
        UPDATE sales SET service_cost_total = %s, total_cost = %s, net_profit = %s
        WHERE id = %s
    """, (new_service_cost_total, new_total_cost, new_net_profit, sale_id))

    cur.execute("SELECT replacement_package FROM package_rebooking_map WHERE original_package = %s",
                (package_code,))
    r = cur.fetchone()
    if not r:
        conn.commit()
        conn.close()
        return {"success": True,
                "message": "تم تسجيل الغياب. لا يوجد باكدج بديل معرَّف لهذا النوع، فلم يتم إنشاء صف إعادة جدولة."}
    replacement_package = r[0]

    new_row = calculate_row(
        cur, name, dob, national_id, passport, port, dest, flight, departure_date,
        submission_date, agent, category, replacement_package
    )
    cur.execute("""
        INSERT INTO sales(
            name, date_of_birth, national_id, passport_number, port, destination,
            flight_number, departure_date, submission_date, agent, investment_supplier,
            category, package_code, airline,
            service_price, ticket_price, total_sales,
            visa_cost, investment_cost, approval_cost, service_cost_total, ticket_cost, total_cost, net_profit,
            booking_status, no_show_penalty
        ) VALUES (%(name)s,%(date_of_birth)s,%(national_id)s,%(passport_number)s,%(port)s,%(destination)s,
                  %(flight_number)s,%(departure_date)s,%(submission_date)s,%(agent)s,%(investment_supplier)s,
                  %(category)s,%(package_code)s,%(airline)s,
                  %(service_price)s,%(ticket_price)s,%(total_sales)s,
                  %(visa_cost)s,%(investment_cost)s,%(approval_cost)s,%(service_cost_total)s,%(ticket_cost)s,%(total_cost)s,%(net_profit)s,
                  %(booking_status)s,%(no_show_penalty)s)
        RETURNING id
    """, new_row)
    new_id = cur.fetchone()[0]

    cur.execute("UPDATE sales SET linked_row_id = %s WHERE id = %s", (new_id, sale_id))
    cur.execute("UPDATE sales SET linked_row_id = %s WHERE id = %s", (sale_id, new_id))

    conn.commit()
    conn.close()
    return {"success": True,
            "message": f"تم تسجيل الغياب بنجاح. الباكدج البديل ({replacement_package}) أُضيف كصف جديد (id={new_id})."}


def unmark_no_show(national_id, departure_date, delete_linked=True):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, linked_row_id, name, date_of_birth, passport_number, port, destination,
               flight_number, submission_date, agent, category, package_code
        FROM sales WHERE national_id = %s AND departure_date = %s AND booking_status = 'غياب (No Show)'
    """, (national_id, departure_date))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"success": False, "message": "لم يتم العثور على عميل مُسجَّل كغياب بهذا الرقم القومى وتاريخ المغادرة."}

    (sale_id, linked_id, name, dob, passport, port, dest, flight,
     submission_date, agent, category, package_code) = row

    recalculated = calculate_row(
        cur, name, dob, national_id, passport, port, dest, flight, departure_date,
        submission_date, agent, category, package_code, row_already_in_db=True
    )
    cur.execute("""
        UPDATE sales SET
            booking_status = 'عادى', no_show_penalty = 0, linked_row_id = NULL,
            service_price = %(service_price)s, ticket_price = %(ticket_price)s, total_sales = %(total_sales)s,
            visa_cost = %(visa_cost)s, investment_cost = %(investment_cost)s, approval_cost = %(approval_cost)s,
            service_cost_total = %(service_cost_total)s, ticket_cost = %(ticket_cost)s,
            total_cost = %(total_cost)s, net_profit = %(net_profit)s,
            airline = %(airline)s, investment_supplier = %(investment_supplier)s
        WHERE id = %(sale_id)s
    """, {**recalculated, "sale_id": sale_id})

    if linked_id and delete_linked:
        cur.execute("DELETE FROM sales WHERE id = %s", (linked_id,))
        msg = f"تم إلغاء الغياب (وإعادة حساب التكلفة الأصلية)، وحُذف صف إعادة الجدولة المرتبط (id={linked_id})."
    elif linked_id:
        cur.execute("UPDATE sales SET linked_row_id = NULL WHERE id = %s", (linked_id,))
        msg = f"تم إلغاء الغياب. صف إعادة الجدولة (id={linked_id}) لم يُحذف - فُكَّ الربط فقط."
    else:
        msg = "تم إلغاء الغياب (وإعادة حساب التكلفة الأصلية) - لم يكن هناك صف إعادة جدولة مرتبط."

    conn.commit()
    conn.close()
    return {"success": True, "message": msg}
