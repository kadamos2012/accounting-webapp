"""
period_bookings_helper.py - Shared logic for applying an edit to one sales
row from the "Open bookings for a period" screen, used identically whether
the edit came from the web form or an uploaded Excel file.

Rule: if the agent/package/route/date changed but NO price/cost/airline/
supplier was typed manually, the row is recalculated automatically from the
current pricing tables. If ANY of those six values was typed manually, they
are respected exactly as given (no auto-recalculation for that row).
"""
import psycopg2.extensions
from pricing_engine import calculate_row


def save_one_row(cur, conn, sid, new_agent, new_package, new_port, new_dest, new_depdate,
                  manual_airline, manual_supplier, manual_sales, manual_visa,
                  manual_investment, manual_ticket):
    """يرجّع 'overridden' أو 'recalculated' أو None (لو الصف مش موجود)"""
    cur.execute("""
        SELECT name, date_of_birth, national_id, passport_number, port, destination,
               flight_number, departure_date, submission_date, agent, category,
               package_code, total_sales, visa_cost, investment_cost, ticket_cost,
               airline, investment_supplier
        FROM sales WHERE id = %s
    """, (sid,))
    row = cur.fetchone()
    if not row:
        return None

    agent = new_agent if new_agent not in (None, "") else row["agent"]
    package_code = new_package if new_package not in (None, "") else row["package_code"]
    port = new_port if new_port else row["port"]
    destination = new_dest if new_dest else row["destination"]
    departure_date = new_depdate if new_depdate else row["departure_date"]

    def parse_or(val, fallback):
        try:
            return float(val)
        except (TypeError, ValueError):
            return fallback

    manually_touched = any(v not in (None, "") for v in
                            [manual_airline, manual_supplier, manual_sales, manual_visa,
                             manual_investment, manual_ticket])

    if manually_touched:
        total_sales = parse_or(manual_sales, row["total_sales"])
        visa_cost = parse_or(manual_visa, row["visa_cost"])
        investment_cost = parse_or(manual_investment, row["investment_cost"])
        ticket_cost = parse_or(manual_ticket, row["ticket_cost"])
        total_cost = visa_cost + investment_cost + ticket_cost
        airline = manual_airline if manual_airline else row["airline"]
        investment_supplier = manual_supplier if manual_supplier else row["investment_supplier"]
        cur.execute("""
            UPDATE sales SET agent = %s, package_code = %s, port = %s, destination = %s,
                departure_date = %s, airline = %s, investment_supplier = %s,
                total_sales = %s, visa_cost = %s, investment_cost = %s,
                ticket_cost = %s, service_cost_total = %s, total_cost = %s,
                net_profit = %s
            WHERE id = %s
        """, (agent, package_code, port, destination, departure_date, airline,
              investment_supplier, total_sales, visa_cost, investment_cost, ticket_cost,
              visa_cost + investment_cost, total_cost, total_sales - total_cost, sid))
        return "overridden"

    plain_cur = conn.cursor(cursor_factory=psycopg2.extensions.cursor)
    recalculated = calculate_row(
        plain_cur, row["name"], row["date_of_birth"], row["national_id"],
        row["passport_number"], port, destination,
        row["flight_number"], departure_date, row["submission_date"],
        agent, row["category"], package_code, row_already_in_db=True
    )
    cur.execute("""
        UPDATE sales SET
            agent = %(agent)s, package_code = %(package_code)s,
            port = %(port)s, destination = %(destination)s,
            departure_date = %(departure_date)s,
            service_price = %(service_price)s, ticket_price = %(ticket_price)s,
            total_sales = %(total_sales)s, visa_cost = %(visa_cost)s,
            investment_cost = %(investment_cost)s, approval_cost = %(approval_cost)s,
            service_cost_total = %(service_cost_total)s, ticket_cost = %(ticket_cost)s,
            total_cost = %(total_cost)s, net_profit = %(net_profit)s,
            airline = %(airline)s, investment_supplier = %(investment_supplier)s
        WHERE id = %(sid)s
    """, {**recalculated, "sid": sid})
    return "recalculated"
