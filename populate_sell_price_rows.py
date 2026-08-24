"""
populate_sell_price_rows.py - Scans EXISTING sales rows and makes sure every
(package_code, port, destination, category) combination that shows up has a
row in total_sell_prices - with price = 0, ready for manual entry. No price
guessing/inference - just fills in the missing "shell" rows so nothing is
missing from the "Edit Selling Prices" screen.
"""
from db import get_connection


def preview_missing_combos():
    """يرجّع كل التركيبات (باكدج+خط سير+فئة) الموجودة فعليًا فى المبيعات
    بس *لسه مالهاش صف* فى جدول أسعار البيع خالص"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT package_code, port, destination, category FROM total_sell_prices")
    already_exists = set(cur.fetchall())

    cur.execute("""
        SELECT DISTINCT package_code, port, destination, category, COUNT(*) OVER (
            PARTITION BY package_code, port, destination, category
        ) as usage_count
        FROM sales
        WHERE package_code IS NOT NULL AND port IS NOT NULL
              AND destination IS NOT NULL AND category IS NOT NULL
    """)
    seen = {}
    for pkg, port, dest, cat, count in cur.fetchall():
        key = (pkg, port, dest, cat)
        if key not in already_exists:
            seen[key] = count
    conn.close()

    combos = [{"package_code": k[0], "port": k[1], "destination": k[2], "category": k[3],
               "usage_count": v} for k, v in seen.items()]
    combos.sort(key=lambda c: -c["usage_count"])
    return combos


def apply_missing_combos(selected_keys):
    """يضيف صف بسعر صفر لكل تركيبة من المختارة - جاهزة تُملأ يدويًا من شاشة
    'تعديل أسعار البيع'"""
    conn = get_connection()
    cur = conn.cursor()
    added = 0
    for key in selected_keys:
        pkg, port, dest, cat = key
        cur.execute("""
            INSERT INTO total_sell_prices(date_from, date_to, package_code, port, destination, category, total_price)
            VALUES ('2020-01-01', '2099-12-31', %s, %s, %s, %s, 0)
        """, (pkg, port, dest, cat))
        added += 1
    conn.commit()
    conn.close()
    return {"added": added}

