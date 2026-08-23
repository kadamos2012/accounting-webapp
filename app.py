"""
app.py - Main Flask web application. Run locally with `python app.py` for
testing, or deploy to Render (which runs it via gunicorn automatically).
"""
import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

from db import get_connection
import reports
import import_daily_submissions
import mark_no_show
import add_new_route
import add_charter_booking
import add_price_change
import health_check
import undo_last_import
import excel_export
from flask import send_file

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")

APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("كلمة السر غلط")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM sales")
    total_clients = cur.fetchone()["c"]
    cur.execute("SELECT import_date, source_file FROM import_log ORDER BY id DESC LIMIT 1")
    last_import = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS c FROM sales WHERE total_sales <= 0")
    zero_price = cur.fetchone()["c"]
    conn.close()
    return render_template("dashboard.html", total_clients=total_clients,
                            last_import=last_import, zero_price=zero_price)


@app.route("/import", methods=["GET", "POST"])
@login_required
def import_page():
    result = None
    if request.method == "POST":
        file = request.files.get("submissions_file")
        if not file or file.filename == "":
            flash("من فضلك اختاري ملف")
        else:
            upload_path = os.path.join("/tmp", file.filename)
            file.save(upload_path)
            result = import_daily_submissions.import_file(upload_path)
            os.remove(upload_path)
    return render_template("import.html", result=result)


@app.route("/reports/agents")
@login_required
def agent_report():
    results = reports.get_all_agent_accounts()
    return render_template("agent_report.html", results=results)


@app.route("/reports/full")
@login_required
def full_report():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")

    conn = get_connection()
    cur = conn.cursor()

    agent_results = reports.get_all_agent_accounts(date_from, date_to)

    cur.execute("SELECT name FROM visa_suppliers ORDER BY name")
    visa_results = [reports.get_visa_supplier_account(cur, r[0], date_from, date_to)
                     for r in cur.fetchall()]

    cur.execute("SELECT name FROM investment_suppliers ORDER BY name")
    investment_results = [reports.get_investment_supplier_account(cur, r[0], date_from, date_to)
                           for r in cur.fetchall()]

    cur.execute("SELECT name FROM airlines ORDER BY name")
    airline_results = [reports.get_airline_account(cur, r[0], date_from, date_to)
                        for r in cur.fetchall()]

    partner_results = reports.get_all_partner_accounts(date_from, date_to)
    pl = reports.get_profit_and_loss(cur, date_from, date_to)

    conn.close()
    return render_template("full_report.html", agent_results=agent_results,
                            visa_results=visa_results, investment_results=investment_results,
                            airline_results=airline_results, partner_results=partner_results,
                            pl=pl, date_from=date_from, date_to=date_to)


@app.route("/reports/full/download")
@login_required
def full_report_download():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")
    buf = excel_export.build_full_report_xlsx(date_from, date_to)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return send_file(buf, as_attachment=True, download_name=f"تقرير_الحسابات_{timestamp}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


MOVEMENT_TYPES = [
    "تحصيل من عميل",
    "سداد لمورد - تأشيرات",
    "سداد لمورد - تذاكر طيران",
    "سداد لمورد - استثمار",
    "مصروفات عمومية",
    "توزيع أرباح على شريك",
    "إيداع/تحويل فى الخزنة",
    "أخرى",
]


def get_names(table):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT name FROM {table} ORDER BY name")
    names = [r[0] for r in cur.fetchall()]
    conn.close()
    return names


@app.route("/treasury", methods=["GET", "POST"])
@login_required
def treasury_page():
    saved = None
    if request.method == "POST":
        movement_type = request.form.get("movement_type")
        party = request.form.get("party", "").strip()
        desc = request.form.get("description", "").strip()
        tdate = request.form.get("date", "").strip() or date_today()
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        payment_method = ""
        related_agent = ""
        related_partner = ""
        if movement_type.startswith("سداد لمورد") and request.form.get("direct"):
            payment_method = "مباشر (بين العميل والمورد)"
            related_agent = request.form.get("related_party", "").strip()
        elif movement_type.startswith("سداد لمورد"):
            payment_method = "عن طريق الخزنة"
        elif movement_type == "تحصيل من عميل" and request.form.get("partner_designate"):
            related_partner = request.form.get("related_party", "").strip()

        incoming = amount if movement_type in ("تحصيل من عميل", "إيداع/تحويل فى الخزنة") else 0
        outgoing = amount if movement_type not in ("تحصيل من عميل", "إيداع/تحويل فى الخزنة") else 0

        if amount > 0:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO treasury(transaction_date, description, movement_type, party_name,
                                      payment_method, related_agent, related_partner, incoming, outgoing)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (tdate, desc, movement_type, party, payment_method, related_agent,
                  related_partner, incoming, outgoing))
            conn.commit()
            conn.close()
            saved = {"movement_type": movement_type, "party": party, "amount": amount}
        else:
            flash("المبلغ لازم يكون أكبر من صفر")

    return render_template("treasury.html", movement_types=MOVEMENT_TYPES,
                            agents=get_names("agents"), airlines=get_names("airlines"),
                            visa_suppliers=get_names("visa_suppliers"),
                            investment_suppliers=get_names("investment_suppliers"),
                            partners=get_names("partners"), saved=saved)


