"""
reports.py - Query functions that compute account balances for agents,
suppliers, and airlines. Each function combines THREE sources reliably
(instead of relying on fragile cross-sheet text-matching like the old
Excel system did):

    1) Sales attributed to the party (from the `sales` table)
    2) Treasury movements for the party (collections/payments actually
       logged in the treasury table, INCLUDING direct payments recorded
       against `related_agent` for the "مباشر بين العميل والمورد" case)
    3) Their opening balance (from the opening_balances_* tables)

All matching is done through proper SQL WHERE clauses against indexed
columns - not fragile cross-sheet formula references - so a direct payment
recorded for an agent will always be picked up correctly.
"""
from db import get_connection


def get_agent_account(cur, agent_name, date_from="2020-01-01", date_to="2099-12-31"):
    """Returns dict: total_sales, total_collected, balance, for one agent,
    covering their submission-date-filtered sales, treasury collections
    (both normal AND direct-to-supplier payments credited to them), and
    their opening balance."""

    cur.execute("""
        SELECT COALESCE(SUM(total_sales), 0) FROM sales
        WHERE agent = %s AND submission_date BETWEEN %s AND %s
    """, (agent_name, date_from, date_to))
    period_sales = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(incoming), 0) FROM treasury
        WHERE movement_type = 'تحصيل من عميل' AND party_name = %s
              AND transaction_date BETWEEN %s AND %s
    """, (agent_name, date_from, date_to))
    normal_collections = cur.fetchone()[0]

    # السداد المباشر (بين العميل والمورد): مبلغ خرج مباشرة للمورد لكن يُحسب
    # كأنه "تحصيل" لصالح هذا الوكيل، لأنه أصلًا كان مستحقًا منه
    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type LIKE 'سداد لمورد%%' AND payment_method = 'مباشر (بين العميل والمورد)'
              AND related_agent = %s AND transaction_date BETWEEN %s AND %s
    """, (agent_name, date_from, date_to))
    direct_payments = cur.fetchone()[0]

    total_collected = normal_collections + direct_payments

    cur.execute("SELECT gross_sales, discount, collected FROM opening_balances_agents WHERE agent_name = %s",
                (agent_name,))
    row = cur.fetchone()
    if row:
        gross, discount, opening_collected = row
        opening_net_sales = gross - discount
    else:
        opening_net_sales = 0
        opening_collected = 0

    total_sales_all = period_sales + opening_net_sales
    total_collected_all = total_collected + opening_collected
    balance = total_sales_all - total_collected_all

    return {
        "agent_name": agent_name,
        "period_sales": period_sales,
        "opening_net_sales": opening_net_sales,
        "total_sales": total_sales_all,
        "normal_collections": normal_collections,
        "direct_payments_credited": direct_payments,
        "opening_collected": opening_collected,
        "total_collected": total_collected_all,
        "balance": balance,
    }


def get_visa_supplier_account(cur, supplier_name, date_from="2020-01-01", date_to="2099-12-31"):
    """تكلفة التأشيرات مقسّمة بالتساوى على الموردين الثلاثة (نفس منطق الإكسيل) +
    السداد الفعلى له (سواء عن طريق الخزنة أو مباشرة من العميل) + رصيده الافتتاحى"""
    cur.execute("SELECT COUNT(*) FROM visa_suppliers")
    n_suppliers = cur.fetchone()[0] or 1

    cur.execute("""
        SELECT COALESCE(SUM(visa_cost), 0) FROM sales
        WHERE submission_date BETWEEN %s AND %s
    """, (date_from, date_to))
    total_visa_cost = cur.fetchone()[0]
    period_cost_share = total_visa_cost / n_suppliers

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'سداد لمورد - تأشيرات' AND party_name = %s
              AND (payment_method IS NULL OR payment_method != 'مباشر (بين العميل والمورد)')
              AND transaction_date BETWEEN %s AND %s
    """, (supplier_name, date_from, date_to))
    paid_via_treasury = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'سداد لمورد - تأشيرات' AND party_name = %s
              AND payment_method = 'مباشر (بين العميل والمورد)'
              AND transaction_date BETWEEN %s AND %s
    """, (supplier_name, date_from, date_to))
    paid_directly = cur.fetchone()[0]

    total_paid = paid_via_treasury + paid_directly

    cur.execute("SELECT gross_purchases, discount, paid FROM opening_balances_visa WHERE supplier_name = %s",
                (supplier_name,))
    row = cur.fetchone()
    if row:
        gross, discount, opening_paid = row
        opening_net_cost = gross - discount
    else:
        opening_net_cost = 0
        opening_paid = 0

    total_cost_all = period_cost_share + opening_net_cost
    total_paid_all = total_paid + opening_paid
    balance = total_cost_all - total_paid_all

    return {
        "supplier_name": supplier_name,
        "period_cost_share": period_cost_share,
        "opening_net_cost": opening_net_cost,
        "total_cost": total_cost_all,
        "paid_via_treasury": paid_via_treasury,
        "paid_directly": paid_directly,
        "opening_paid": opening_paid,
        "total_paid": total_paid_all,
        "balance": balance,
    }

