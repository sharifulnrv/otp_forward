from flask import Flask, request, jsonify
import re
import threading
import time
import uuid
import sqlite3
import os

app = Flask(__name__)

# ── CORS (allow bookmark fetch from any site) ─────────────────────────
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept, ngrok-skip-browser-warning'
    return response

@app.route('/otp_json/<device_id>', methods=['OPTIONS'])
@app.route('/otp/<device_id>', methods=['OPTIONS'])
@app.route('/get_otp/<device_id>', methods=['OPTIONS'])
def handle_options(device_id):
    return '', 204

# ── Multi-device storage ──────────────────────────────────────────────
# devices = { device_id: { name, otp, otp_timestamp, last_seen, created_at, timer } }
devices = {}
lock = threading.Lock()

WORD_TO_DIGIT = {
    'Zero': '0', 'One': '1', 'Two': '2', 'Three': '3', 'Four': '4',
    'Five': '5', 'Six': '6', 'Seven': '7', 'Eight': '8', 'Nine': '9'
}

DB_PATH = 'devices.db'

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        conn.commit()

def load_devices_from_db():
    global devices
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('SELECT id, name, created_at FROM devices')
        for row in cursor:
            did, name, created_at = row
            devices[did] = {
                'name': name,
                'otp': None,
                'otp_timestamp': None,
                'last_seen': None,
                'created_at': created_at,
                'timer': None
            }
    print(f"Loaded {len(devices)} devices from database.")

def save_device_to_db(did, name, created_at):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT INTO devices (id, name, created_at) VALUES (?, ?, ?)', (did, name, created_at))
        conn.commit()

def delete_device_from_db(did):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM devices WHERE id = ?', (did,))
        conn.commit()


def reset_otp(device_id):
    with lock:
        if device_id in devices:
            devices[device_id]['otp'] = None
            devices[device_id]['otp_timestamp'] = None
            print(f"OTP reset for device {devices[device_id]['name']} ({device_id})")


# ── API Endpoints ─────────────────────────────────────────────────────

@app.route('/api/devices', methods=['GET'])
def api_list_devices():
    with lock:
        result = []
        for did, dev in devices.items():
            time_left = 0
            otp = dev['otp']
            if otp and dev['otp_timestamp']:
                time_left = int(180 - (time.time() - dev['otp_timestamp']))
                if time_left <= 0:
                    otp = None
                    time_left = 0
            result.append({
                'id': did,
                'name': dev['name'],
                'otp': otp,
                'time_left': max(time_left, 0),
                'last_seen': dev.get('last_seen'),
                'created_at': dev.get('created_at'),
            })
        return jsonify(result)


@app.route('/api/devices', methods=['POST'])
def api_add_device():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Device name is required'}), 400

    device_id = uuid.uuid4().hex[:8]
    created_at = time.time()
    with lock:
        devices[device_id] = {
            'name': name,
            'otp': None,
            'otp_timestamp': None,
            'last_seen': None,
            'created_at': created_at,
        }
    save_device_to_db(device_id, name, created_at)
    return jsonify({'id': device_id, 'name': name}), 201


@app.route('/api/devices/<device_id>', methods=['DELETE'])
def api_delete_device(device_id):
    with lock:
        if device_id in devices:
            t = devices[device_id].get('timer')
            if t:
                t.cancel()
            del devices[device_id]
            delete_device_from_db(device_id)
            return jsonify({'status': 'deleted'}), 200
        return jsonify({'error': 'Device not found'}), 404


# ── SMS Forwarding (per device) ──────────────────────────────────────

@app.route('/forward_sms/<device_id>', methods=['POST'])
def forward_sms(device_id):
    with lock:
        if device_id not in devices:
            return jsonify({'status': 'error', 'message': 'Unknown device'}), 404

    data = request.get_json()
    message = data.get('message', '')

    if "IVACBD" not in message:
        return jsonify({'status': 'error', 'message': 'Invalid source.'}), 400

    words = re.findall(r'\b(?:Zero|One|Two|Three|Four|Five|Six|Seven|Eight|Nine)\b', message)
    if len(words) < 6:
        return jsonify({'status': 'error', 'message': '6-digit word OTP not found.'}), 400

    otp_string = "".join(WORD_TO_DIGIT[w] for w in words[-6:])

    with lock:
        dev = devices[device_id]
        # Cancel any existing timer
        if dev.get('timer'):
            dev['timer'].cancel()
        dev['otp'] = otp_string
        dev['otp_timestamp'] = time.time()
        dev['last_seen'] = time.time()
        timer = threading.Timer(180, reset_otp, args=[device_id])
        timer.start()
        dev['timer'] = timer

    print(f"[{devices[device_id]['name']}] OTP received: {otp_string}")
    return jsonify({'status': 'success', 'message': 'OTP received!'}), 200


