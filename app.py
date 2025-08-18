from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import os
import pytz
from datetime import datetime

app = Flask(__name__)
auth = HTTPBasicAuth()

# Configuration
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

LOG_FILE = 'access.log'
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        f.write('')

# Status and statistics
status = "redy"
access_count = 0
downloads = {}
uploads = {}
status_changes = []
cuba_timezone = pytz.timezone('America/Havana')
cuba_time = datetime.now(cuba_timezone)

# Users
users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "Carlos": generate_password_hash("carlos334087"),
    "Nathan": generate_password_hash("123nathan")
}

# Helper functions
def log_access(username, endpoint, action):
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    global access_count
    access_count += 1

def get_today_access_count():
    today = cuba_time.strftime('%Y-%m-%d')
    count = 0
    
    with open(LOG_FILE, 'r') as f:
        for line in f:
            if line.startswith(today):
                count += 1
                
    return count

# Authentication
@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# Routes
@app.route('/')
@auth.login_required
def index():
    username = auth.current_user()
    
    # Get logs
    with open(LOG_FILE, 'r') as f:
        logs = f.readlines()
    
    # Get statistics
    today_access = get_today_access_count()
    upload_list = [f"{file} (Subido el {time})" for file, time in uploads.items()]
    download_list = [f"{file} (Bajado el {time})" for file, time in downloads.items()]
    status_history = status_changes.copy()
    
    return render_template('admin.html',
                         status=status,
                         access_count=access_count,
                         today_access=today_access,
                         uploads=upload_list,
                         downloads=download_list,
                         status_history=status_history,
                         logs=logs)

@app.route('/status')
def get_status():
    log_access("Kilito", '/', 'Abierto')
    return status

@app.route('/status_bank')
def gggg():
    log_access("Banco", '/', 'Abierto')
    return status

@app.route('/statuschange', methods=['POST'])
@auth.login_required
def change_status():
    global status
    new_status = request.form.get('new_status')
    if new_status in ['redy', 'destroy']:
        username = auth.current_user()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status_changes.append(f"{status} -> {new_status} at {timestamp} by {username}")
        status = new_status
        log_access(username, '/statuschange', f"changed status to {new_status}")
        return f"Estado cambiado a {new_status}"
    return "Invalid status", 400

@app.route('/lastupdatekilo')
def uplast():
    return "3"

@app.route('/downloadkilo')
def down():
    return "Contacte con el creador para obtener la ultima versión"

@app.route('/download/<filename>', methods=['GET'])
@auth.login_required
def download_file(filename):
    username = auth.current_user()
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        log_access(username, f'/download/{filename}', 'attempted download (file not found)')
        return "noexiste esa mecanica", 404
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    downloads[filename] = timestamp
    log_access("Banco", f'/download/{filename}', f'Bajando lista turno: {filename}')
    
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route('/upload', methods=['POST'])
@auth.login_required
def upload_file():
    username = auth.current_user()
    if 'archivo' not in request.files:
        log_access(username, '/upload', 'attempted upload (no file part)')
        return "error mo se llama archivo en el formulario", 400
    
    file = request.files['archivo']
    if file.filename == '':
        log_access(username, '/upload', 'attempted upload (empty filename)')
        return "orror nombre de archivo mal", 400
    
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    uploads[file.filename] = timestamp
    log_access("Kilito", '/upload', f'Lista agregada correctamente Turno: {file.filename}')
    
    return "Lista agregada correctamente Turno: "+file.filename

@app.route('/files', methods=['GET'])
def list_files():
    username = auth.current_user()
    log_access("Banco", '/files', 'Leyendo listas')
    files = os.listdir(UPLOAD_FOLDER)
    return jsonify({"Listas": files})

@app.route('/delete/<filename>', methods=['DELETE'])
@auth.login_required
def delete_file(filename):
    username = auth.current_user()
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        log_access(username, f'/delete/{filename}', 'attempted delete (file not found)')
        return "Lista no encontrada", 404
    
    os.remove(file_path)
    log_access("Banco", f'/delete/{filename}', 'borrando lista')
    return "Lista eliminada correctamente"