def get_investment_supplier_account(cur, supplier_name, date_from="2020-01-01", date_to="2099-12-31"):
    """التكلفة تُنسب لهذا المورد تحديدًا (عمود investment_supplier فى المبيعات)، مفلترة
    حسب تاريخ المغادرة (وليس التقديم) - نفس منطق الإكسيل تمامًا"""
    cur.execute("""
        SELECT COALESCE(SUM(investment_cost), 0) FROM sales
        WHERE investment_supplier = %s AND departure_date BETWEEN %s AND %s
    """, (supplier_name, date_from, date_to))
    period_cost = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'سداد لمورد - استثمار' AND party_name = %s
              AND transaction_date BETWEEN %s AND %s
    """, (supplier_name, date_from, date_to))
    paid = cur.fetchone()[0]

    cur.execute("SELECT gross_purchases, discount, paid FROM opening_balances_investment WHERE supplier_name = %s",
                (supplier_name,))
    row = cur.fetchone()
    if row:
        gross, discount, opening_paid = row
        opening_net_cost = gross - discount
    else:
        opening_net_cost, opening_paid = 0, 0

    total_cost = period_cost + opening_net_cost
    total_paid = paid + opening_paid

    return {
        "supplier_name": supplier_name,
        "period_cost": period_cost,
        "opening_net_cost": opening_net_cost,
        "total_cost": total_cost,
        "paid": paid,
        "opening_paid": opening_paid,
        "total_paid": total_paid,
        "balance": total_cost - total_paid,
    }


def get_airline_account(cur, airline_name, date_from="2020-01-01", date_to="2099-12-31"):
    """إيراد وتكلفة التذاكر منسوبان لهذه الشركة تحديدًا، مفلترة حسب تاريخ المغادرة
    (وليس التقديم) - نفس منطق الإكسيل تمامًا"""
    cur.execute("""
        SELECT COALESCE(SUM(total_sales), 0), COALESCE(SUM(ticket_cost), 0), COUNT(*)
        FROM sales WHERE airline = %s AND departure_date BETWEEN %s AND %s
    """, (airline_name, date_from, date_to))
    # ملحوظة: الإيراد هنا تقريبى (سعر البيع الإجمالى الجديد لا يفصل بين خدمة وتذكرة) -
    # لو محتاجة فصل دقيق للإيراد، محتاجين نتناقش إزاي نوزّع السعر الإجمالى على المكوّنات
    _, period_ticket_cost, ticket_count = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'سداد لمورد - تذاكر طيران' AND party_name = %s
              AND transaction_date BETWEEN %s AND %s
    """, (airline_name, date_from, date_to))
    paid = cur.fetchone()[0]

    cur.execute("SELECT gross_cost, discount, paid FROM opening_balances_airlines WHERE airline_name = %s",
                (airline_name,))
    row = cur.fetchone()
    if row:
        gross_cost, discount, opening_paid = row
        opening_net_cost = gross_cost - discount
    else:
        opening_net_cost, opening_paid = 0, 0

    total_cost = period_ticket_cost + opening_net_cost
    total_paid = paid + opening_paid

    return {
        "airline_name": airline_name,
        "ticket_count": ticket_count,
        "period_ticket_cost": period_ticket_cost,
        "opening_net_cost": opening_net_cost,
        "total_cost": total_cost,
        "paid": paid,
        "opening_paid": opening_paid,
        "total_paid": total_paid,
        "balance": total_cost - total_paid,
    }