def date_today():
    from datetime import date
    return date.today().isoformat()


def detect_entity_type(cur, name):
    for table, etype in [("agents", "agent"), ("airlines", "airline"),
                          ("visa_suppliers", "visa"), ("investment_suppliers", "investment"),
                          ("partners", "partner")]:
        cur.execute(f"SELECT 1 FROM {table} WHERE name = %s", (name,))
        if cur.fetchone():
            return etype
    return None


@app.route("/statement", methods=["GET", "POST"])
@login_required
def statement_page():
    result = None
    all_parties = get_names("agents") + get_names("airlines") + get_names("visa_suppliers") + \
                  get_names("investment_suppliers") + get_names("partners")
    if request.method == "POST":
        name = request.form.get("party", "").strip()
        date_from = request.form.get("from") or "2020-01-01"
        date_to = request.form.get("to") or "2099-12-31"

        conn = get_connection()
        cur = conn.cursor()
        entity_type = detect_entity_type(cur, name)
        if not entity_type:
            flash(f"لم يتم التعرف على '{name}' كطرف معروف")
        else:
            summary = None
            txn_headers, txn_rows = None, []
            if entity_type == "agent":
                summary = reports.get_agent_account(cur, name, date_from, date_to)
                cur.execute("""
                    SELECT submission_date, name, national_id, package_code, total_sales
                    FROM sales WHERE agent = %s AND submission_date BETWEEN %s AND %s
                    ORDER BY submission_date
                """, (name, date_from, date_to))
                txn_headers = ["التاريخ", "اسم العميل", "الرقم القومى", "نوع الخدمة", "المبلغ"]
                cols = [d[0] for d in cur.description]
                txn_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            elif entity_type == "airline":
                summary = reports.get_airline_account(cur, name, date_from, date_to)
                cur.execute("""
                    SELECT departure_date, name, national_id, flight_number, ticket_cost
                    FROM sales WHERE airline = %s AND departure_date BETWEEN %s AND %s
                    ORDER BY departure_date
                """, (name, date_from, date_to))
                txn_headers = ["تاريخ المغادرة", "اسم العميل", "الرقم القومى", "رقم الرحلة", "تكلفة التذكرة"]
                cols = [d[0] for d in cur.description]
                txn_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            elif entity_type == "visa":
                summary = reports.get_visa_supplier_account(cur, name, date_from, date_to)
            elif entity_type == "investment":
                summary = reports.get_investment_supplier_account(cur, name, date_from, date_to)
            elif entity_type == "partner":
                summary = reports.get_partner_account(cur, name, date_from, date_to)

            all_time = None
            if entity_type == "agent":
                all_time = reports.get_agent_account(cur, name, "2020-01-01", "2099-12-31")
            elif entity_type == "airline":
                all_time = reports.get_airline_account(cur, name, "2020-01-01", "2099-12-31")
            elif entity_type == "visa":
                all_time = reports.get_visa_supplier_account(cur, name, "2020-01-01", "2099-12-31")
            elif entity_type == "investment":
                all_time = reports.get_investment_supplier_account(cur, name, "2020-01-01", "2099-12-31")
            elif entity_type == "partner":
                all_time = reports.get_partner_account(cur, name, "2020-01-01", "2099-12-31")

            result = {"entity_type": entity_type, "name": name, "summary": summary,
                      "txn_headers": txn_headers, "txn_rows": txn_rows, "all_time": all_time}
        conn.close()

    return render_template("statement.html", all_parties=all_parties, result=result)


