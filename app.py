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
import users as users_module
import recalculate_period
import populate_sell_price_rows
from flask import send_file

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")


def gform(male_form, female_form):
    """يرجّع الصيغة الصحيحة (مذكر/مؤنث) حسب جنس المستخدم المسجّل دخوله دلوقتي -
    تُستخدم فى القوالب كده: {{ gform('جاهز', 'جاهزة') }}
    (الاسم مش 'g' عشان g محجوز فعليًا فى Flask لكائن السياق الخاص بيه)"""
    return female_form if session.get("gender", "female") == "female" else male_form


app.jinja_env.globals["gform"] = gform


def greeting_name():
    """اسم المستخدم الحالي لمخاطبته به فى الرسائل، أو 'صديقى/صديقتى' لو مفيش اسم مسجّل"""
    return session.get("display_name") or gform("صديقى", "صديقتى")


app.jinja_env.globals["greeting_name"] = greeting_name


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("هذه الصفحة للمدير فقط")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


def log(action, details=""):
    """يسجّل نشاط المستخدم الحالي فى سجل النشاط"""
    if session.get("username"):
        users_module.log_activity(session["username"], action, details)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = users_module.verify_login(username, password)
        if user:
            session["username"] = user["username"]
            session["display_name"] = user["display_name"]
            session["is_admin"] = bool(user["is_admin"])
            session["gender"] = user.get("gender") or "female"
            users_module.log_activity(username, "تسجيل دخول")
            return redirect(url_for("dashboard"))
        flash("اسم المستخدم أو كلمة السر غلط")
    return render_template("login.html")


@app.route("/logout")
def logout():
    if session.get("username"):
        users_module.log_activity(session["username"], "تسجيل خروج")
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
    debts = reports.get_debts_summary()
    return render_template("dashboard.html", total_clients=total_clients,
                            last_import=last_import, zero_price=zero_price, debts=debts)


@app.route("/debts")
@login_required
def debts_page():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")
    summary = reports.get_debts_summary(date_from, date_to)
    return render_template("debts.html", summary=summary, date_from=date_from, date_to=date_to)


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
            result = import_daily_submissions.import_file(upload_path, performed_by=session.get("username", ""))
            os.remove(upload_path)
            if result.get("success"):
                log("استيراد يومي", f"استوردت {result['added']} عميل من ملف '{file.filename}'")
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


def get_names(table, cur=None):
    def extract(rows):
        return [r["name"] if isinstance(r, dict) else r[0] for r in rows]
    if cur is not None:
        cur.execute(f"SELECT name FROM {table} ORDER BY name")
        return extract(cur.fetchall())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT name FROM {table} ORDER BY name")
    names = extract(cur.fetchall())
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
        account_type = request.form.get("account_type", "نقدي")
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
                                      payment_method, account_type, related_agent, related_partner,
                                      incoming, outgoing)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (tdate, desc, movement_type, party, payment_method, account_type, related_agent,
                  related_partner, incoming, outgoing))
            conn.commit()
            conn.close()
            saved = {"movement_type": movement_type, "party": party, "amount": amount,
                      "account_type": account_type}
            log("حركة خزنة", f"{movement_type} - {party} - {amount:,.0f} ({account_type})")
        else:
            flash("المبلغ لازم يكون أكبر من صفر")

    conn = get_connection()
    cur = conn.cursor()
    render = render_template("treasury.html", movement_types=MOVEMENT_TYPES,
                              agents=get_names("agents", cur), airlines=get_names("airlines", cur),
                              visa_suppliers=get_names("visa_suppliers", cur),
                              investment_suppliers=get_names("investment_suppliers", cur),
                              partners=get_names("partners", cur), saved=saved)
    conn.close()
    return render


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
    _conn = get_connection()
    _cur = _conn.cursor()
    all_parties = get_names("agents", _cur) + get_names("airlines", _cur) + \
                  get_names("visa_suppliers", _cur) + get_names("investment_suppliers", _cur) + \
                  get_names("partners", _cur)
    _conn.close()
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
            log("تسجيل غياب", f"الرقم القومى {nid}, تاريخ {dep}, غرامة {penalty:,.0f}")
        else:
            message = mark_no_show.unmark_no_show(nid, dep)
            log("إلغاء غياب", f"الرقم القومى {nid}, تاريخ {dep}")
    return render_template("noshow.html", message=message)


