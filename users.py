"""
users.py - User authentication (per-person accounts instead of one shared
password) and activity logging, so every important action is tracked with
who did it and when.
"""
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_connection


def create_user(username, password, display_name="", is_admin=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users(username, password_hash, display_name, is_admin)
        VALUES (%s, %s, %s, %s)
    """, (username, generate_password_hash(password), display_name or username, int(is_admin)))
    conn.commit()
    conn.close()


def verify_login(username, password):
    """يرجّع بيانات المستخدم لو الباسورد صح، وإلا None"""
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    conn.close()
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def change_password(username, new_password):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash = %s WHERE username = %s",
                (generate_password_hash(new_password), username))
    conn.commit()
    conn.close()


def list_users():
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, is_admin, created_at FROM users ORDER BY id")
    users = cur.fetchall()
    conn.close()
    return users


def log_activity(username, action, details=""):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO activity_log(username, action, details) VALUES (%s, %s, %s)",
                (username, action, details))
    conn.commit()
    conn.close()


def get_activity_log(limit=200, username_filter=None):
    conn = get_connection(dict_cursor=True)
    cur = conn.cursor()
    if username_filter:
        cur.execute("""
            SELECT * FROM activity_log WHERE username = %s
            ORDER BY id DESC LIMIT %s
        """, (username_filter, limit))
    else:
        cur.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows
