"""
database.py — จัดการ SQLite + Schema
"""
import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """สร้างตารางถ้ายังไม่มี + seed ผลัดเริ่มต้น"""
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                id       TEXT PRIMARY KEY,
                code     TEXT DEFAULT '',
                fullname TEXT NOT NULL,
                position TEXT NOT NULL,
                phone    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shifts (
                id         TEXT PRIMARY KEY,
                code       TEXT NOT NULL,
                name       TEXT DEFAULT '',
                start_time TEXT DEFAULT '',
                end_time   TEXT DEFAULT '',
                color      TEXT DEFAULT '#3498db',
                overnight  INTEGER DEFAULT 0,
                ot_until   TEXT,
                is_off     INTEGER DEFAULT 0,
                active     INTEGER NOT NULL DEFAULT 1   -- 0 = ปิดใช้งาน (soft delete)
            );

            -- ผลัดที่มีในตารางงานแล้วจะไม่ถูกลบจริง (ปิดใช้งานแทน)
            -- RESTRICT กันไม่ให้ประวัติหายถ้ามีโค้ดไหนเผลอลบผลัดตรง ๆ
            CREATE TABLE IF NOT EXISTS schedule (
                date     TEXT NOT NULL,
                emp_id   TEXT NOT NULL,
                shift_id TEXT NOT NULL,
                ot       INTEGER DEFAULT 0,
                PRIMARY KEY (date, emp_id),
                FOREIGN KEY (emp_id)   REFERENCES employees(id) ON DELETE CASCADE,
                FOREIGN KEY (shift_id) REFERENCES shifts(id)    ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_schedule_date ON schedule(date);
        """)

        # ฐานข้อมูลเก่าที่สร้างก่อนมีคอลัมน์ active → เพิ่มคอลัมน์ให้
        cols = {r['name'] for r in conn.execute("PRAGMA table_info(shifts)")}
        if 'active' not in cols:
            conn.execute("ALTER TABLE shifts ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

        # Seed ผลัดถ้าตารางว่าง
        cur = conn.execute("SELECT COUNT(*) AS c FROM shifts")
        if cur.fetchone()['c'] == 0:
            default_shifts = [
                ('S1', 'M',   'เช้า',    '07:00', '16:00', '#f39c12', 0, None,    0),
                ('S2', 'A',   'บ่าย',    '13:30', '22:30', '#3498db', 0, None,    0),
                ('S3', 'N',   'ดึก',     '22:00', '07:00', '#8e44ad', 1, '10:00', 0),
                ('S4', 'T08', '',        '08:00', '17:00', '#16a085', 0, None,    0),
                ('S5', 'T10', '',        '10:00', '19:00', '#27ae60', 0, '22:30', 0),
                ('S6', 'T13', '',        '13:00', '22:00', '#2ecc71', 0, None,    0),
                ('S7', 'MGR', 'ผู้จัดการ', '08:30', '17:30', '#c0392b', 0, None,    0),
                ('S8', 'OFF', 'หยุด',    '',      '',      '#95a5a6', 0, None,    1),
            ]
            conn.executemany("""
                INSERT INTO shifts (id, code, name, start_time, end_time,
                                    color, overnight, ot_until, is_off)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, default_shifts)
            print("✅ Seed ผลัดเริ่มต้น 8 รายการ")


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]