@app.route("/statement/download")
@login_required
def statement_download():
    name = request.args.get("party", "").strip()
    date_from = request.args.get("from") or "2020-01-01"
    date_to = request.args.get("to") or "2099-12-31"

    conn = get_connection()
    cur = conn.cursor()
    entity_type = detect_entity_type(cur, name)
    if not entity_type:
        conn.close()
        flash(f"لم يتم التعرف على '{name}' كطرف معروف")
        return redirect(url_for("statement_page"))

    summary, txn_headers, txn_rows = None, None, []
    if entity_type == "agent":
        summary = reports.get_agent_account(cur, name, date_from, date_to)
        cur.execute("""
            SELECT submission_date, name, national_id, package_code, total_sales
            FROM sales WHERE agent = %s AND submission_date BETWEEN %s AND %s ORDER BY submission_date
        """, (name, date_from, date_to))
        txn_headers = ["التاريخ", "اسم العميل", "الرقم القومى", "نوع الخدمة", "المبلغ"]
        cols = [d[0] for d in cur.description]
        txn_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    elif entity_type == "airline":
        summary = reports.get_airline_account(cur, name, date_from, date_to)
        cur.execute("""
            SELECT departure_date, name, national_id, flight_number, ticket_cost
            FROM sales WHERE airline = %s AND departure_date BETWEEN %s AND %s ORDER BY departure_date
        """, (name, date_from, date_to))
        txn_headers = ["تاريخ المغادرة", "اسم العميل", "الرقم القومى", "رقم الرحلة", "تكلفة التذكرة"]
        cols = [d[0] for d in cur.description]
        txn_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    elif entity_type == "visa":
        summary = reports.get_visa_supplier_account(cur, name, date_from, date_to)
    elif entity_type == "investment":
        summary = reports.get_investment_supplier_account(cur, name, date_from, date_to)
    elif entity_type == "partner":
        summary = reports.get_partner_account(cur, name, date_from, date_to)

    if entity_type == "agent":
        all_time = reports.get_agent_account(cur, name, "2020-01-01", "2099-12-31")
    elif entity_type == "airline":
        all_time = reports.get_airline_account(cur, name, "2020-01-01", "2099-12-31")
    elif entity_type == "visa":
        all_time = reports.get_visa_supplier_account(cur, name, "2020-01-01", "2099-12-31")
    elif entity_type == "investment":
        all_time = reports.get_investment_supplier_account(cur, name, "2020-01-01", "2099-12-31")
    else:
        all_time = reports.get_partner_account(cur, name, "2020-01-01", "2099-12-31")
    conn.close()

    buf = excel_export.build_statement_xlsx(name, entity_type, summary, txn_headers, txn_rows, all_time)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    safe_name = excel_export.clean_filename(name)
    return send_file(buf, as_attachment=True, download_name=f"كشف_حساب_{safe_name}_{timestamp}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/noshow", methods=["GET", "POST"])
@login_required
def noshow_page():
    message = None
    if request.method == "POST":
        action = request.form.get("action")
        nid = request.form.get("national_id", "").strip()
        dep = request.form.get("departure_date", "").strip()
        if action == "mark":
            try:
                penalty = float(request.form.get("penalty", 0))
            except ValueError:
                penalty = 0
            message = mark_no_show.mark_no_show(nid, dep, penalty)
        else:
            message = mark_no_show.unmark_no_show(nid, dep)
    return render_template("noshow.html", message=message)


