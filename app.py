"""
app.py - Main Flask web application. Run locally with `python app.py` for
testing, or deploy to Render (which runs it via gunicorn automatically).
"""
import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

from db import get_connection
import reports
import import_daily_submissions

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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