def get_net_profit(cur, date_from="2020-01-01", date_to="2099-12-31"):
    """صافى الربح = إجمالى المبيعات - إجمالى التكلفة (من شيت المبيعات) - المصروفات
    العمومية (من الخزنة) - لا علاقة له بالتحصيل الفعلى؛ الربح يُحتسب وقت البيع نفسه
    (Accrual)، مش وقت تحصيل الفلوس فعليًا من العميل"""
    cur.execute("""
        SELECT COALESCE(SUM(total_sales), 0), COALESCE(SUM(total_cost), 0) FROM sales
        WHERE submission_date BETWEEN %s AND %s
    """, (date_from, date_to))
    total_sales, total_cost = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'مصروفات عمومية' AND transaction_date BETWEEN %s AND %s
    """, (date_from, date_to))
    general_expenses = cur.fetchone()[0]

    return total_sales - total_cost - general_expenses


def get_profit_and_loss(cur, date_from="2020-01-01", date_to="2099-12-31"):
    """ملخص الأرباح والخسائر الكامل - يشمل حركة الفترة (من شيت المبيعات، مفلترة حسب
    تاريخ التقديم) بالإضافة للأرصدة الافتتاحية (كل الأقسام الأربعة) والمصروفات
    العمومية، بنفس منطق شيت Revenue_Expense_Summary فى الإكسيل"""
    cur.execute("""
        SELECT COALESCE(SUM(total_sales), 0), COALESCE(SUM(total_cost), 0) FROM sales
        WHERE submission_date BETWEEN %s AND %s
    """, (date_from, date_to))
    period_revenue, period_cost = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'مصروفات عمومية' AND transaction_date BETWEEN %s AND %s
    """, (date_from, date_to))
    general_expenses = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(gross_sales - discount), 0) FROM opening_balances_agents")
    opening_agents_revenue = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(gross_revenue), 0) FROM opening_balances_airlines")
    opening_airlines_revenue = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(gross_purchases - discount), 0) FROM opening_balances_visa")
    opening_visa_cost = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(gross_purchases - discount), 0) FROM opening_balances_investment")
    opening_investment_cost = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(gross_cost - discount), 0) FROM opening_balances_airlines")
    opening_airlines_cost = cur.fetchone()[0]

    opening_revenue = opening_agents_revenue + opening_airlines_revenue
    opening_cost = opening_visa_cost + opening_investment_cost + opening_airlines_cost

    total_revenue = period_revenue + opening_revenue
    total_cost = period_cost + opening_cost
    net_profit = total_revenue - total_cost - general_expenses

    return {
        "period_revenue": period_revenue,
        "opening_revenue": opening_revenue,
        "total_revenue": total_revenue,
        "period_cost": period_cost,
        "opening_cost": opening_cost,
        "total_cost": total_cost,
        "general_expenses": general_expenses,
        "net_profit": net_profit,
    }