@app.route("/packages", methods=["GET", "POST"])
@login_required
def packages_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        if request.form.get("action") == "add":
            new_code = request.form.get("new_package_code", "").strip()
            if new_code:
                cur.execute("""
                    INSERT INTO package_definitions(package_code, includes_visa, includes_investment,
                                                      includes_approval, includes_ticket)
                    VALUES (%s, 0, 0, 0, 0) ON CONFLICT (package_code) DO NOTHING
                """, (new_code,))
                conn.commit()
                flash(f"تم إضافة باكدج جديد: {new_code}")
        else:
            cur.execute("SELECT id FROM package_definitions")
            all_ids = [r["id"] for r in cur.fetchall()]
            for pid in all_ids:
                cur.execute("""
                    UPDATE package_definitions SET
                        includes_visa = %s, includes_investment = %s,
                        includes_approval = %s, includes_ticket = %s
                    WHERE id = %s
                """, (
                    1 if request.form.get(f"visa_{pid}") else 0,
                    1 if request.form.get(f"investment_{pid}") else 0,
                    1 if request.form.get(f"approval_{pid}") else 0,
                    1 if request.form.get(f"ticket_{pid}") else 0,
                    pid,
                ))
            conn.commit()
            flash("تم حفظ التعديلات")

    cur.execute("SELECT id, package_code, includes_visa, includes_investment, includes_approval, includes_ticket "
                "FROM package_definitions ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return render_template("packages.html", rows=rows)


@app.route("/prices/sell", methods=["GET", "POST"])
@login_required
def sell_prices_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        for key, value in request.form.items():
            if key.startswith("price_"):
                row_id = key.replace("price_", "")
                try:
                    price = float(value or 0)
                except ValueError:
                    price = 0
                cur.execute("UPDATE total_sell_prices SET total_price = %s WHERE id = %s", (price, row_id))
        conn.commit()
        flash("تم حفظ التعديلات")
    cur.execute("""
        SELECT id, date_from, date_to, package_code, port, destination, category, total_price
        FROM total_sell_prices ORDER BY package_code, port, destination, category
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("sell_prices.html", rows=rows)


@app.route("/bookings/period", methods=["GET", "POST"])
@login_required
def period_bookings_page():
    rows = []
    date_from = request.values.get("from", "")
    date_to = request.values.get("to", "")
    if date_from and date_to:
        conn = get_connection(dict_cursor=True)
        cur = conn.cursor()
        if request.method == "POST" and request.form.get("save") == "1":
            for key, value in request.form.items():
                if key.startswith("agent_"):
                    sid = key.replace("agent_", "")
                    cur.execute("UPDATE sales SET agent = %s WHERE id = %s", (value, sid))
                elif key.startswith("package_"):
                    sid = key.replace("package_", "")
                    cur.execute("UPDATE sales SET package_code = %s WHERE id = %s", (value, sid))
            conn.commit()
            flash("تم حفظ التعديلات")
        cur.execute("""
            SELECT id, name, national_id, agent, package_code, port, destination,
                   flight_number, total_sales, total_cost, airline, departure_date
            FROM sales WHERE submission_date BETWEEN %s AND %s ORDER BY id
        """, (date_from, date_to))
        rows = cur.fetchall()
        conn.close()
    return render_template("period_bookings.html", rows=rows, date_from=date_from, date_to=date_to,
                            agents=get_names("agents"), packages=get_package_codes())


def get_package_codes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT package_code FROM package_definitions ORDER BY id")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()
    return codes


def get_known_ports():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT port FROM ticket_costs WHERE port != ''")
    ports = [r[0] for r in cur.fetchall()]
    conn.close()
    return ports


def get_known_destinations():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT destination FROM ticket_costs WHERE destination != ''")
    dests = [r[0] for r in cur.fetchall()]
    conn.close()
    return dests


@app.route("/routes/new", methods=["GET", "POST"])
@login_required
def new_route_page():
    result = None
    if request.method == "POST":
        port = request.form.get("port", "").strip()
        dest = request.form.get("destination", "").strip()
        airline = request.form.get("airline", "").strip()
        if port and dest and airline:
            result = add_new_route.add_route(port, dest, airline)
    return render_template("new_route.html", result=result,
                            ports=get_known_ports(), destinations=get_known_destinations(),
                            airlines=get_names("airlines"))


@app.route("/charter", methods=["GET", "POST"])
@login_required
def charter_page():
    result = None
    if request.method == "POST":
        flight = request.form.get("flight_number", "").strip()
        dep = request.form.get("departure_date", "").strip()
        airline = request.form.get("airline", "").strip()
        try:
            cost = float(request.form.get("total_cost", 0))
        except ValueError:
            cost = 0
        result = add_charter_booking.add_booking(flight, dep, airline, cost)
        if result["success"] and request.form.get("recalculate"):
            recalc = add_charter_booking.recalculate_flight(flight, dep)
            result["message"] += f" تم إعادة حساب {recalc['updated']} حجز موجود بالفعل على هذه الرحلة."
    return render_template("charter.html", result=result, airlines=get_names("airlines"))


@app.route("/prices/change", methods=["GET", "POST"])
@login_required
def price_change_page():
    result = None
    if request.method == "POST":
        change_type = request.form.get("change_type")
        package = request.form.get("package", "").strip()
        category = request.form.get("category", "").strip()
        eff_date = request.form.get("effective_date", "").strip()
        try:
            value = float(request.form.get("value", 0))
        except ValueError:
            value = 0
        if change_type == "sell":
            port = request.form.get("port", "").strip()
            dest = request.form.get("destination", "").strip()
            add_price_change.add_sell_price_change(package, port, dest, category, value, eff_date)
            result = f"تم تسجيل سعر بيع جديد ({value:,.0f}) سارٍ من {eff_date}."
        else:
            component = request.form.get("component", "").strip()
            add_price_change.add_service_cost_change(package, component, category, value, eff_date)
            result = f"تم تسجيل تكلفة جديدة ({value:,.0f}) سارية من {eff_date}."
    return render_template("price_change.html", result=result, packages=get_package_codes(),
                            ports=get_known_ports(), destinations=get_known_destinations())


@app.route("/health-check")
@login_required
def health_check_page():
    issues = health_check.run_health_check()
    return render_template("health_check.html", issues=issues)


@app.route("/undo-import", methods=["GET", "POST"])
@login_required
def undo_import_page():
    last = undo_last_import.get_last_import()
    result = None
    if request.method == "POST":
        result = undo_last_import.undo_last_import()
        last = undo_last_import.get_last_import()
    return render_template("undo_import.html", last=last, result=result)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