@app.route("/investment-assignment", methods=["GET", "POST"])
@login_required
def investment_assignment_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        assignment_type = request.form.get("assignment_type")
        supplier = request.form.get("supplier", "").strip()
        date_from = request.form.get("date_from") or "2020-01-01"
        date_to = request.form.get("date_to") or "2099-12-31"
        if assignment_type == "airline":
            airline = request.form.get("airline", "").strip()
            cur.execute("""
                INSERT INTO investment_supplier_assignment(date_from, date_to, airline, supplier)
                VALUES (%s,%s,%s,%s)
            """, (date_from, date_to, airline, supplier))
            log("تخصيص مورد استثمار (شركة طيران)", f"{airline} -> {supplier}")
        else:
            port = request.form.get("port", "").strip()
            dest = request.form.get("destination", "").strip()
            cur.execute("""
                INSERT INTO investment_supplier_assignment(date_from, date_to, port, destination, supplier)
                VALUES (%s,%s,%s,%s,%s)
            """, (date_from, date_to, port, dest, supplier))
            log("تخصيص مورد استثمار (خط سير)", f"{port} -> {dest} : {supplier}")
        conn.commit()
        flash("تم إضافة التخصيص")

    cur.execute("""
        SELECT id, date_from, date_to, airline, port, destination, supplier
        FROM investment_supplier_assignment ORDER BY id DESC
    """)
    rows = cur.fetchall()
    airlines = get_names("airlines", cur)
    suppliers = get_names("investment_suppliers", cur)
    ports = get_known_ports(cur)
    destinations = get_known_destinations(cur)
    conn.close()
    return render_template("investment_assignment.html", rows=rows,
                            airlines=airlines, suppliers=suppliers,
                            ports=ports, destinations=destinations)