# ── Raw OTP (per device) ─────────────────────────────────────────────

@app.route('/get_otp/<device_id>', methods=['GET'])
def get_raw_otp(device_id):
    with lock:
        dev = devices.get(device_id)
        if not dev:
            return "Device not found", 404
        if dev['otp'] and dev['otp_timestamp']:
            tl = int(180 - (time.time() - dev['otp_timestamp']))
            if tl <= 0:
                reset_otp(device_id)
                return "OTP expired", 404
            return dev['otp']
        return "No OTP available", 404


# ── JSON OTP API (per device) ────────────────────────────────────────
@app.route('/otp_json/<device_id>', methods=['GET'])
def get_otp_json(device_id):
    with lock:
        dev = devices.get(device_id)
        if not dev:
            return jsonify({"otp": None, "error": "Device not found"}), 404
        otp_val = dev['otp']
        if otp_val and dev['otp_timestamp']:
            time_left = int(180 - (time.time() - dev['otp_timestamp']))
            if time_left <= 0:
                reset_otp(device_id)
                return jsonify({"otp": None, "error": "OTP expired"}), 404
            return jsonify({"otp": otp_val, "time_left": time_left})
        return jsonify({"otp": None, "error": "No OTP available"}), 404

# ── Pretty OTP Viewer (per device) ───────────────────────────────────

@app.route('/otp/<device_id>', methods=['GET'])
def otp_page(device_id):
    with lock:
        dev = devices.get(device_id)
        if not dev:
            return "<h2>Device not found</h2>", 404

        otp_val = dev['otp']
        dev_name = dev['name']
        if otp_val and dev['otp_timestamp']:
            time_left = int(180 - (time.time() - dev['otp_timestamp']))
            if time_left <= 0:
                otp_val = None

    if not otp_val:
        return f"""
        <html>
        <head>
            <title>No OTP — {dev_name}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="refresh" content="5">
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
                body {{ font-family:'Inter',sans-serif; background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh; margin:0; }}
                .card {{ background:rgba(30,41,59,.85); backdrop-filter:blur(16px); padding:40px 30px; border-radius:20px; text-align:center; max-width:400px; width:90%; border:1px solid rgba(148,163,184,.15); }}
                .card h2 {{ color:#f87171; font-size:22px; margin:10px 0 8px; }}
                .card p {{ color:#94a3b8; font-size:15px; }}
                .icon {{ font-size:50px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon">📭</div>
                <h2>No OTP — {dev_name}</h2>
                <p>Waiting for OTP…<br>Auto-refreshing every 5s.</p>
            </div>
        </body>
        </html>
        """, 404

    return f"""
    <html>
    <head>
        <title>OTP — {dev_name}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
            body {{ font-family:'Inter',sans-serif; background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh; margin:0; }}
            .card {{ background:rgba(30,41,59,.85); backdrop-filter:blur(16px); padding:36px 30px; border-radius:20px; text-align:center; max-width:400px; width:90%; border:1px solid rgba(148,163,184,.15); }}
            .label {{ color:#94a3b8; font-size:13px; text-transform:uppercase; letter-spacing:2px; margin-bottom:6px; }}
            .otp {{ font-size:40px; font-weight:700; color:#38bdf8; letter-spacing:8px; margin:10px 0 18px; }}
            .msg {{ font-size:14px; color:#64748b; margin-bottom:18px; }}
            #countdown {{ font-size:13px; color:#f87171; font-weight:600; margin-bottom:22px; }}
            .btn {{ display:block; width:100%; padding:12px; margin:6px 0; font-size:14px; border:none; border-radius:10px; cursor:pointer; color:#fff; font-weight:600; transition:.2s; text-decoration:none; text-align:center; box-sizing:border-box; }}
            .btn-copy {{ background:#6366f1; }} .btn-copy:hover {{ background:#4f46e5; }}
            .btn-refresh {{ background:#0ea5e9; }} .btn-refresh:hover {{ background:#0284c7; }}
            .toast {{ display:none; margin-top:10px; font-size:12px; color:#34d399; font-weight:600; }}
        </style>
        <script>
            let timeLeft = {time_left};
            function startCountdown() {{
                const el = document.getElementById("countdown");
                setInterval(() => {{
                    if (timeLeft <= 0) {{ el.textContent = "OTP expired"; setTimeout(() => location.reload(), 1000); }}
                    else {{ let m = Math.floor(timeLeft/60), s = timeLeft%60; el.textContent = "⏳ " + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0"); timeLeft--; }}
                }}, 1000);
            }}
            function copyOTP() {{
                navigator.clipboard.writeText(document.getElementById("otp-value").innerText.replace(/\\s/g,""));
                const t = document.getElementById("toast"); t.style.display="block"; setTimeout(()=>t.style.display="none",1500);
            }}
            window.onload = startCountdown;
        </script>
    </head>
    <body>
        <div class="card">
            <div class="label">{dev_name}</div>
            <div class="otp" id="otp-value">{otp_val}</div>
            <div class="msg">Use this PIN within 3 minutes. Do not share.</div>
            <div id="countdown"></div>
            <button class="btn btn-copy" onclick="copyOTP()">📋 Copy OTP</button>
            <div id="toast" class="toast">✅ Copied!</div>
            <a href="/otp/{device_id}" class="btn btn-refresh">🔄 Refresh</a>
        </div>
    </body>
    </html>
    """


