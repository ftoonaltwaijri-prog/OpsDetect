"""OpsDetect local portfolio application. Run: python app.py"""
import csv
import io
import os
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024
app.config['DATABASE'] = str(ROOT / 'opsdetect.sqlite3')
FIELDS = ('id', 'type', 'vendor', 'amount', 'date', 'reference', 'status')
OPTIONAL_FIELDS = ('due_date',)
STATES = ('Open', 'Investigating', 'Resolved')

def db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def initialize():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, vendor TEXT, amount REAL, event_date TEXT, reference TEXT, status TEXT, due_date TEXT);
        CREATE TABLE IF NOT EXISTS findings (id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT NOT NULL, reference TEXT, detail TEXT NOT NULL, severity TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'Open', created_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, finding_id INTEGER, old_status TEXT, new_status TEXT, changed_at TEXT);
        """)

def parse_csv(data):
    try:
        text = data.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or any(f not in reader.fieldnames for f in FIELDS):
            raise ValueError('Required columns: ' + ', '.join(FIELDS))
        rows = []
        for i, raw in enumerate(reader, 2):
            if i > 5001: raise ValueError('Maximum 5000 rows')
            row = {k: (raw.get(k) or '').strip() for k in FIELDS + OPTIONAL_FIELDS}
            if not row['id']: raise ValueError(f'Row {i}: missing id')
            try: row['amount'] = float(row['amount']) if row['amount'] else None
            except ValueError: raise ValueError(f'Row {i}: invalid amount')
            for col in ('date', 'due_date'):
                if row[col]:
                    try: date.fromisoformat(row[col])
                    except ValueError: raise ValueError(f'Row {i}: {col} must be YYYY-MM-DD')
            rows.append(row)
        return rows
    except UnicodeDecodeError: raise ValueError('CSV must be UTF-8')

def analyze(rows):
    issues = []
    def add(rule, ref, detail, severity): issues.append((rule, ref, detail, severity))
    seen = set()
    amounts = [abs(r['amount']) for r in rows if r['amount'] is not None]
    amounts.sort()
    median = amounts[len(amounts)//2] if amounts else 0
    for r in rows:
        ref = r['reference']
        if ref and ref.casefold() in seen: add('Duplicate reference', ref, 'Reference appears in multiple records; verify before action.', 'High')
        if ref: seen.add(ref.casefold())
        if not r['vendor'] or not ref or r['amount'] is None: add('Missing field', ref or r['id'], 'Vendor, reference or amount is missing.', 'Medium')
        if r['amount'] is not None and median > 0 and abs(r['amount']) > median * 3: add('Amount outlier', ref or r['id'], 'Amount exceeds 3× dataset median; investigate, not proof of loss.', 'Medium')
        if r['type'].lower() in ('purchase order','po') and r['status'].lower() not in ('delivered','closed','complete') and r.get('due_date') and date.fromisoformat(r['due_date']) < date.today():
            add('Overdue purchase order', ref or r['id'], 'Due date has passed and order is not marked complete.', 'Medium')
    return issues

@app.get('/')
def home(): return send_from_directory(ROOT, 'dashboard.html')

@app.get('/api/summary')
def summary():
    with db() as c:
        records = c.execute('SELECT COUNT(*) n FROM records').fetchone()['n']
        findings = [dict(x) for x in c.execute('SELECT * FROM findings ORDER BY id DESC')]
        audit = [dict(x) for x in c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 100')]
    return jsonify(records=records, findings=findings, audit=audit)

@app.post('/api/import')
def import_records():
    file = request.files.get('file')
    if not file: return jsonify(error='Choose a CSV file'), 400
    if not file.filename.lower().endswith('.csv'): return jsonify(error='Only .csv files are accepted'), 400
    try: rows = parse_csv(file.read())
    except ValueError as e: return jsonify(error=str(e)), 400
    if len({r['id'] for r in rows}) != len(rows): return jsonify(error='Duplicate row IDs in CSV'), 400
    start = time.perf_counter()
    issues = analyze(rows)
    with db() as c:
        c.execute('DELETE FROM audit_log')
        c.execute('DELETE FROM findings')
        c.execute('DELETE FROM records')
        c.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?)', [(r['id'],r['type'],r['vendor'],r['amount'],r['date'],r['reference'],r['status'],r['due_date']) for r in rows])
        c.executemany('INSERT INTO findings(rule,reference,detail,severity,created_at) VALUES(?,?,?,?,?)', [(*issue,datetime.now().isoformat(timespec='seconds')) for issue in issues])
    return jsonify(imported=len(rows), findings=len(issues), processing_ms=round((time.perf_counter()-start)*1000,2))

@app.patch('/api/findings/<int:fid>')
def update_finding(fid):
    payload = request.get_json(silent=True) or {}
    status = payload.get('status')
    note = payload.get('note', '')
    if not isinstance(note, str) or len(note) > 500: return jsonify(error='Note must be at most 500 characters'), 400
    if status not in STATES: return jsonify(error='Invalid status'), 400
    with db() as c:
        old = c.execute('SELECT review_status FROM findings WHERE id=?',(fid,)).fetchone()
        if not old: return jsonify(error='Finding not found'), 404
        if old['review_status'] != status:
            c.execute('UPDATE findings SET review_status=?, note=? WHERE id=?',(status,note,fid))
            c.execute('INSERT INTO audit_log(finding_id,old_status,new_status,changed_at) VALUES(?,?,?,?)',(fid,old['review_status'],status,datetime.now().isoformat(timespec='seconds')))
    return jsonify(ok=True)

@app.get('/api/health')
def health():
    with db() as c: c.execute('SELECT 1').fetchone()
    return jsonify(status='ok', database='sqlite')

@app.get('/api/records')
def records():
    with db() as c: rows = [dict(r) for r in c.execute('SELECT * FROM records ORDER BY id LIMIT 5000')]
    return jsonify(records=rows)

@app.get('/api/export')
def export():
    with db() as c: rows = [dict(r) for r in c.execute('SELECT id,rule,reference,detail,severity,review_status,note,created_at FROM findings ORDER BY id')]
    for row in rows:
        for key, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                row[key] = "'" + value
    out = io.StringIO(); writer=csv.DictWriter(out,fieldnames=['id','rule','reference','detail','severity','review_status','note','created_at']); writer.writeheader(); writer.writerows(rows)
    from flask import Response
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=opsdetect_findings.csv'})

if __name__ == '__main__':
    initialize()
    print('Open http://127.0.0.1:5000')
    app.run(host='127.0.0.1',port=5000,debug=False)
