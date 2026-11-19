"""
app.py — Flask API สำหรับระบบจัดตารางงาน
รัน: python app.py   (เปิดเฉพาะเครื่องนี้ที่ http://127.0.0.1:5000)
"""
from flask import Flask, request, jsonify, send_from_directory, abort
import os
import sqlite3
import uuid
from datetime import date as date_cls, datetime

from database import db, init_db, rows_to_list

# เสิร์ฟเฉพาะไฟล์ frontend จากโฟลเดอร์แม่
# (ห้ามใช้ static_folder=ROOT เพราะจะเปิดให้โหลดทุกไฟล์ รวมถึง data.db และ .git/)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PUBLIC_FILES = {'index.html', 'app.js', 'style.css'}

app = Flask(__name__, static_folder=None)


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def valid_date(s):
    """ตรวจรูปแบบ YYYY-MM-DD และต้องเป็นวันที่มีอยู่จริง"""
    try:
        return date_cls.fromisoformat(s).isoformat() == s
    except (TypeError, ValueError):
        return False


def pick(d, *keys, default=None):
    """คืนค่าจาก key แรกที่มีใน dict (รองรับทั้ง camelCase และ snake_case)"""
    for k in keys:
        if k in d:
            return d[k]
    return default


def shift_row(r):
    """แปลงแถวผลัดจาก DB เป็น dict สำหรับ REST API (snake_case)"""
    d = dict(r)
    d['overnight'] = bool(d['overnight'])
    d['is_off'] = bool(d['is_off'])
    d['active'] = bool(d['active'])
    return d


@app.errorhandler(sqlite3.IntegrityError)
def integrity_error(e):
    return jsonify({'error': 'ข้อมูลซ้ำ หรืออ้างอิงพนักงาน/ผลัดที่ไม่มีอยู่'}), 409


# ============================================================
# Static frontend
# ============================================================
@app.get('/', defaults={'name': 'index.html'})
@app.get('/<name>')
def static_files(name):
    if name not in PUBLIC_FILES:
        abort(404)
    return send_from_directory(ROOT, name)


# ============================================================
# EMPLOYEES
# ============================================================
def employee_error(data):
    if not data.get('fullname') or not data.get('position') or not data.get('phone'):
        return jsonify({'error': 'ต้องกรอก ชื่อ, ตำแหน่ง, เบอร์โทร'}), 400
    return None


@app.get('/api/employees')
def list_employees():
    with db() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY fullname").fetchall()
    return jsonify(rows_to_list(rows))


@app.post('/api/employees')
def create_employee():
    data = request.get_json(silent=True) or {}
    err = employee_error(data)
    if err:
        return err

    emp_id = data.get('id') or uid('emp')
    with db() as conn:
        conn.execute("""
            INSERT INTO employees (id, code, fullname, position, phone)
            VALUES (?, ?, ?, ?, ?)
        """, (emp_id, data.get('code', ''), data['fullname'],
              data['position'], data['phone']))
    return jsonify({**data, 'id': emp_id}), 201


@app.put('/api/employees/<emp_id>')
def update_employee(emp_id):
    data = request.get_json(silent=True) or {}
    err = employee_error(data)
    if err:
        return err

    with db() as conn:
        cur = conn.execute("""
            UPDATE employees SET code=?, fullname=?, position=?, phone=?
            WHERE id=?
        """, (data.get('code', ''), data['fullname'],
              data['position'], data['phone'], emp_id))
        if cur.rowcount == 0:
            return jsonify({'error': 'ไม่พบพนักงาน'}), 404
    return jsonify({**data, 'id': emp_id})


