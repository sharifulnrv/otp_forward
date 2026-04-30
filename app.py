from flask import Flask, request, jsonify
import re
import threading
import time

app = Flask(__name__)

# ── CORS ─────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept, ngrok-skip-browser-warning'
    return response

import sqlite3
import os

# Database Path (Ensure write permissions on PythonAnywhere)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "otps.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS otps (
                phone_number TEXT PRIMARY KEY,
                otp TEXT,
                timestamp REAL,
                last_seen REAL
            )
        """)
init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

WORD_TO_DIGIT = {
    'Zero': '0', 'One': '1', 'Two': '2', 'Three': '3', 'Four': '4',
    'Five': '5', 'Six': '6', 'Seven': '7', 'Eight': '8', 'Nine': '9'
}

# ── Universal OTP Receiver ───────────────────────────────────────────
@app.route('/receive_otp', methods=['POST', 'OPTIONS'])
def receive_otp():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    message = data.get('message', '')
    phone_number = data.get('phone_number', 'Unknown')
    direct_otp = data.get('otp') # Support direct OTP field if provided

    if phone_number == "Unknown" or not phone_number:
        return jsonify({'status': 'ignored', 'message': 'Unknown phone number.'}), 200

    otp_string = None
    
    # 1. Try direct OTP field
    if direct_otp and direct_otp.lower() != "none":
        otp_string = str(direct_otp)
    
    # 2. Try word-based OTP (IVAC format)
    if not otp_string:
        # Match words case-insensitively
        words = re.findall(r'\b(?:Zero|One|Two|Three|Four|Five|Six|Seven|Eight|Nine)\b', message, re.IGNORECASE)
        if len(words) >= 6:
            # Map words to digits regardless of case
            otp_string = "".join(WORD_TO_DIGIT[w.capitalize()] for w in words[-6:])
    
    # 3. Try numeric 6-digit OTP (Common bank format)
    if not otp_string:
        nums = re.findall(r'\d{6}', message)
        if nums:
            otp_string = nums[0]

    with sqlite3.connect(DB_PATH) as conn:
        # Check if exists
        curr = conn.execute("SELECT * FROM otps WHERE phone_number = ?", (phone_number,)).fetchone()
        now = time.time()
        
        if otp_string:
            if curr:
                conn.execute("UPDATE otps SET otp = ?, timestamp = ?, last_seen = ? WHERE phone_number = ?", 
                             (otp_string, now, now, phone_number))
            else:
                conn.execute("INSERT INTO otps (phone_number, otp, timestamp, last_seen) VALUES (?, ?, ?, ?)",
                             (phone_number, otp_string, now, now))
            print(f"[{phone_number}] OTP received: {otp_string}")
        else:
            if curr:
                conn.execute("UPDATE otps SET last_seen = ? WHERE phone_number = ?", (now, phone_number))
            else:
                conn.execute("INSERT INTO otps (phone_number, otp, timestamp, last_seen) VALUES (?, NULL, NULL, ?)",
                             (phone_number, now))
            print(f"[{phone_number}] Heartbeat")
        conn.commit()

    return jsonify({'status': 'success', 'otp': otp_string, 'phone': phone_number}), 200

# ── API: Get all OTPs ────────────────────────────────────────────────
@app.route('/api/otps', methods=['GET'])
def get_all_otps():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM otps ORDER BY last_seen DESC").fetchall()
        result = []
        now = time.time()
        for row in rows:
            otp = row['otp']
            time_left = 0
            # Expire OTP after 3 mins
            if otp and row['timestamp'] and (now - row['timestamp'] > 180):
                otp = None
            
            if otp:
                time_left = int(180 - (now - row['timestamp']))

            result.append({
                'phone_number': row['phone_number'],
                'otp': otp,
                'time_left': max(time_left, 0),
                'timestamp': row['timestamp'],
                'last_seen': row['last_seen'],
            })
        return jsonify(result)

# ── API: Get OTP by Phone ───────────────────────────────────────────
@app.route('/api/otp/<path:phone>', methods=['GET'])
def get_otp_by_phone(phone):
    now = time.time()
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM otps WHERE phone_number = ?", (phone,)).fetchone()
        if row:
            otp = row['otp']
            if not otp or (row['timestamp'] and (now - row['timestamp'] > 180)):
                return jsonify({'error': 'No active OTP for this phone'}), 404
            
            time_left = int(180 - (now - row['timestamp']))
            return jsonify({
                'phone': phone,
                'otp': otp,
                'time_left': max(time_left, 0)
            })
        return jsonify({'error': 'Phone not found'}), 404

# ── Clear single OTP ─────────────────────────────────────────────────
@app.route('/api/clear/<path:phone>', methods=['DELETE'])
def delete_otp(phone):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("DELETE FROM otps WHERE phone_number = ?", (phone,))
        if res.rowcount > 0:
            conn.commit()
            return jsonify({'status': 'deleted'}), 200
        return jsonify({'error': 'Not found'}), 404

# ── Dashboard ────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OTP Receiver</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Inter',sans-serif;background:#0b0f19;color:#e2e8f0;min-height:100vh;}

/* Header */
.header{background:linear-gradient(135deg,#1e1b4b 0%,#0f172a 50%,#0c1222 100%);padding:32px;border-bottom:1px solid rgba(99,102,241,.2);}
.header h1{font-size:28px;font-weight:700;background:linear-gradient(135deg,#818cf8,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;display:flex;align-items:center;gap:12px;}
.header h1 span{font-size:32px;-webkit-text-fill-color:initial;}
.header p{color:#94a3b8;font-size:14px;margin-top:8px;}

/* Endpoint Box */
.endpoint-box{background:rgba(30,41,59,.6);border:1px solid rgba(99,102,241,.3);border-radius:12px;padding:16px 20px;margin:24px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
.endpoint-url{font-family:monospace;background:rgba(15,23,42,.8);padding:10px 14px;border-radius:8px;flex:1;min-width:250px;color:#38bdf8;overflow-x:auto;white-space:nowrap;font-size:13px;}
.btn-copy-endpoint{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border:none;padding:10px 20px;border-radius:8px;font-weight:600;cursor:pointer;transition:.2s;white-space:nowrap;}
.btn-copy-endpoint:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(99,102,241,.3);}

/* Stats */
.stats{display:flex;gap:16px;padding:0 24px;margin-bottom:20px;flex-wrap:wrap;}
.stat{background:rgba(30,41,59,.7);border:1px solid rgba(148,163,184,.1);padding:12px 20px;border-radius:12px;text-align:center;}
.stat-val{font-size:24px;font-weight:700;color:#38bdf8;}
.stat-label{font-size:12px;color:#94a3b8;margin-top:4px;text-transform:uppercase;letter-spacing:1px;}

/* Table */
.table-wrap{padding:0 24px 32px;}
table{width:100%;border-collapse:separate;border-spacing:0;background:rgba(15,23,42,.7);border-radius:16px;overflow:hidden;border:1px solid rgba(148,163,184,.08);}
thead th{background:rgba(30,41,59,.9);color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;padding:14px 16px;text-align:left;font-weight:600;}
tbody tr{border-bottom:1px solid rgba(148,163,184,.06);transition:.15s;}
tbody tr:hover{background:rgba(99,102,241,.04);}
td{padding:16px;font-size:14px;vertical-align:middle;}

/* Phone column */
.phone-col{font-weight:600;color:#c7d2fe;font-size:15px;}

/* OTP cell */
.otp-val{font-family:monospace;font-size:24px;font-weight:700;letter-spacing:6px;color:#38bdf8;text-align:center;}
.otp-waiting{color:#475569;font-style:italic;font-size:12px;}

/* Timer */
.timer{font-size:13px;color:#f87171;font-weight:600;text-align:center;}

/* Actions */
.btn-copy{background:rgba(34,197,94,.1);color:#4ade80;border:none;padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer;transition:.15s;font-weight:500;}
.btn-copy:hover{background:rgba(34,197,94,.25);}
.btn-del{background:rgba(239,68,68,.1);color:#f87171;border:none;padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer;transition:.15s;font-weight:500;}
.btn-del:hover{background:rgba(239,68,68,.25);}

/* Empty */
.empty{text-align:center;padding:80px 20px;color:#475569;}
.empty .icon{font-size:56px;margin-bottom:16px;}
.empty p{font-size:15px;line-height:1.6;}

/* Toast */
.toast{position:fixed;bottom:28px;right:28px;background:#1e293b;color:#4ade80;padding:14px 24px;border-radius:12px;font-size:14px;font-weight:600;border:1px solid rgba(74,222,128,.2);opacity:0;transition:.3s;pointer-events:none;z-index:200;}
.toast.show{opacity:1;}

/* Pulse */
.pulse{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;}
.pulse.live{background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.5);animation:pulse-ring 1.5s infinite;}
.pulse.idle{background:#475569;}
@keyframes pulse-ring{0%{box-shadow:0 0 0 0 rgba(74,222,128,.45);}70%{box-shadow:0 0 0 10px rgba(74,222,128,0);}100%{box-shadow:0 0 0 0 rgba(74,222,128,0);}}

/* Responsive */
/* Responsive */
@media(max-width:768px){
  .header{padding:20px 16px;} 
  .header h1{font-size:22px;}
  .endpoint-box{padding:12px;margin:16px;flex-direction:column;align-items:stretch;}
  .endpoint-url{font-size:11px;min-width:auto;margin-bottom:8px;}
  .btn-copy-endpoint{width:100%;}
  
  .table-wrap{padding:0 12px 20px;}
  
  /* Convert table to cards */
  table, thead, tbody, th, td, tr { display: block; }
  thead tr { position: absolute; top: -9999px; left: -9999px; }
  tr { background: rgba(30,41,59,.4); margin-bottom: 16px; border-radius: 12px; border: 1px solid rgba(148,163,184,.1); padding: 8px; }
  td { border: none; position: relative; padding-left: 45% !important; text-align: left; min-height: 40px; display: flex; align-items: center; justify-content: flex-end; }
  td:before { content: attr(data-label); position: absolute; left: 16px; width: 40%; font-weight: 600; font-size: 11px; text-transform: uppercase; color: #94a3b8; text-align: left; }
  
  .otp-val{font-size:20px;letter-spacing:2px;}
  .btn-copy, .btn-del{padding:8px 14px; font-size:12px; flex:1; justify-content:center;}
  td[style*="display:flex"]{ padding-left: 16px !important; justify-content: center; gap: 10px; margin-top: 8px; border-top: 1px solid rgba(148,163,184,.05); padding-top: 12px !important; }
  td[style*="display:flex"]:before { display: none; }
}
</style>
</head>
<body>

<div class="header">
    <h1><span>📬</span> OTP Receiver</h1>
    <p>Universal OTP dashboard — receive from any sender</p>
</div>

<div class="endpoint-box">
    <div>
        <div style="font-size:12px;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">POST Endpoint</div>
        <div class="endpoint-url" id="endpoint-url"></div>
    </div>
    <button class="btn-copy-endpoint" onclick="copyEndpoint()">📋 Copy URL</button>
</div>

<div class="endpoint-box">
    <div>
        <div style="font-size:12px;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">JSON Data API (All Numbers & OTPs)</div>
        <div class="endpoint-url" id="json-url"></div>
    </div>
    <div style="display:flex;gap:8px;">
        <a id="json-link" href="#" target="_blank" style="text-decoration:none;background:rgba(56,189,248,.1);color:#38bdf8;padding:10px 16px;border-radius:8px;font-weight:600;font-size:13px;border:1px solid rgba(56,189,248,.3);">🌐 Open</a>
        <button class="btn-copy-endpoint" onclick="copyJsonUrl()">📋 Copy URL</button>
    </div>
</div>

<div class="stats">
    <div class="stat">
        <div class="stat-val" id="total-count">0</div>
        <div class="stat-label">Active Numbers</div>
    </div>
    <div class="stat">
        <div class="stat-val" id="active-otps">0</div>
        <div class="stat-label">OTPs Ready</div>
    </div>
</div>

<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Phone Number</th>
                <th>Status / Live OTP</th>
                <th>Last Seen</th>
                <th>Timer</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="otp-table">
            <tr><td colspan="5"><div class="empty"><div class="icon">📱</div><p>Waiting for OTPs…<br>Send SMS to the endpoint above.</p></div></td></tr>
        </tbody>
    </table>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = location.origin;
const ENDPOINT = BASE + '/receive_otp';
const JSON_URL = BASE + '/api/otps';

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}

function copyText(text) {
    navigator.clipboard.writeText(text).then(() => showToast('📋 Copied!'));
}

function copyEndpoint() {
    copyText(ENDPOINT);
}

function copyJsonUrl() {
    copyText(JSON_URL);
}

function fmtTimer(secs) {
    if (secs <= 0) return '—';
    const m = Math.floor(secs/60), s = secs%60;
    return String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}

async function deleteOtp(phone) {
    if (!confirm('Clear this OTP?')) return;
    await fetch('/api/clear/' + encodeURIComponent(phone), { method:'DELETE' });
    showToast('🗑️ Cleared');
    refreshOtps();
}

async function refreshOtps() {
    try {
        const res = await fetch('/api/otps');
        const data = await res.json();
        const tbody = document.getElementById('otp-table');
        
        document.getElementById('total-count').textContent = data.length;
        document.getElementById('active-otps').textContent = data.filter(d => d.otp).length;
        
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4"><div class="empty"><div class="icon">📱</div><p>Waiting for OTPs…<br>Send SMS to the endpoint above.</p></div></td></tr>';
            return;
        }
        
        tbody.innerHTML = data.map(d => {
            const otpHtml = d.otp
                ? `<div style="display:flex;align-items:center;gap:8px;"><span class="pulse live"></span><span class="otp-val">${d.otp}</span></div>`
                : `<div style="display:flex;align-items:center;gap:8px;"><span class="pulse idle" style="background:#38bdf8;"></span><span class="otp-waiting" style="color:#38bdf8;">Connected (Waiting...)</span></div>`;
            const timerHtml = d.otp ? `<div class="timer">${fmtTimer(d.time_left)}</div>` : '—';
            const copyBtn = d.otp ? `<button class="btn-copy" onclick="copyText('${d.otp}')">📋 Copy OTP</button>` : '';
            
            const lastSeenSecs = Math.floor(Date.now()/1000 - d.last_seen);
            const lastSeenText = lastSeenSecs < 5 ? 'Just now' : lastSeenSecs + 's ago';

            return `<tr>
                <td class="phone-col" data-label="Phone Number">${d.phone_number}</td>
                <td data-label="Status / OTP">${otpHtml}</td>
                <td style="color:#94a3b8;font-size:12px;" data-label="Last Seen">${lastSeenText}</td>
                <td data-label="Timer">${timerHtml}</td>
                <td style="display:flex;gap:6px;flex-wrap:wrap;">${copyBtn}<button class="btn-del" onclick="deleteOtp('${d.phone_number.replace(/'/g, "\\'")}')">🗑 Clear</button></td>
            </tr>`;
        }).join('');
        
    } catch(e) { console.error(e); }
}

// Set endpoint URLs
document.getElementById('endpoint-url').textContent = ENDPOINT;
document.getElementById('json-url').textContent = JSON_URL;
document.getElementById('json-link').href = JSON_URL;

// Initial load and auto-refresh every 2 seconds
refreshOtps();
setInterval(refreshOtps, 2000);
</script>

</body>
</html>
"""

if __name__ == '__main__':
    app.run(debug=True)