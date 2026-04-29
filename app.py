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

# ── Storage ──────────────────────────────────────────────────────────
# otps = { phone_number: { otp, timestamp, timer } }
otps = {}
lock = threading.Lock()

WORD_TO_DIGIT = {
    'Zero': '0', 'One': '1', 'Two': '2', 'Three': '3', 'Four': '4',
    'Five': '5', 'Six': '6', 'Seven': '7', 'Eight': '8', 'Nine': '9'
}

def reset_otp(phone_number):
    with lock:
        if phone_number in otps:
            otps[phone_number]['otp'] = None
            otps[phone_number]['timestamp'] = None
            print(f"OTP expired for {phone_number}")

# ── Universal OTP Receiver ───────────────────────────────────────────
@app.route('/receive_otp', methods=['POST', 'OPTIONS'])
def receive_otp():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    message = data.get('message', '')
    phone_number = data.get('phone_number', 'Unknown')

    if phone_number == "Unknown" or not phone_number:
        return jsonify({'status': 'ignored', 'message': 'Unknown phone number.'}), 200

    if "IVACBD" not in message:
        return jsonify({'status': 'error', 'message': 'Invalid source.'}), 400

    words = re.findall(r'\b(?:Zero|One|Two|Three|Four|Five|Six|Seven|Eight|Nine)\b', message)
    if len(words) < 6:
        return jsonify({'status': 'error', 'message': '6-digit OTP not found.'}), 400

    otp_string = "".join(WORD_TO_DIGIT[w] for w in words[-6:])

    with lock:
        # Cancel existing timer if any
        if phone_number in otps and otps[phone_number].get('timer'):
            otps[phone_number]['timer'].cancel()
        
        # Store OTP with phone number
        otps[phone_number] = {
            'otp': otp_string,
            'timestamp': time.time(),
            'timer': None
        }
        
        # Start 3-minute timer
        timer = threading.Timer(180, reset_otp, args=[phone_number])
        timer.start()
        otps[phone_number]['timer'] = timer

    print(f"[{phone_number}] OTP received: {otp_string}")
    return jsonify({'status': 'success', 'otp': otp_string, 'phone': phone_number}), 200

# ── API: Get all OTPs ────────────────────────────────────────────────
@app.route('/api/otps', methods=['GET'])
def get_all_otps():
    with lock:
        result = []
        for phone, data in otps.items():
            otp = data['otp']
            time_left = 0
            if otp and data['timestamp']:
                time_left = int(180 - (time.time() - data['timestamp']))
                if time_left <= 0:
                    otp = None
                    time_left = 0
            
            result.append({
                'phone_number': phone,
                'otp': otp,
                'time_left': max(time_left, 0),
                'timestamp': data['timestamp'],
            })
        
        # Sort by timestamp (newest first)
        result.sort(key=lambda x: x['timestamp'] or 0, reverse=True)
        return jsonify(result)

# ── API: Get OTP by Phone ───────────────────────────────────────────
@app.route('/api/otp/<path:phone>', methods=['GET'])
def get_otp_by_phone(phone):
    with lock:
        if phone in otps:
            data = otps[phone]
            otp = data['otp']
            time_left = 0
            if otp and data['timestamp']:
                time_left = int(180 - (time.time() - data['timestamp']))
                if time_left <= 0:
                    otp = None
                    time_left = 0
            return jsonify({
                'phone': phone,
                'otp': otp,
                'time_left': max(time_left, 0)
            })
        return jsonify({'error': 'Phone not found'}), 404


# ── Clear single OTP ─────────────────────────────────────────────────
@app.route('/api/clear/<path:phone_number>', methods=['DELETE'])
def clear_otp(phone_number):
    with lock:
        if phone_number in otps:
            if otps[phone_number].get('timer'):
                otps[phone_number]['timer'].cancel()
            del otps[phone_number]
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
@media(max-width:768px){
 .header{padding:20px 16px;} .header h1{font-size:22px;}
 .endpoint-box{padding:12px;margin:16px;flex-direction:column;}
 .endpoint-url{font-size:12px;min-width:auto;}
 .table-wrap{padding:0 8px 20px;}
 td,th{padding:10px 8px;font-size:12px;}
 .otp-val{font-size:18px;letter-spacing:4px;}
 .btn-copy, .btn-del{padding:4px 10px;font-size:11px;}
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
                <th>Live OTP</th>
                <th>Timer</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="otp-table">
            <tr><td colspan="4"><div class="empty"><div class="icon">📱</div><p>Waiting for OTPs…<br>Send SMS to the endpoint above.</p></div></td></tr>
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
                : `<div style="display:flex;align-items:center;gap:8px;"><span class="pulse idle"></span><span class="otp-waiting">Expired</span></div>`;
            const timerHtml = d.otp ? `<div class="timer">${fmtTimer(d.time_left)}</div>` : '—';
            const copyBtn = d.otp ? `<button class="btn-copy" onclick="copyText('${d.otp}')">📋 Copy OTP</button>` : '';
            
            return `<tr>
                <td class="phone-col">${d.phone_number}</td>
                <td>${otpHtml}</td>
                <td>${timerHtml}</td>
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