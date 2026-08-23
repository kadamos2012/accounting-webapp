"""
db.py - PostgreSQL connection helper. Reads the connection string from the
DATABASE_URL environment variable (set this in Render's dashboard, or in a
local .env file for testing).
"""
import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_connection(dict_cursor=False):
    """يرجّع اتصال جديد بقاعدة البيانات - يُستخدم مرة واحدة لكل طلب (request)
    ويتقفل بعدها، مناسب لتطبيق ويب بيستقبل طلبات من أكتر من مستخدم فى نفس الوقت.
    dict_cursor=True بيرجّع صفوف كـ dict (مفيد فى الـ Flask templates)، بينما
    الافتراضي (False) بيرجّع صفوف كـ tuple عادية (زي sqlite3 - مطلوب عشان
    reports.py يشتغل من غير أي تعديل فى منطق الوصول للأعمدة)"""
    if dict_cursor:
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return psycopg2.connect(DATABASE_URL)
