"""
pricing_engine.py - Shared calculation logic used by the daily import script
(and potentially other tools). Mirrors the business rules from the original
Excel system, with the NEW simplified total-selling-price model:

  SELL SIDE:  one total price looked up from total_sell_prices, keyed by
              (package_code, port, destination, category, submission_date)
  COST SIDE:  unchanged - visa/investment/approval costs from service_costs
              (keyed by package+component+category+submission_date), ticket
              cost from ticket_costs (keyed by route+airline+category+
              departure_date), with a charter_bookings override if the
              flight+date matches a chartered booking.
"""
def get_package_flags(cur, package_code):
    cur.execute("""
        SELECT includes_visa, includes_investment, includes_approval, includes_ticket
        FROM package_definitions WHERE package_code = %s
    """, (package_code,))
    row = cur.fetchone()
    if row is None:
        return (0, 0, 0, 0)
    return row


def extract_airline(flight_number):
    """Mirrors the Excel logic: strip the trailing numeric flight code + the
    airline-code token before it, leaving just the airline name. If the last
    token isn't numeric, the whole flight_number is treated as the airline
    name as-is (matches the Excel fallback behaviour)."""
    if not flight_number:
        return ""
    tokens = flight_number.strip().split(" ")
    last = tokens[-1]
    if last.replace(".", "", 1).isdigit():
        return " ".join(tokens[:-2]).strip() if len(tokens) >= 2 else ""
    return flight_number.strip()


def lookup_total_sell_price(cur, package_code, port, destination, category, submission_date):
    cur.execute("""
        SELECT total_price FROM total_sell_prices
        WHERE package_code = %s AND port = %s AND destination = %s AND category = %s
              AND date_from <= %s AND date_to >= %s
        ORDER BY id LIMIT 1
    """, (package_code, port, destination, category, submission_date, submission_date))
    row = cur.fetchone()
    return row[0] if row else 0.0


def lookup_service_cost(cur, package_code, component, category, submission_date):
    cur.execute("""
        SELECT cost FROM service_costs
        WHERE package_code = %s AND component = %s AND (category = %s OR category = 'الكل')
              AND date_from <= %s AND date_to >= %s
        ORDER BY id LIMIT 1
    """, (package_code, component, category, submission_date, submission_date))
    row = cur.fetchone()
    return row[0] if row else 0.0


def lookup_ticket_cost(cur, port, destination, airline, category, departure_date):
    cur.execute("""
        SELECT cost_adult, cost_female, cost_child, cost_infant FROM ticket_costs
        WHERE port = %s AND destination = %s AND airline = %s
              AND date_from <= %s AND date_to >= %s
        ORDER BY id LIMIT 1
    """, (port, destination, airline, departure_date, departure_date))
    row = cur.fetchone()
    if not row:
        return 0.0
    cost_adult, cost_female, cost_child, cost_infant = row
    if category == "طفل":
        return cost_child
    if category == "رضيع":
        return cost_infant
    if category == "انثى":
        return cost_female
    return cost_adult


def lookup_charter_cost_per_seat(cur, flight_number, departure_date, row_already_in_db=False):
    """Returns the per-seat charter cost if this flight+date matches a
    charter booking, divided by the count of ticket-inclusive passengers on
    that exact flight+date. Returns None if this flight+date isn't a
    charter booking.

    row_already_in_db must be set correctly by the caller:
      - False (daily import): the row being priced is NOT YET inserted into
        the sales table, so it's added +1 on top of the existing count.
      - True (recalculating an existing row, e.g. after adding/editing a
        charter booking): the row is already counted by the SELECT COUNT(*)
        below, so no +1 is added - otherwise the per-seat cost comes out
        too low (diluted across one seat too many)."""
    cur.execute("""
        SELECT total_cost FROM charter_bookings
        WHERE flight_number = %s AND departure_date = %s
        ORDER BY id LIMIT 1
    """, (flight_number, departure_date))
    row = cur.fetchone()
    if not row:
        return None
    total_cost = row[0]

    cur.execute("""
        SELECT COUNT(*) FROM sales s
        JOIN package_definitions pd ON pd.package_code = s.package_code
        WHERE s.flight_number = %s AND s.departure_date = %s AND pd.includes_ticket = 1
    """, (flight_number, departure_date))
    seat_count = cur.fetchone()[0]
    if not row_already_in_db:
        seat_count += 1
    if seat_count <= 0:
        return 0.0
    return total_cost / seat_count


def lookup_investment_supplier(cur, airline, departure_date):
    cur.execute("""
        SELECT supplier FROM investment_supplier_assignment
        WHERE airline = %s AND date_from <= %s AND date_to >= %s
        ORDER BY id LIMIT 1
    """, (airline, departure_date, departure_date))
    row = cur.fetchone()
    return row[0] if row else None


def calculate_row(cur, name, dob, national_id, passport, port, destination,
                   flight_number, departure_date, submission_date, agent,
                   category, package_code, row_already_in_db=False):
    """Computes all derived fields for one client row. Returns a dict ready
    to be inserted into the sales table (minus id/created_at).

    row_already_in_db: pass True when recalculating a row that ALREADY
    exists in the sales table (e.g. via recalculate_flight after adding a
    charter booking, or undoing a no-show) - this is needed so the charter
    per-seat cost divides by the correct passenger count. Leave False for
    brand-new imports (the default)."""
    includes_visa, includes_investment, includes_approval, includes_ticket = \
        get_package_flags(cur, package_code)

    airline = extract_airline(flight_number)

    # ---- SELL SIDE: one total price (NEW model) ----
    total_sales = lookup_total_sell_price(cur, package_code, port, destination,
                                           category, submission_date)

    # ---- COST SIDE: unchanged, per-component ----
    visa_cost = lookup_service_cost(cur, package_code, "تأشيرة", category, submission_date) \
        if includes_visa else 0.0
    investment_cost = lookup_service_cost(cur, package_code, "استثمار", category, submission_date) \
        if includes_investment else 0.0
    approval_cost = lookup_service_cost(cur, package_code, "موافقة", category, submission_date) \
        if includes_approval else 0.0
    service_cost_total = visa_cost + investment_cost + approval_cost

    ticket_cost = 0.0
    if includes_ticket:
        charter_per_seat = lookup_charter_cost_per_seat(cur, flight_number, departure_date,
                                                          row_already_in_db=row_already_in_db)
        if charter_per_seat is not None:
            ticket_cost = charter_per_seat
        else:
            ticket_cost = lookup_ticket_cost(cur, port, destination, airline, category, departure_date)

    total_cost = service_cost_total + ticket_cost
    net_profit = total_sales - total_cost

    investment_supplier = lookup_investment_supplier(cur, airline, departure_date) \
        if includes_investment else None

    return {
        "name": name, "date_of_birth": dob, "national_id": national_id,
        "passport_number": passport, "port": port, "destination": destination,
        "flight_number": flight_number, "departure_date": departure_date,
        "submission_date": submission_date, "agent": agent,
        "investment_supplier": investment_supplier, "category": category,
        "package_code": package_code, "airline": airline,
        "service_price": 0.0, "ticket_price": 0.0, "total_sales": total_sales,
        "visa_cost": visa_cost, "investment_cost": investment_cost,
        "approval_cost": approval_cost, "service_cost_total": service_cost_total,
        "ticket_cost": ticket_cost, "total_cost": total_cost, "net_profit": net_profit,
        "booking_status": "عادى", "no_show_penalty": 0.0,
    }