# ── Admin Dashboard ──────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OTP Command Center</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Inter',sans-serif;background:#0b0f19;color:#e2e8f0;min-height:100vh;}

/* ── Header ─────────────────────────────── */
.header{background:linear-gradient(135deg,#1e1b4b 0%,#0f172a 50%,#0c1222 100%);padding:28px 32px;border-bottom:1px solid rgba(99,102,241,.2);}
.header h1{font-size:26px;font-weight:700;background:linear-gradient(135deg,#818cf8,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;display:flex;align-items:center;gap:12px;}
.header h1 span{font-size:28px;-webkit-text-fill-color:initial;}
.header p{color:#64748b;font-size:13px;margin-top:4px;}

/* ── Toolbar ────────────────────────────── */
.toolbar{display:flex;align-items:center;justify-content:space-between;padding:16px 32px;flex-wrap:wrap;gap:12px;}
.stats{display:flex;gap:16px;}
.stat-chip{background:rgba(30,41,59,.6);border:1px solid rgba(148,163,184,.1);padding:8px 18px;border-radius:10px;font-size:13px;color:#94a3b8;}
.stat-chip b{color:#e2e8f0;margin-left:4px;}
.btn-add{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border:none;padding:10px 22px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s;display:flex;align-items:center;gap:6px;}
.btn-add:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(99,102,241,.35);}

/* ── Table ──────────────────────────────── */
.table-wrap{padding:0 32px 32px;}
table{width:100%;border-collapse:separate;border-spacing:0;background:rgba(15,23,42,.7);border-radius:16px;overflow:hidden;border:1px solid rgba(148,163,184,.08);}
thead th{background:rgba(30,41,59,.9);color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;padding:14px 16px;text-align:left;font-weight:600;white-space:nowrap;}
tbody tr{border-bottom:1px solid rgba(148,163,184,.06);transition:.15s;}
tbody tr:hover{background:rgba(99,102,241,.04);}
td{padding:14px 16px;font-size:13px;vertical-align:middle;}
td:first-child{font-weight:600;color:#c7d2fe;}

/* OTP cell */
.otp-val{font-family:'Inter',monospace;font-size:20px;font-weight:700;letter-spacing:4px;color:#38bdf8;}
.otp-none{color:#475569;font-style:italic;font-size:12px;}
.otp-expired{color:#f87171;font-size:12px;}

/* Timer */
.timer{font-size:12px;color:#f87171;font-weight:600;}

/* Links */
.link-box{display:flex;align-items:center;gap:6px;}
.link-text{background:rgba(30,41,59,.8);padding:4px 10px;border-radius:6px;font-size:11px;color:#94a3b8;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:monospace;}
.btn-sm{background:rgba(99,102,241,.15);color:#818cf8;border:none;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;transition:.15s;white-space:nowrap;}
.btn-sm:hover{background:rgba(99,102,241,.3);}

/* Action buttons */
.btn-del{background:rgba(239,68,68,.1);color:#f87171;border:none;padding:6px 14px;border-radius:8px;font-size:12px;cursor:pointer;transition:.15s;font-weight:500;}
.btn-del:hover{background:rgba(239,68,68,.25);}
.btn-otp-copy{background:rgba(34,197,94,.1);color:#4ade80;border:none;padding:6px 14px;border-radius:8px;font-size:12px;cursor:pointer;transition:.15s;font-weight:500;}
.btn-otp-copy:hover{background:rgba(34,197,94,.25);}

/* Empty state */
.empty{text-align:center;padding:60px 20px;color:#475569;}
.empty .icon{font-size:48px;margin-bottom:12px;}
.empty p{font-size:14px;}

/* ── Modal ──────────────────────────────── */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:100;justify-content:center;align-items:center;}
.modal-overlay.active{display:flex;}
.modal{background:#1e293b;border-radius:20px;padding:32px;width:90%;max-width:420px;border:1px solid rgba(148,163,184,.12);}
.modal h2{font-size:20px;color:#e2e8f0;margin-bottom:20px;}
.modal input{width:100%;padding:12px 16px;background:#0f172a;border:1px solid rgba(148,163,184,.15);border-radius:10px;color:#e2e8f0;font-size:14px;outline:none;transition:.2s;}
.modal input:focus{border-color:#6366f1;}
.modal-btns{display:flex;gap:10px;margin-top:20px;}
.modal-btns button{flex:1;padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s;}
.modal-btns .cancel{background:rgba(148,163,184,.1);color:#94a3b8;}
.modal-btns .cancel:hover{background:rgba(148,163,184,.2);}
.modal-btns .confirm{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;}
.modal-btns .confirm:hover{box-shadow:0 4px 16px rgba(99,102,241,.35);}

/* ── Toast ──────────────────────────────── */
.toast{position:fixed;bottom:28px;right:28px;background:#1e293b;color:#4ade80;padding:12px 22px;border-radius:12px;font-size:13px;font-weight:600;border:1px solid rgba(74,222,128,.2);opacity:0;transition:.3s;pointer-events:none;z-index:200;}
.toast.show{opacity:1;}

/* ── Pulse dot ──────────────────────────── */
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;}
.pulse.live{background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.5);animation:pulse-ring 1.5s infinite;}
.pulse.idle{background:#475569;}
@keyframes pulse-ring{0%{box-shadow:0 0 0 0 rgba(74,222,128,.45);}70%{box-shadow:0 0 0 8px rgba(74,222,128,0);}100%{box-shadow:0 0 0 0 rgba(74,222,128,0);}}

/* Responsive */
@media(max-width:768px){
 .header{padding:20px 16px;} .header h1{font-size:20px;}
 .toolbar{padding:12px 16px;} .table-wrap{padding:0 8px 20px;}
 td,th{padding:10px 8px;font-size:12px;} .otp-val{font-size:16px;letter-spacing:2px;}
 .link-text{max-width:100px;} .stats{display:none;}
}
</style>
</head>
<body>

<div class="header">
    <h1><span>📡</span> OTP Command Center</h1>
    <p>Multi-device OTP management dashboard — live monitoring</p>
</div>

<div class="toolbar">
    <div class="stats">
        <div class="stat-chip">📱 Devices: <b id="device-count">0</b></div>
        <div class="stat-chip">🔑 Active OTPs: <b id="active-count">0</b></div>
    </div>
    <button class="btn-add" onclick="openModal()">＋ Add Device</button>
</div>

<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Device</th>
                <th>Live OTP</th>
                <th>Timer</th>
                <th>Forward Link</th>
                <th>JSON Link</th>
                <th>View Link</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="device-table">
            <tr id="empty-row"><td colspan="6"><div class="empty"><div class="icon">📱</div><p>No devices yet. Click <b>+ Add Device</b> to get started.</p></div></td></tr>
        </tbody>
    </table>
</div>

<!-- Modal -->
<div class="modal-overlay" id="modal">
    <div class="modal">
        <h2>Add New Device</h2>
        <input type="text" id="device-name" placeholder="e.g. Motinbhai Phone 1" autofocus>
        <div class="modal-btns">
            <button class="cancel" onclick="closeModal()">Cancel</button>
            <button class="confirm" onclick="addDevice()">Add Device</button>
        </div>
    </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
const BASE = location.origin;

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}

function copyText(text) {
    navigator.clipboard.writeText(text).then(() => showToast('📋 Copied to clipboard!'));
}

function openModal() { document.getElementById('modal').classList.add('active'); document.getElementById('device-name').value=''; document.getElementById('device-name').focus(); }
function closeModal() { document.getElementById('modal').classList.remove('active'); }

async function addDevice() {
    const name = document.getElementById('device-name').value.trim();
    if (!name) return;
    const res = await fetch('/api/devices', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name}) });
    if (res.ok) { closeModal(); showToast('✅ Device added!'); refreshDevices(); }
}

async function deleteDevice(id) {
    if (!confirm('Delete this device?')) return;
    await fetch('/api/devices/' + id, { method:'DELETE' });
    showToast('🗑️ Device removed'); refreshDevices();
}

function fmtTimer(secs) {
    if (secs <= 0) return '';
    const m = Math.floor(secs/60), s = secs%60;
    return String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}

async function refreshDevices() {
    try {
        const res = await fetch('/api/devices');
        const devs = await res.json();
        const tbody = document.getElementById('device-table');
        document.getElementById('device-count').textContent = devs.length;
        document.getElementById('active-count').textContent = devs.filter(d => d.otp).length;

        if (devs.length === 0) {
            tbody.innerHTML = '<tr id="empty-row"><td colspan="6"><div class="empty"><div class="icon">📱</div><p>No devices yet. Click <b>+ Add Device</b> to get started.</p></div></td></tr>';
            return;
        }

        tbody.innerHTML = devs.map(d => {
            const fwdLink = BASE + '/forward_sms/' + d.id;
            const jsonLink = BASE + '/otp_json/' + d.id;
            const viewLink = BASE + '/otp/' + d.id;
            const otpHtml = d.otp
                ? `<span class="pulse live"></span><span class="otp-val">${d.otp}</span>`
                : `<span class="pulse idle"></span><span class="otp-none">Waiting…</span>`;
            const timerHtml = d.otp ? `<span class="timer">⏳ ${fmtTimer(d.time_left)}</span>` : '—';
            const copyOtpBtn = d.otp ? `<button class="btn-otp-copy" onclick="copyText('${d.otp}')">📋 Copy OTP</button>` : '';

            return `<tr>
                <td>${d.name}</td>
                <td>${otpHtml}</td>
                <td>${timerHtml}</td>
                <td><div class="link-box"><span class="link-text" title="${fwdLink}">${fwdLink}</span><button class="btn-sm" onclick="copyText('${fwdLink}')">Copy</button></div></td>
                <td><div class="link-box"><span class="link-text" title="${jsonLink}">${jsonLink}</span><button class="btn-sm" onclick="copyText('${jsonLink}')">Copy</button></div></td>
                <td><div class="link-box"><a href="${viewLink}" target="_blank" class="btn-sm" style="text-decoration:none">Open</a><button class="btn-sm" onclick="copyText('${viewLink}')">Copy</button></div></td>
                <td style="display:flex;gap:6px;flex-wrap:wrap;">${copyOtpBtn}<button class="btn-del" onclick="deleteDevice('${d.id}')">🗑 Delete</button></td>
            </tr>`;
        }).join('');

    } catch(e) { console.error('Refresh error:', e); }
}

// Enter key to submit
document.getElementById('device-name').addEventListener('keydown', e => { if(e.key==='Enter') addDevice(); });

// Auto-refresh every 3 seconds
refreshDevices();
setInterval(refreshDevices, 3000);
</script>

</body>
</html>
"""

if __name__ == '__main__':
    load_devices_from_db()
    app.run(debug=True)