"""
============================================
CLONE TRACKING SERVER
============================================

This server tracks cloned websites and manages the approval system.

FEATURES:
- Receives registration requests from clone websites
- Tracks visitor IPs using request headers
- Maintains a queue for new/unverified clones
- Admin can approve or reject clones from queue
- Admin can kick (remove) approved clones
- Tracks request counts per clone
- Returns list of approved clones to clients

ENDPOINTS:
    POST /api/register      - Clone registers itself (sends {name: "url"})
    GET  /api/clones        - Get list of approved clones
    GET  /admin             - Admin dashboard
    POST /admin/approve     - Approve a clone from queue
    POST /admin/reject      - Reject a clone from queue
    POST /admin/kick        - Remove an approved clone

SETUP:
1. pip install flask flask-cors
2. Change ADMIN_PASSWORD below
3. Run: python tracking_server.py
4. Update TRACKING_SERVER_URL in index.html to point to this server

============================================
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from datetime import datetime
from collections import defaultdict
import json
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests from clone sites

# ============================================
# CONFIGURATION - CHANGE THESE
# ============================================

# ============================================
# CHANGE THESE VALUES FOR PRODUCTION
# ============================================

# CHANGE THIS: Admin password for the dashboard (use a strong password!)
ADMIN_PASSWORD = ''  # e.g., 'your-secure-password-here'

# CHANGE THIS: Port to run on
PORT = 5000

# CHANGE THIS: The original site URL (always shown in list, can't be kicked)
ORIGINAL_SITE_URL = ''  # e.g., 'https://your-original-site.com'

# Data file paths
DATA_DIR = 'data'
APPROVED_FILE = os.path.join(DATA_DIR, 'approved_clones.json')
QUEUE_FILE = os.path.join(DATA_DIR, 'queue.json')
REQUESTS_FILE = os.path.join(DATA_DIR, 'requests.json')

# ============================================
# DATA STORAGE
# ============================================

def ensure_data_dir():
    """Create data directory if it doesn't exist"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_json(filepath, default):
    """Load JSON file or return default"""
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return default

def save_json(filepath, data):
    """Save data to JSON file"""
    ensure_data_dir()
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def get_approved_clones():
    """Get list of approved clone URLs"""
    return load_json(APPROVED_FILE, [])

def save_approved_clones(clones):
    """Save approved clone URLs"""
    save_json(APPROVED_FILE, clones)

def get_queue():
    """Get list of clones pending approval"""
    return load_json(QUEUE_FILE, [])

def save_queue(queue):
    """Save queue"""
    save_json(QUEUE_FILE, queue)

def get_request_counts():
    """Get request counts per clone"""
    return load_json(REQUESTS_FILE, {})

def save_request_counts(counts):
    """Save request counts"""
    save_json(REQUESTS_FILE, counts)

# ============================================
# IP DETECTION
# ============================================

def get_visitor_ip():
    """
    Get the real IP address of the visitor.
    Checks various headers that proxies/load balancers set.
    """
    # Check X-Forwarded-For header (set by proxies)
    if request.headers.get('X-Forwarded-For'):
        # Can be comma-separated list, first is the real IP
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()

    # Check X-Real-IP header (set by nginx)
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')

    # Check CF-Connecting-IP header (set by Cloudflare)
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')

    # Fall back to remote_addr
    return request.remote_addr

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/api/register', methods=['POST'])
def register_clone():
    """
    Called by clone websites when a user visits.
    Registers new clones to the queue and tracks requests.

    Expected body: { "name": "https://clone-site.com" }
    """
    data = request.get_json()

    if not data or 'name' not in data:
        return jsonify({'error': 'Missing name field'}), 400

    clone_url = data['name']
    visitor_ip = get_visitor_ip()

    # Get current data
    approved = get_approved_clones()
    queue = get_queue()
    request_counts = get_request_counts()

    # Check if clone is already approved
    if clone_url in approved:
        # Increment request count
        request_counts[clone_url] = request_counts.get(clone_url, 0) + 1
        save_request_counts(request_counts)
        return jsonify({'status': 'approved', 'requests': request_counts[clone_url]})

    # Check if clone is already in queue
    queue_urls = [item['url'] for item in queue]
    if clone_url in queue_urls:
        return jsonify({'status': 'pending'})

    # Add to queue (new clone discovered)
    queue.append({
        'url': clone_url,
        'first_seen': datetime.now().isoformat(),
        'discovered_by_ip': visitor_ip
    })
    save_queue(queue)

    return jsonify({'status': 'queued'})