@app.route("/investment-assignment/<int:row_id>/delete", methods=["POST"])
@login_required
def investment_assignment_delete(row_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM investment_supplier_assignment WHERE id = %s", (row_id,))
    conn.commit()
    conn.close()
    log("حذف تخصيص مورد استثمار", f"id={row_id}")
    flash("تم الحذف")
    return redirect(url_for("investment_assignment_page"))


@app.route("/opening-balances", methods=["GET", "POST"])
@login_required
def opening_balances_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()

    if request.method == "POST":
        section = request.form.get("section")
        if section == "agents":
            for name in get_names("agents", cur):
                key = name.replace(" ", "_")
                gross = float(request.form.get(f"gross_{key}", 0) or 0)
                discount = float(request.form.get(f"discount_{key}", 0) or 0)
                collected = float(request.form.get(f"collected_{key}", 0) or 0)
                cur.execute("""
                    INSERT INTO opening_balances_agents(agent_name, gross_sales, discount, collected)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (agent_name) DO UPDATE SET
                        gross_sales = EXCLUDED.gross_sales, discount = EXCLUDED.discount,
                        collected = EXCLUDED.collected
                """, (name, gross, discount, collected))
        elif section in ("visa", "investment"):
            table = "opening_balances_visa" if section == "visa" else "opening_balances_investment"
            ref_table = "visa_suppliers" if section == "visa" else "investment_suppliers"
            for name in get_names(ref_table, cur):
                key = name.replace(" ", "_")
                gross = float(request.form.get(f"gross_{key}", 0) or 0)
                discount = float(request.form.get(f"discount_{key}", 0) or 0)
                paid = float(request.form.get(f"paid_{key}", 0) or 0)
                cur.execute(f"""
                    INSERT INTO {table}(supplier_name, gross_purchases, discount, paid)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (supplier_name) DO UPDATE SET
                        gross_purchases = EXCLUDED.gross_purchases, discount = EXCLUDED.discount,
                        paid = EXCLUDED.paid
                """, (name, gross, discount, paid))
        elif section == "airlines":
            for name in get_names("airlines", cur):
                key = name.replace(" ", "_")
                revenue = float(request.form.get(f"revenue_{key}", 0) or 0)
                cost = float(request.form.get(f"cost_{key}", 0) or 0)
                discount = float(request.form.get(f"discount_{key}", 0) or 0)
                paid = float(request.form.get(f"paid_{key}", 0) or 0)
                cur.execute("""
                    INSERT INTO opening_balances_airlines(airline_name, gross_revenue, gross_cost, discount, paid)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (airline_name) DO UPDATE SET
                        gross_revenue = EXCLUDED.gross_revenue, gross_cost = EXCLUDED.gross_cost,
                        discount = EXCLUDED.discount, paid = EXCLUDED.paid
                """, (name, revenue, cost, discount, paid))
        conn.commit()
        flash("تم حفظ الأرصدة الافتتاحية")

    def load_section(names, table, key_col, value_cols):
        cur.execute(f"SELECT * FROM {table}")
        existing = {r[key_col]: r for r in cur.fetchall()}
        result = []
        for name in names:
            row = existing.get(name, {})
            result.append({"name": name, "key": name.replace(" ", "_"),
                            **{c: row.get(c, 0) for c in value_cols}})
        return result

    agents_data = load_section(get_names("agents", cur), "opening_balances_agents", "agent_name",
                                ["gross_sales", "discount", "collected"])
    visa_data = load_section(get_names("visa_suppliers", cur), "opening_balances_visa", "supplier_name",
                              ["gross_purchases", "discount", "paid"])
    investment_data = load_section(get_names("investment_suppliers", cur), "opening_balances_investment",
                                    "supplier_name", ["gross_purchases", "discount", "paid"])
    airlines_data = load_section(get_names("airlines", cur), "opening_balances_airlines", "airline_name",
                                  ["gross_revenue", "gross_cost", "discount", "paid"])
    conn.close()

    return render_template("opening_balances.html", agents_data=agents_data, visa_data=visa_data,
                            investment_data=investment_data, airlines_data=airlines_data)


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


@app.route("/prices/sell/populate", methods=["GET", "POST"])
@login_required
def populate_sell_prices_page():
    result = None
    if request.method == "POST":
        selected = request.form.getlist("combo")
        keys = [tuple(k.split("||")) for k in selected]
        if keys:
            result = populate_sell_price_rows.apply_missing_combos(keys)
            log("تجهيز صفوف أسعار البيع", f"أضاف {result['added']} تركيبة جديدة بسعر صفر")
        else:
            flash("من فضلك اختاري تركيبة واحدة على الأقل")
    combos = populate_sell_price_rows.preview_missing_combos()
    return render_template("populate_sell_prices.html", combos=combos, result=result)


@app.route("/prices/sell", methods=["GET", "POST"])
@login_required
def sell_prices_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        changed = 0
        for key, value in request.form.items():
            if key.startswith("price_"):
                row_id = key.replace("price_", "")
                try:
                    price = float(value or 0)
                except ValueError:
                    price = 0
                cur.execute("UPDATE total_sell_prices SET total_price = %s WHERE id = %s", (price, row_id))
                changed += 1
            elif key.startswith("from_"):
                row_id = key.replace("from_", "")
                cur.execute("UPDATE total_sell_prices SET date_from = %s WHERE id = %s", (value, row_id))
            elif key.startswith("to_"):
                row_id = key.replace("to_", "")
                cur.execute("UPDATE total_sell_prices SET date_to = %s WHERE id = %s", (value, row_id))
        conn.commit()
        flash("تم حفظ التعديلات")
        log("تعديل أسعار البيع", f"عدّل {changed} صف/صفوف فى جدول أسعار البيع")
    cur.execute("""
        SELECT id, date_from, date_to, package_code, port, destination, category, total_price
        FROM total_sell_prices ORDER BY package_code, port, destination, category
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("sell_prices.html", rows=rows)


@app.route("/costs/service", methods=["GET", "POST"])
@login_required
def service_costs_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        if request.form.get("action") == "add":
            cur.execute("""
                INSERT INTO service_costs(date_from, date_to, package_code, component, category, cost)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (request.form.get("new_from") or "2020-01-01", request.form.get("new_to") or "2099-12-31",
                  request.form.get("new_package"), request.form.get("new_component"),
                  request.form.get("new_category"), float(request.form.get("new_cost") or 0)))
            conn.commit()
            flash("تم إضافة صف جديد")
            log("إضافة تكلفة خدمة", f"{request.form.get('new_package')} / {request.form.get('new_component')}")
        else:
            changed = 0
            for key, value in request.form.items():
                if key.startswith("cost_"):
                    row_id = key.replace("cost_", "")
                    try:
                        cost = float(value or 0)
                    except ValueError:
                        cost = 0
                    cur.execute("UPDATE service_costs SET cost = %s WHERE id = %s", (cost, row_id))
                    changed += 1
                elif key.startswith("from_"):
                    row_id = key.replace("from_", "")
                    cur.execute("UPDATE service_costs SET date_from = %s WHERE id = %s", (value, row_id))
                elif key.startswith("to_"):
                    row_id = key.replace("to_", "")
                    cur.execute("UPDATE service_costs SET date_to = %s WHERE id = %s", (value, row_id))
            conn.commit()
            flash("تم حفظ التعديلات")
            log("تعديل تكلفة خدمات", f"عدّل {changed} صف/صفوف")
    cur.execute("""
        SELECT id, date_from, date_to, package_code, component, category, cost
        FROM service_costs ORDER BY package_code, component, category
    """)
    rows = cur.fetchall()
    packages = get_package_codes(cur)
    conn.close()
    return render_template("service_costs.html", rows=rows, packages=packages)


@app.route("/costs/ticket", methods=["GET", "POST"])
@login_required
def ticket_costs_page():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if request.method == "POST":
        if request.form.get("action") == "add":
            cur.execute("""
                INSERT INTO ticket_costs(date_from, date_to, port, destination, airline,
                                          cost_adult, cost_female, cost_child, cost_infant)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (request.form.get("new_from") or "2020-01-01", request.form.get("new_to") or "2099-12-31",
                  request.form.get("new_port"), request.form.get("new_destination"),
                  request.form.get("new_airline"),
                  float(request.form.get("new_adult") or 0), float(request.form.get("new_female") or 0),
                  float(request.form.get("new_child") or 0), float(request.form.get("new_infant") or 0)))
            conn.commit()
            flash("تم إضافة صف جديد")
            log("إضافة تكلفة تذاكر", f"{request.form.get('new_port')} -> {request.form.get('new_destination')} "
                                     f"({request.form.get('new_airline')})")
        else:
            changed = 0
            for key, value in request.form.items():
                for prefix, col in [("adult_", "cost_adult"), ("female_", "cost_female"),
                                     ("child_", "cost_child"), ("infant_", "cost_infant")]:
                    if key.startswith(prefix):
                        row_id = key.replace(prefix, "")
                        try:
                            cost = float(value or 0)
                        except ValueError:
                            cost = 0
                        cur.execute(f"UPDATE ticket_costs SET {col} = %s WHERE id = %s", (cost, row_id))
                        changed += 1
                if key.startswith("from_"):
                    row_id = key.replace("from_", "")
                    cur.execute("UPDATE ticket_costs SET date_from = %s WHERE id = %s", (value, row_id))
                elif key.startswith("to_"):
                    row_id = key.replace("to_", "")
                    cur.execute("UPDATE ticket_costs SET date_to = %s WHERE id = %s", (value, row_id))
            conn.commit()
            flash("تم حفظ التعديلات")
            log("تعديل تكلفة تذاكر", f"عدّل {changed} قيمة/قيم")
    cur.execute("""
        SELECT id, date_from, date_to, port, destination, airline, cost_adult, cost_female, cost_child, cost_infant
        FROM ticket_costs ORDER BY port, destination, airline
    """)
    rows = cur.fetchall()
    ports = get_known_ports(cur)
    destinations = get_known_destinations(cur)
    airlines = get_names("airlines", cur)
    conn.close()
    return render_template("ticket_costs.html", rows=rows, ports=ports,
                            destinations=destinations, airlines=airlines)


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
        _conn = get_connection()
        _cur = _conn.cursor()
        agents = get_names("agents", _cur)
        packages = get_package_codes(_cur)
        _conn.close()
    else:
        agents = get_names("agents")
        packages = get_package_codes()
    return render_template("period_bookings.html", rows=rows, date_from=date_from, date_to=date_to,
                            agents=agents, packages=packages)


def get_package_codes(cur=None):
    def extract(rows):
        return [r["package_code"] if isinstance(r, dict) else r[0] for r in rows]
    if cur is not None:
        cur.execute("SELECT package_code FROM package_definitions ORDER BY id")
        return extract(cur.fetchall())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT package_code FROM package_definitions ORDER BY id")
    codes = extract(cur.fetchall())
    conn.close()
    return codes


def get_known_ports(cur=None):
    def extract(rows):
        return [r["port"] if isinstance(r, dict) else r[0] for r in rows]
    if cur is not None:
        cur.execute("SELECT DISTINCT port FROM ticket_costs WHERE port != ''")
        return extract(cur.fetchall())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT port FROM ticket_costs WHERE port != ''")
    ports = extract(cur.fetchall())
    conn.close()
    return ports


def get_known_destinations(cur=None):
    def extract(rows):
        return [r["destination"] if isinstance(r, dict) else r[0] for r in rows]
    if cur is not None:
        cur.execute("SELECT DISTINCT destination FROM ticket_costs WHERE destination != ''")
        return extract(cur.fetchall())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT destination FROM ticket_costs WHERE destination != ''")
    dests = extract(cur.fetchall())
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
            log("إضافة خط سير", f"{port} -> {dest} ({airline})")
    _conn = get_connection()
    _cur = _conn.cursor()
    ports = get_known_ports(_cur)
    destinations = get_known_destinations(_cur)
    airlines = get_names("airlines", _cur)
    _conn.close()
    return render_template("new_route.html", result=result,
                            ports=ports, destinations=destinations, airlines=airlines)


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
        log("حجز شارتر", f"رحلة {flight} فى {dep}, شركة {airline}, تكلفة {cost:,.0f}")
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
            log("سعر بيع جديد", f"{package} / {port}->{dest} / {category}: {value:,.0f} من {eff_date}")
        else:
            component = request.form.get("component", "").strip()
            add_price_change.add_service_cost_change(package, component, category, value, eff_date)
            result = f"تم تسجيل تكلفة جديدة ({value:,.0f}) سارية من {eff_date}."
            log("تكلفة جديدة", f"{package} / {component} / {category}: {value:,.0f} من {eff_date}")
    _conn = get_connection()
    _cur = _conn.cursor()
    packages = get_package_codes(_cur)
    ports = get_known_ports(_cur)
    destinations = get_known_destinations(_cur)
    _conn.close()
    return render_template("price_change.html", result=result, packages=packages,
                            ports=ports, destinations=destinations)


@app.route("/recalculate", methods=["GET", "POST"])
@login_required
def recalculate_page():
    result = None
    if request.method == "POST":
        date_from = request.form.get("date_from") or "2020-01-01"
        date_to = request.form.get("date_to") or "2099-12-31"
        force = bool(request.form.get("force"))
        result = recalculate_period.recalculate(date_from, date_to, force=force)
        if not result.get("aborted"):
            log("إعادة حساب فترة", f"من {date_from} إلى {date_to}: {result['updated']} حجز")
    return render_template("recalculate.html", result=result)


@app.route("/reports/sales-by-period")
@login_required
def sales_by_period_page():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, national_id, agent, package_code, port, destination,
               departure_date, submission_date, total_sales, total_cost, net_profit
        FROM sales WHERE submission_date BETWEEN %s AND %s ORDER BY submission_date
    """, (date_from, date_to))
    rows = cur.fetchall()
    totals = {
        "sales": sum(r["total_sales"] for r in rows),
        "cost": sum(r["total_cost"] for r in rows),
        "profit": sum(r["net_profit"] for r in rows),
    }
    conn.close()
    return render_template("sales_by_period.html", rows=rows, totals=totals,
                            date_from=date_from, date_to=date_to)


def _compute_treasury_report(date_from, date_to):
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    balances = reports.get_account_balances(cur, date_from, date_to)
    cur.execute("""
        SELECT * FROM treasury WHERE transaction_date BETWEEN %s AND %s ORDER BY transaction_date, id
    """, (date_from, date_to))
    movements = cur.fetchall()
    running_by_account = {"نقدي": 0, "بنك": 0}
    processed = []
    for m in movements:
        is_direct = m["payment_method"] == "مباشر (بين العميل والمورد)"
        acct = m.get("account_type") or "نقدي"
        if not is_direct:
            running_by_account[acct] = running_by_account.get(acct, 0) + (m["incoming"] or 0) - (m["outgoing"] or 0)
        processed.append({**m, "affects_cash": not is_direct,
                            "running_balance": running_by_account.get(acct, 0)})
    conn.close()
    return processed, balances


@app.route("/reports/treasury")
@login_required
def treasury_report_page():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")
    processed, balances = _compute_treasury_report(date_from, date_to)
    return render_template("treasury_report.html", movements=processed, balances=balances,
                            date_from=date_from, date_to=date_to)


@app.route("/reports/treasury/download")
@login_required
def treasury_report_download():
    date_from = request.args.get("from", "2020-01-01")
    date_to = request.args.get("to", "2099-12-31")
    processed, balances = _compute_treasury_report(date_from, date_to)
    buf = excel_export.build_treasury_report_xlsx(processed, balances, date_from, date_to)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return send_file(buf, as_attachment=True, download_name=f"تقرير_حركة_الخزنة_{timestamp}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
        if result.get("success"):
            log("تراجع عن استيراد", f"حذف {result['removed']} عميل من '{result['source_file']}'")
    return render_template("undo_import.html", last=last, result=result)


@app.route("/delete-day", methods=["GET", "POST"])
@login_required
def delete_day_page():
    result = None
    preview = None
    if request.method == "POST":
        target_date = request.form.get("target_date", "").strip()
        conn = get_connection(dict_cursor=True)
        cur = conn.cursor()
        if request.form.get("action") == "preview":
            cur.execute("""
                SELECT id, name, national_id, agent, package_code, total_sales
                FROM sales WHERE submission_date = %s ORDER BY id
            """, (target_date,))
            preview = {"date": target_date, "rows": cur.fetchall()}
        elif request.form.get("action") == "confirm_delete":
            cur.execute("SELECT COUNT(*) AS cnt FROM sales WHERE submission_date = %s", (target_date,))
            count = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM sales WHERE submission_date = %s", (target_date,))
            conn.commit()
            log("حذف تقديمات يوم", f"حذف {count} حجز بتاريخ تقديم {target_date}")
            result = {"deleted": count, "date": target_date}
        conn.close()
    return render_template("delete_day.html", result=result, preview=preview)


@app.route("/activity-log")
@login_required
@admin_required
def activity_log_page():
    filter_user = request.args.get("user", "").strip() or None
    entries = users_module.get_activity_log(username_filter=filter_user)
    all_users = users_module.list_users()
    return render_template("activity_log.html", entries=entries, all_users=all_users, filter_user=filter_user)


@app.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users_page():
    message = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        display_name = request.form.get("display_name", "").strip()
        is_admin = bool(request.form.get("is_admin"))
        gender = request.form.get("gender", "female")
        if username and password:
            try:
                users_module.create_user(username, password, display_name, is_admin, gender)
                log("إضافة مستخدم", f"أضاف مستخدم جديد: {username}")
                message = f"تم إنشاء المستخدم '{username}' بنجاح."
            except Exception as e:
                message = f"فشل الإنشاء (ربما الاسم مستخدم بالفعل): {e}"
    all_users = users_module.list_users()
    return render_template("users.html", all_users=all_users, message=message)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user_page(user_id):
    message = None
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        is_admin = bool(request.form.get("is_admin"))
        gender = request.form.get("gender", "female")
        new_password = request.form.get("new_password", "").strip()
        users_module.update_user(user_id, display_name, is_admin, gender)
        if new_password:
            users_module.admin_reset_password(user_id, new_password)
            log("تعديل مستخدم", f"عدّل بيانات وغيّر كلمة سر المستخدم id={user_id}")
        else:
            log("تعديل مستخدم", f"عدّل بيانات المستخدم id={user_id}")
        flash("تم حفظ التعديلات")
        return redirect(url_for("users_page"))
    user = users_module.get_user_by_id(user_id)
    if not user:
        flash("المستخدم غير موجود")
        return redirect(url_for("users_page"))
    return render_template("edit_user.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user_page(user_id):
    user = users_module.get_user_by_id(user_id)
    if user and user["username"] == session.get("username"):
        flash("متقدريش تحذفي حسابك الشخصي وانتِ داخلة بيه")
        return redirect(url_for("users_page"))
    if user:
        users_module.delete_user(user_id)
        log("حذف مستخدم", f"حذف المستخدم: {user['username']}")
        flash(f"تم حذف المستخدم '{user['username']}'")
    return redirect(url_for("users_page"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password_page():
    message = None
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new1 = request.form.get("new_password", "")
        new2 = request.form.get("confirm_password", "")
        user = users_module.verify_login(session["username"], current)
        if not user:
            flash("كلمة السر الحالية غلط")
        elif len(new1) < 6:
            flash("كلمة السر الجديدة لازم تكون 6 حروف/أرقام على الأقل")
        elif new1 != new2:
            flash("كلمة السر الجديدة والتأكيد مش متطابقين")
        else:
            users_module.change_password(session["username"], new1)
            log("تغيير كلمة السر")
            message = "تم تغيير كلمة السر بنجاح."
    return render_template("change_password.html", message=message)


@app.route("/clients/search")
@login_required
def client_search_page():
    query = request.args.get("q", "").strip()
    results = []
    if query:
        conn = get_connection(dict_cursor=True)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, national_id, departure_date, agent, package_code, category
            FROM sales WHERE name ILIKE %s OR national_id ILIKE %s
            ORDER BY id DESC LIMIT 30
        """, (f"%{query}%", f"%{query}%"))
        results = cur.fetchall()
        conn.close()
    return render_template("client_search.html", query=query, results=results)


@app.route("/clients/<int:client_id>", methods=["GET", "POST"])
@login_required
def client_edit_page(client_id):
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()

    if request.method == "POST":
        new_name = request.form.get("name", "").strip()
        new_agent = request.form.get("agent", "").strip()
        new_package = request.form.get("package", "").strip()
        new_category = request.form.get("category", "").strip()

        cur.execute("""
            SELECT date_of_birth, national_id, passport_number, port, destination,
                   flight_number, departure_date, submission_date
            FROM sales WHERE id = %s
        """, (client_id,))
        row = cur.fetchone()
        from pricing_engine import calculate_row
        import psycopg2.extensions
        # لازم نحدد cursor_factory بالتحديد هنا - الاتصال نفسه معمول عليه
        # RealDictCursor كافتراضي، فمجرد conn.cursor() هيورّث نفس النوع برضه
        plain_cur = conn.cursor(cursor_factory=psycopg2.extensions.cursor)
        recalculated = calculate_row(
            plain_cur, new_name, row["date_of_birth"], row["national_id"], row["passport_number"],
            row["port"], row["destination"], row["flight_number"], row["departure_date"],
            row["submission_date"], new_agent, new_category, new_package, row_already_in_db=True
        )
        cur.execute("""
            UPDATE sales SET
                name = %(name)s, agent = %(agent)s, package_code = %(package_code)s, category = %(category)s,
                service_price = %(service_price)s, ticket_price = %(ticket_price)s, total_sales = %(total_sales)s,
                visa_cost = %(visa_cost)s, investment_cost = %(investment_cost)s, approval_cost = %(approval_cost)s,
                service_cost_total = %(service_cost_total)s, ticket_cost = %(ticket_cost)s,
                total_cost = %(total_cost)s, net_profit = %(net_profit)s,
                investment_supplier = %(investment_supplier)s
            WHERE id = %(client_id)s
        """, {**recalculated, "client_id": client_id})
        conn.commit()
        log("تعديل حجز", f"عدّل بيانات العميل (id={client_id}): وكيل={new_agent}, باكدج={new_package}")
        flash("تم حفظ التعديلات وإعادة الحساب")

    cur.execute("SELECT * FROM sales WHERE id = %s", (client_id,))
    client = cur.fetchone()
    if not client:
        conn.close()
        flash("العميل غير موجود")
        return redirect(url_for("client_search_page"))
    agents = get_names("agents", cur)
    packages = get_package_codes(cur)
    conn.close()
    return render_template("client_edit.html", client=client,
                            agents=agents, packages=packages)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