@app.delete('/api/employees/<emp_id>')
def delete_employee(emp_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
        if cur.rowcount == 0:
            return jsonify({'error': 'ไม่พบพนักงาน'}), 404
    return jsonify({'ok': True})


# ============================================================
# SHIFTS
# ============================================================
@app.get('/api/shifts')
def list_shifts():
    """คืนผลัดทั้งหมด (รวมที่ปิดใช้งาน) — ?active=1 เพื่อเอาเฉพาะที่ใช้งานอยู่"""
    sql = "SELECT * FROM shifts"
    if request.args.get('active') == '1':
        sql += " WHERE active=1"
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY code").fetchall()
    return jsonify([shift_row(r) for r in rows])


@app.post('/api/shifts')
def create_shift():
    data = request.get_json(silent=True) or {}
    if not data.get('code'):
        return jsonify({'error': 'ต้องมีรหัสผลัด'}), 400

    sh_id = data.get('id') or uid('shift')
    active = 0 if data.get('active') is False else 1
    with db() as conn:
        conn.execute("""
            INSERT INTO shifts (id, code, name, start_time, end_time,
                                color, overnight, ot_until, is_off, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sh_id, data['code'], data.get('name', ''),
              data.get('start_time', ''), data.get('end_time', ''),
              data.get('color', '#3498db'),
              1 if data.get('overnight') else 0,
              data.get('ot_until'),
              1 if data.get('is_off') else 0,
              active))
    return jsonify({**data, 'id': sh_id, 'active': bool(active)}), 201


@app.put('/api/shifts/<sh_id>')
def update_shift(sh_id):
    """แก้ไขผลัด — ส่ง active: true เพื่อเปิดใช้ผลัดที่ปิดไว้อีกครั้ง (ไม่ส่ง = คงค่าเดิม)"""
    data = request.get_json(silent=True) or {}
    if not data.get('code'):
        return jsonify({'error': 'ต้องมีรหัสผลัด'}), 400

    active = None if 'active' not in data else (1 if data['active'] else 0)
    with db() as conn:
        cur = conn.execute("""
            UPDATE shifts SET code=?, name=?, start_time=?, end_time=?,
                              color=?, overnight=?, ot_until=?, is_off=?,
                              active=COALESCE(?, active)
            WHERE id=?
        """, (data['code'], data.get('name', ''),
              data.get('start_time', ''), data.get('end_time', ''),
              data.get('color', '#3498db'),
              1 if data.get('overnight') else 0,
              data.get('ot_until'),
              1 if data.get('is_off') else 0,
              active,
              sh_id))
        if cur.rowcount == 0:
            return jsonify({'error': 'ไม่พบผลัด'}), 404
        row = conn.execute("SELECT * FROM shifts WHERE id=?", (sh_id,)).fetchone()
    return jsonify(shift_row(row))


@app.delete('/api/shifts/<sh_id>')
def delete_shift(sh_id):
    """
    ผลัดที่ยังไม่เคยถูกใช้ → ลบจริง
    ผลัดที่มีในตารางงานแล้ว → ปิดใช้งาน (active=0) เพื่อเก็บประวัติไว้
    """
    with db() as conn:
        if conn.execute("SELECT 1 FROM shifts WHERE id=?", (sh_id,)).fetchone() is None:
            return jsonify({'error': 'ไม่พบผลัด'}), 404

        used = conn.execute(
            "SELECT COUNT(*) AS c FROM schedule WHERE shift_id=?", (sh_id,)
        ).fetchone()['c']
        if used:
            conn.execute("UPDATE shifts SET active=0 WHERE id=?", (sh_id,))
        else:
            conn.execute("DELETE FROM shifts WHERE id=?", (sh_id,))
    return jsonify({'ok': True, 'deactivated': bool(used), 'usedIn': used})


# ============================================================
# SCHEDULE
# ============================================================
@app.get('/api/schedule')
def list_schedule():
    """คืน schedule ทั้งหมด (หรือกรองด้วย ?date=YYYY-MM-DD)"""
    date = request.args.get('date')
    if date is not None and not valid_date(date):
        return jsonify({'error': 'วันที่ต้องเป็นรูปแบบ YYYY-MM-DD'}), 400

    with db() as conn:
        if date:
            rows = conn.execute(
                "SELECT * FROM schedule WHERE date=?", (date,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM schedule").fetchall()

    # แปลงเป็น { date: { empId: {shiftId, ot} } }
    out = {}
    for r in rows:
        d = dict(r)
        out.setdefault(d['date'], {})[d['emp_id']] = {
            'shiftId': d['shift_id'],
            'ot': bool(d['ot'])
        }
    return jsonify(out)


@app.put('/api/schedule/<date>/<emp_id>')
def set_schedule(date, emp_id):
    """กำหนดผลัดให้พนักงานในวันนั้น — body: { shiftId, ot }"""
    if not valid_date(date):
        return jsonify({'error': 'วันที่ต้องเป็นรูปแบบ YYYY-MM-DD'}), 400

    data = request.get_json(silent=True) or {}
    shift_id = data.get('shiftId')
    ot = 1 if data.get('ot') else 0

    with db() as conn:
        if not shift_id:
            # ลบรายการ
            conn.execute(
                "DELETE FROM schedule WHERE date=? AND emp_id=?",
                (date, emp_id)
            )
        else:
            shift = conn.execute(
                "SELECT active FROM shifts WHERE id=?", (shift_id,)
            ).fetchone()
            if shift is None:
                return jsonify({'error': 'ไม่พบผลัด'}), 404
            if not shift['active']:
                # ผลัดที่ปิดใช้งานแล้ว: แก้รายการเดิมได้ (เช่นติ๊ก OT) แต่กำหนดใหม่ไม่ได้
                current = conn.execute(
                    "SELECT shift_id FROM schedule WHERE date=? AND emp_id=?",
                    (date, emp_id)
                ).fetchone()
                if current is None or current['shift_id'] != shift_id:
                    return jsonify({'error': 'ผลัดนี้ถูกปิดใช้งานแล้ว'}), 409

            conn.execute("""
                INSERT INTO schedule (date, emp_id, shift_id, ot)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date, emp_id) DO UPDATE SET
                    shift_id=excluded.shift_id,
                    ot=excluded.ot
            """, (date, emp_id, shift_id, ot))
    return jsonify({'date': date, 'emp_id': emp_id, 'shiftId': shift_id, 'ot': bool(ot)})


@app.delete('/api/schedule/<date>/<emp_id>')
def delete_schedule(date, emp_id):
    if not valid_date(date):
        return jsonify({'error': 'วันที่ต้องเป็นรูปแบบ YYYY-MM-DD'}), 400
    with db() as conn:
        conn.execute("DELETE FROM schedule WHERE date=? AND emp_id=?", (date, emp_id))
    return jsonify({'ok': True})


# ============================================================
# BACKUP / RESTORE
# ใช้รูปแบบเดียวกับไฟล์ JSON ที่ส่งออกจากหน้าเว็บ (camelCase)
# เพื่อให้ไฟล์ backup ใช้สลับกันได้ระหว่างเว็บกับ backend
# ============================================================
@app.get('/api/backup')
def backup():
    """คืน JSON ทั้งหมด"""
    with db() as conn:
        employees = rows_to_list(conn.execute("SELECT * FROM employees").fetchall())
        shift_rows = conn.execute("SELECT * FROM shifts").fetchall()
        sched = rows_to_list(conn.execute("SELECT * FROM schedule").fetchall())

    shifts = [{
        'id': r['id'],
        'code': r['code'],
        'name': r['name'],
        'startTime': r['start_time'],
        'endTime': r['end_time'],
        'color': r['color'],
        'overnight': bool(r['overnight']),
        'otUntil': r['ot_until'],
        'isOff': bool(r['is_off']),
        'active': bool(r['active']),
    } for r in shift_rows]

    schedule = {}
    for r in sched:
        schedule.setdefault(r['date'], {})[r['emp_id']] = {
            'shiftId': r['shift_id'],
            'ot': bool(r['ot'])
        }

    return jsonify({
        'employees': employees,
        'shifts': shifts,
        'schedule': schedule,
        'exportedAt': datetime.now().isoformat(),
        'version': 2
    })


@app.post('/api/restore')
def restore():
    """กู้คืนจาก JSON — ลบของเดิมทั้งหมด (รับได้ทั้งไฟล์จากเว็บและไฟล์ backup รุ่นเก่า)"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not isinstance(data.get('employees'), list) \
            or not isinstance(data.get('shifts'), list):
        return jsonify({'error': 'รูปแบบไม่ถูกต้อง'}), 400

    schedule = data.get('schedule')
    if not isinstance(schedule, dict):
        schedule = {}

    with db() as conn:
        # ล้างของเดิมทั้งหมด (schedule ลบก่อนเพราะมี FK อ้างถึง)
        conn.execute("DELETE FROM schedule")
        conn.execute("DELETE FROM employees")
        conn.execute("DELETE FROM shifts")

        for e in data['employees']:
            if not isinstance(e, dict):
                continue
            conn.execute("""
                INSERT INTO employees (id, code, fullname, position, phone)
                VALUES (?, ?, ?, ?, ?)
            """, (e.get('id') or uid('emp'), e.get('code', ''),
                  e.get('fullname', ''), e.get('position', ''), e.get('phone', '')))

        for s in data['shifts']:
            if not isinstance(s, dict):
                continue
            conn.execute("""
                INSERT INTO shifts (id, code, name, start_time, end_time,
                                    color, overnight, ot_until, is_off, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s.get('id') or uid('shift'), s.get('code', ''), s.get('name', ''),
                  pick(s, 'startTime', 'start_time', default='') or '',
                  pick(s, 'endTime', 'end_time', default='') or '',
                  s.get('color', '#3498db'),
                  1 if s.get('overnight') else 0,
                  pick(s, 'otUntil', 'ot_until') or None,
                  1 if pick(s, 'isOff', 'is_off') else 0,
                  0 if s.get('active') is False else 1))

        # อ้างอิงที่ถูกต้องจริงหลัง insert (กัน FK error จากข้อมูลอ้างอิงที่ไม่มีอยู่)
        emp_ids = {r['id'] for r in conn.execute("SELECT id FROM employees")}
        shift_ids = {r['id'] for r in conn.execute("SELECT id FROM shifts")}

        for date, day in schedule.items():
            if not valid_date(date) or not isinstance(day, dict):
                continue
            for emp_id, entry in day.items():
                if not isinstance(entry, dict) or not entry.get('shiftId'):
                    continue
                if emp_id not in emp_ids or entry['shiftId'] not in shift_ids:
                    continue  # ข้ามรายการที่อ้างถึงพนักงาน/ผลัดที่ไม่มีอยู่
                conn.execute("""
                    INSERT INTO schedule (date, emp_id, shift_id, ot)
                    VALUES (?, ?, ?, ?)
                """, (date, emp_id, entry['shiftId'], 1 if entry.get('ot') else 0))

    return jsonify({'ok': True})


# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    init_db()
    print("=" * 55)
    print("🐍  Flask Backend — ระบบจัดตารางงาน")
    print("=" * 55)
    print("  🌐 http://127.0.0.1:5000  (เปิดได้เฉพาะเครื่องนี้)")
    print("  📡 API: /api/employees | /api/shifts | /api/schedule")
    print("=" * 55)
    # ห้ามเปิด debug บนเครื่องที่คนอื่นเข้าถึงได้: Werkzeug debugger สั่งรันโค้ดได้
    app.run(host='127.0.0.1', port=5000,
            debug=os.environ.get('FLASK_DEBUG') == '1')