@app.route('/api/clones', methods=['GET'])
def get_clones():
    """
    Returns list of approved clones with their request counts.
    Called by clone websites to display the sidebar list.
    """
    approved = get_approved_clones()
    request_counts = get_request_counts()

    clones = []

    # Add original site first if configured
    if ORIGINAL_SITE_URL:
        clones.append({
            'url': ORIGINAL_SITE_URL,
            'requests': request_counts.get(ORIGINAL_SITE_URL, 0),
            'is_original': True
        })

    # Add approved clones
    for url in approved:
        if url != ORIGINAL_SITE_URL:  # Don't duplicate original
            clones.append({
                'url': url,
                'requests': request_counts.get(url, 0),
                'is_original': False
            })

    return jsonify({'clones': clones})

# ============================================
# ADMIN DASHBOARD
# ============================================

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Clone Tracker Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 40px;
        }
        h1 {
            color: #a855f7;
            margin-bottom: 30px;
            font-size: 28px;
        }
        h2 {
            color: #888;
            margin: 30px 0 15px;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .section {
            background: rgba(30, 30, 50, 0.8);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 15px;
            background: rgba(40, 40, 60, 0.6);
            border-radius: 8px;
            margin-bottom: 10px;
        }
        .item-info {
            flex: 1;
        }
        .item-url {
            color: #ccc;
            font-size: 14px;
            word-break: break-all;
        }
        .item-meta {
            color: #666;
            font-size: 12px;
            margin-top: 4px;
        }
        .item-requests {
            background: rgba(99, 102, 241, 0.2);
            color: #818cf8;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            margin-right: 15px;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            margin-left: 8px;
            transition: all 0.2s;
        }
        .btn-approve {
            background: #10b981;
            color: white;
        }
        .btn-approve:hover { background: #059669; }
        .btn-reject {
            background: #ef4444;
            color: white;
        }
        .btn-reject:hover { background: #dc2626; }
        .btn-kick {
            background: #f59e0b;
            color: white;
        }
        .btn-kick:hover { background: #d97706; }
        .empty {
            color: #555;
            text-align: center;
            padding: 30px;
        }
        .original-badge {
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            margin-right: 15px;
        }
        .login-form {
            max-width: 400px;
            margin: 100px auto;
            text-align: center;
        }
        .login-form input {
            width: 100%;
            padding: 14px;
            margin: 10px 0;
            border: 2px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: rgba(30,30,50,0.8);
            color: #fff;
            font-size: 16px;
        }
        .login-form button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #a855f7 0%, #6366f1 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
        }
    </style>
</head>
<body>
    {% if not authenticated %}
    <div class="login-form">
        <h1>Admin Login</h1>
        <form method="POST" action="/admin">
            <input type="password" name="password" placeholder="Enter admin password" required>
            <button type="submit">Login</button>
        </form>
    </div>
    {% else %}
    <h1>Clone Tracker Admin</h1>

    <h2>Pending Approval ({{ queue|length }})</h2>
    <div class="section">
        {% if queue %}
            {% for item in queue %}
            <div class="item">
                <div class="item-info">
                    <div class="item-url">{{ item.url }}</div>
                    <div class="item-meta">First seen: {{ item.first_seen }} | IP: {{ item.discovered_by_ip }}</div>
                </div>
                <form method="POST" action="/admin/approve" style="display:inline">
                    <input type="hidden" name="url" value="{{ item.url }}">
                    <input type="hidden" name="password" value="{{ password }}">
                    <button type="submit" class="btn btn-approve">Approve</button>
                </form>
                <form method="POST" action="/admin/reject" style="display:inline">
                    <input type="hidden" name="url" value="{{ item.url }}">
                    <input type="hidden" name="password" value="{{ password }}">
                    <button type="submit" class="btn btn-reject">Reject</button>
                </form>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">No clones pending approval</div>
        {% endif %}
    </div>

    <h2>Approved Clones ({{ approved|length }})</h2>
    <div class="section">
        {% if approved %}
            {% for url in approved %}
            <div class="item">
                <div class="item-info">
                    <div class="item-url">{{ url }}</div>
                </div>
                {% if url == original_url %}
                    <span class="original-badge">ORIGINAL</span>
                {% else %}
                    <span class="item-requests">{{ request_counts.get(url, 0) }} requests</span>
                    <form method="POST" action="/admin/kick" style="display:inline">
                        <input type="hidden" name="url" value="{{ url }}">
                        <input type="hidden" name="password" value="{{ password }}">
                        <button type="submit" class="btn btn-kick">Kick</button>
                    </form>
                {% endif %}
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">No approved clones yet</div>
        {% endif %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    """Admin dashboard for managing clones"""
    authenticated = False
    password = ''

    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            authenticated = True

    if not authenticated:
        return render_template_string(ADMIN_HTML, authenticated=False)

    queue = get_queue()
    approved = get_approved_clones()
    request_counts = get_request_counts()

    # Sort approved by request count
    approved_sorted = sorted(approved, key=lambda x: request_counts.get(x, 0), reverse=True)

    return render_template_string(
        ADMIN_HTML,
        authenticated=True,
        password=password,
        queue=queue,
        approved=approved_sorted,
        request_counts=request_counts,
        original_url=ORIGINAL_SITE_URL
    )

@app.route('/admin/approve', methods=['POST'])
def approve_clone():
    """Approve a clone from the queue"""
    password = request.form.get('password', '')
    if password != ADMIN_PASSWORD:
        return 'Unauthorized', 401

    url = request.form.get('url', '')

    # Remove from queue
    queue = get_queue()
    queue = [item for item in queue if item['url'] != url]
    save_queue(queue)

    # Add to approved
    approved = get_approved_clones()
    if url not in approved:
        approved.append(url)
        save_approved_clones(approved)

    return admin_dashboard()

@app.route('/admin/reject', methods=['POST'])
def reject_clone():
    """Reject a clone from the queue"""
    password = request.form.get('password', '')
    if password != ADMIN_PASSWORD:
        return 'Unauthorized', 401

    url = request.form.get('url', '')

    # Remove from queue
    queue = get_queue()
    queue = [item for item in queue if item['url'] != url]
    save_queue(queue)

    return admin_dashboard()

@app.route('/admin/kick', methods=['POST'])
def kick_clone():
    """Remove an approved clone"""
    password = request.form.get('password', '')
    if password != ADMIN_PASSWORD:
        return 'Unauthorized', 401

    url = request.form.get('url', '')

    # Don't allow kicking the original
    if url == ORIGINAL_SITE_URL:
        return 'Cannot kick original site', 400

    # Remove from approved
    approved = get_approved_clones()
    approved = [u for u in approved if u != url]
    save_approved_clones(approved)

    return admin_dashboard()

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    ensure_data_dir()

    # Validate configuration
    if not ADMIN_PASSWORD:
        print('ERROR: ADMIN_PASSWORD is not set!')
        print('Please set a secure password in the configuration section.')
        exit(1)

    print('=' * 50)
    print('CLONE TRACKING SERVER')
    print('=' * 50)
    print(f'Running on http://0.0.0.0:{PORT}')
    print(f'Admin dashboard: http://localhost:{PORT}/admin')
    if ORIGINAL_SITE_URL:
        print(f'Original site: {ORIGINAL_SITE_URL}')
    else:
        print('WARNING: ORIGINAL_SITE_URL not set')
    print('=' * 50)
    print('')
    print('ENDPOINTS:')
    print(f'  POST /api/register  - Clone registration')
    print(f'  GET  /api/clones    - Get approved clones')
    print(f'  GET  /admin         - Admin dashboard')
    print('')
    print('For production, use a WSGI server like gunicorn:')
    print(f'  gunicorn -w 4 -b 0.0.0.0:{PORT} tracking_server:app')
    print('')

    app.run(host='0.0.0.0', port=PORT, debug=False)
