"""
undo_last_import.py - Deletes all client rows added by the most recent
daily import batch, using the ID range recorded at import time (PostgreSQL
/ Supabase version).
"""
from db import get_connection


def get_last_import():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, import_date, source_file, rows_added, min_id, max_id
        FROM import_log ORDER BY id DESC LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row


def undo_last_import():
    row = get_last_import()
    if not row:
        return {"success": False, "error": "لا يوجد سجل استيراد سابق."}

    log_id, import_date, source_file, rows_added, min_id, max_id = row
    if min_id is None or max_id is None:
        return {"success": False, "error": "هذا الاستيراد أقدم من ميزة التراجع، لا يمكن التراجع عنه تلقائيًا."}

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sales WHERE id BETWEEN %s AND %s", (min_id, max_id))
    actual_count = cur.fetchone()[0]

    cur.execute("DELETE FROM sales WHERE id BETWEEN %s AND %s", (min_id, max_id))
    cur.execute("DELETE FROM import_log WHERE id = %s", (log_id,))
    conn.commit()
    conn.close()

    return {"success": True, "removed": actual_count, "source_file": source_file,
            "import_date": str(import_date)}