def get_partner_account(cur, partner_name, date_from="2020-01-01", date_to="2099-12-31"):
    """نصيب الشريك (entitled) = نسبته % × صافى الربح - ثابت، لا يتأثر بأى تحصيل.
    الموزَّع له فعليًا (distributed) = مجموع:
        1) قيود "توزيع أرباح على شريك" الصريحة باسمه
        2) أى تحصيل من عميل حُدِّد وقت تسجيله أنه مخصَّص لهذا الشريك تحديدًا
           (عمود related_partner) - دون أن يغيّر هذا نصيبه (entitled) على الإطلاق"""
    cur.execute("SELECT share_percentage FROM partners WHERE name = %s", (partner_name,))
    row = cur.fetchone()
    share = row[0] if row else 0

    net_profit = get_net_profit(cur, date_from, date_to)
    entitled = share * net_profit

    cur.execute("""
        SELECT COALESCE(SUM(outgoing), 0) FROM treasury
        WHERE movement_type = 'توزيع أرباح على شريك' AND party_name = %s
              AND transaction_date BETWEEN %s AND %s
    """, (partner_name, date_from, date_to))
    explicit_distributions = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(incoming), 0) FROM treasury
        WHERE movement_type = 'تحصيل من عميل' AND related_partner = %s
              AND transaction_date BETWEEN %s AND %s
    """, (partner_name, date_from, date_to))
    designated_collections = cur.fetchone()[0]

    distributed = explicit_distributions + designated_collections

    return {
        "partner_name": partner_name,
        "share_percentage": share,
        "net_profit": net_profit,
        "entitled": entitled,
        "explicit_distributions": explicit_distributions,
        "designated_collections": designated_collections,
        "distributed": distributed,
        "remaining": entitled - distributed,
    }


def get_all_partner_accounts(date_from="2020-01-01", date_to="2099-12-31"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM partners ORDER BY name")
    names = [r[0] for r in cur.fetchall()]
    results = [get_partner_account(cur, n, date_from, date_to) for n in names]
    conn.close()
    return results


def get_daily_package_breakdown(cur, date_from="2020-01-01", date_to="2099-12-31"):
    """عدد التقديمات وإجمالى السعر والتكلفة لكل نوع باكدج، فى كل يوم على حدة (بغض
    النظر عن خط السير)، مفلتر حسب تاريخ التقديم"""
    cur.execute("""
        SELECT submission_date, package_code, COUNT(*), COALESCE(SUM(total_sales),0),
               COALESCE(SUM(total_cost),0)
        FROM sales
        WHERE submission_date BETWEEN %s AND %s
        GROUP BY submission_date, package_code
        ORDER BY submission_date, package_code
    """, (date_from, date_to))
    rows = cur.fetchall()
    return [
        {"date": r[0], "package_code": r[1], "count": r[2], "total_sales": r[3], "total_cost": r[4]}
        for r in rows
    ]



def get_agent_package_summary(cur, date_from="2020-01-01", date_to="2099-12-31"):
    """عدد كل نوع باكدج حجزه كل وكيل (عملاء المبيعات) خلال الفترة - مفلتر حسب
    تاريخ التقديم"""
    cur.execute("SELECT name FROM agents ORDER BY name")
    agents = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT package_code FROM package_definitions ORDER BY id")
    packages = [r[0] for r in cur.fetchall()]

    results = []
    for agent in agents:
        row = {"agent_name": agent}
        total = 0
        for pkg in packages:
            cur.execute("""
                SELECT COUNT(*) FROM sales
                WHERE agent = %s AND package_code = %s AND submission_date BETWEEN %s AND %s
            """, (agent, pkg, date_from, date_to))
            count = cur.fetchone()[0]
            row[pkg] = count
            total += count
        row["total"] = total
        results.append(row)
    return results, packages


def get_treasury_movements(cur, date_from="2020-01-01", date_to="2099-12-31"):
    """كل حركات الخزنة خلال فترة معيّنة، بترتيب التاريخ، مع رصيد جاري تراكمي.
    ملحوظة مهمة: "السداد المباشر بين العميل والمورد" بيتسجّل هنا للتوثيق والمتابعة
    (وبيدخل فى حساب الوكيل/المورد بشكل صحيح فى تقارير تانية)، لكن الكاش فعليًا
    ما دخلش ولا خرج من خزنتك - فمينفعش يأثر على الرصيد الفعلى للخزنة"""
    cur.execute("""
        SELECT transaction_date, description, movement_type, party_name,
               payment_method, related_agent, related_partner, incoming, outgoing
        FROM treasury WHERE transaction_date BETWEEN %s AND %s
        ORDER BY transaction_date, id
    """, (date_from, date_to))
    rows = cur.fetchall()
    results = []
    running_balance = 0
    for row in rows:
        (tdate, desc, mtype, party, method, agent, partner, incoming, outgoing) = row
        is_direct = (method == "مباشر (بين العميل والمورد)")
        if not is_direct:
            running_balance += incoming - outgoing
        results.append({
            "date": tdate, "description": desc, "movement_type": mtype, "party_name": party,
            "payment_method": method, "related_agent": agent, "related_partner": partner,
            "incoming": incoming, "outgoing": outgoing,
            "running_balance": running_balance, "affects_treasury_cash": not is_direct,
        })
    return results


def get_sales_by_period(cur, date_from, date_to):
    """كل عمليات البيع (تفاصيل + إجمالى) خلال فترة تاريخ تقديم مختارة بحرية"""
    cur.execute("""
        SELECT submission_date, name, national_id, agent, package_code, total_sales, total_cost, net_profit
        FROM sales WHERE submission_date BETWEEN %s AND %s
        ORDER BY submission_date
    """, (date_from, date_to))
    rows = cur.fetchall()
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(total_sales),0), COALESCE(SUM(total_cost),0), COALESCE(SUM(net_profit),0)
        FROM sales WHERE submission_date BETWEEN %s AND %s
    """, (date_from, date_to))
    count, total_sales, total_cost, total_profit = cur.fetchone()
    return {
        "rows": rows,
        "count": count,
        "total_sales": total_sales,
        "total_cost": total_cost,
        "total_profit": total_profit,
    }


def get_all_agent_accounts(date_from="2020-01-01", date_to="2099-12-31"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM agents ORDER BY name")
    agents = [r[0] for r in cur.fetchall()]
    results = [get_agent_account(cur, a, date_from, date_to) for a in agents]
    conn.close()
    return results


if __name__ == "__main__":
    for r in get_all_agent_accounts():
        if r["total_sales"] or r["total_collected"]:
            print(r)
