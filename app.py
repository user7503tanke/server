from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import os
import pytz
from datetime import datetime
import threading
import time
import requests
import random
import re

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

#######FIIIIIINAAAAALLLL###################
# Users
users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "Carlos": generate_password_hash("carlos334087"),
    "Nathan": generate_password_hash("123nathan")
}

# Helper functions
def log_access(username, endpoint, action):
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    global access_count
    access_count += 1

def get_today_access_count():
    cuba_time = datetime.now(cuba_timezone)
    today = cuba_time.strftime('%Y-%m-%d')
    count = 0
    
    with open(LOG_FILE, 'r') as f:
        for line in f:
            if line.startswith(today):
                count += 1
                
    return count

def validate_filename(filename):
    """
    Valida que el nombre del archivo siga el formato: [prefijo]-YYYY-MM-DD-Turno
    y que cumpla con los horarios establecidos para cada turno.
    """
    # Verificar el patrón del nombre - ahora el primer segmento puede ser cualquier palabra
    pattern = r'^[a-zA-Z]+-\d{4}-\d{2}-\d{2}-(Dia|Noche)$'
    if not re.match(pattern, filename):
        return False, "Formato de nombre inválido. Debe ser: [prefijo]-YYYY-MM-DD-Turno"
    
    # Extraer componentes
    try:
        parts = filename.split('-')
        prefix = parts[0]  # Primer segmento que puede variar (a, b, berde, asw, etc.)
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        turno = parts[4]
        
        # Verificar que la fecha sea válida
        file_date = datetime(year, month, day)
        
        # Obtener fecha y hora actual en Cuba
        cuba_now = datetime.now(cuba_timezone)
        current_date = cuba_now.date()
        current_time = cuba_now.time()
        
        # Verificar que la fecha del archivo sea hoy
        if file_date.date() != current_date:
            return False, "Solo se pueden subir listas del día actual"
        
        # Verificar horarios según el turno
        if turno == "Dia":
            # Para turno Dia: antes de 1:30 PM (13:30)
            limite_dia = datetime.strptime("13:30", "%H:%M").time()
            if current_time > limite_dia:
                return False, "El turno Dia solo se puede subir antes de las 1:29 PM, esta lista la banquea usted."
        
        elif turno == "Noche":
            # Para turno Noche: antes de 9:44 PM (21:44)
            limite_noche = datetime.strptime("21:44", "%H:%M").time()
            if current_time > limite_noche:
                return False, "El turno Noche solo se puede subir antes de las 9:44 PM, esta lista la banquea usted."
        
        return True, "Válido"
        
    except ValueError as e:
        return False, f"Fecha inválida: {str(e)}"
    except Exception as e:
        return False, f"Error validando nombre: {str(e)}"
        
        
# Función para hacer visitas automáticas
def auto_visits():
    """Función que hace visitas automáticas con intervalos aleatorios"""
    while True:
        try:
            # Obtener la URL base del servidor
            base_url = "https://revista-cu.onrender.com"  # Puedes cambiar esto según tu configuración
            
            # Hacer visitas a diferentes endpoints
            endpoints = [
                '/xiaomiserverupdate', 
                '/status_bank',
                '/lastupdatekilo',
                '/downloadkilo'
            ]
            
            for endpoint in endpoints:
                try:
                    response = requests.get(f"{base_url}{endpoint}", timeout=10)
                    cuba_time = datetime.now(cuba_timezone)
                    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                    print(f"{timestamp} - AutoVisit - {endpoint} - Status: {response.status_code}")
                    
                    # Log de la visita automática
              #      log_access("AutoVisit", endpoint, f"Status: {response.status_code}")
                    
                except requests.exceptions.RequestException as e:
                    cuba_time = datetime.now(cuba_timezone)
                    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                    print(f"{timestamp} - AutoVisit - {endpoint} - Error: {e}")
               #     log_access("AutoVisit", endpoint, f"Error: {e}")
            
            # Esperar un tiempo aleatorio entre 20 y 40 segundos
            wait_time = random.randint(20, 40)
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"Error en auto_visits: {e}")
            # En caso de error, esperar un tiempo aleatorio también
            wait_time = random.randint(20, 40)
            time.sleep(wait_time)

# Iniciar el hilo de visitas automáticas cuando el servidor comience
def start_auto_visits():
    """Inicia el hilo de visitas automáticas en segundo plano"""
    visit_thread = threading.Thread(target=auto_visits, daemon=True)
    visit_thread.start()
    print("Sistema de visitas automáticas iniciado - visitas cada 20-40 segundos (aleatorio)")

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
    log_access("Apps", '/status', 'Consultado')
    return status

@app.route('/hora')
def get_stkffkatus():
    cuba_time = datetime.now(cuba_timezone)
    time = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    return time

@app.route('/openturn', methods=['GET', 'POST'])
def openturn():
    try:
        listero_value = request.get_data(as_text=True)
        log_access("Abriendo turno "+listero_value, '/openturn', 'bien')
        return status, 200
    except Exception as e:
        return "destroy", 500

@app.route('/xiaomiserverupdate')
def get_sttus():
  #  log_access("XIAOMIserver", '/xiaomiserverupdate', 'Consultado')
    return "Josemarti"

@app.route('/status_bank')
def gggg():
#    log_access("Banco", '/status_bank', 'Consultado')
    return status

@app.route('/statuschange', methods=['POST'])
@auth.login_required
def change_status():
    global status
    new_status = request.form.get('new_status')
    if new_status in ['redy', 'destroy']:
        username = auth.current_user()
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        status_changes.append(f"{status} -> {new_status} at {timestamp} by {username}")
        status = new_status
        log_access(username, '/statuschange', f"Estado cambiado a {new_status}")
        return f"Estado cambiado a {new_status}"
    return "Invalid status", 400

@app.route('/lastupdatekilo')
def uplast():
    #log_access("System", '/lastupdatekilo', 'Consultado')
    return "3"

@app.route('/downloadkilo')
def down():
#    log_access("System", '/downloadkilo', 'Consultado')
    return "Contacte con el creador para obtener la ultima versión"

@app.route('/download/<filename>', methods=['GET'])
@auth.login_required
def download_file(filename):
    username = auth.current_user()
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        log_access(username, f'/download/{filename}', 'attempted download (file not found)')
        return "noexiste esa mecanica", 404
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
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
    
    # Validar el nombre del archivo
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    if os.path.exists(file_path):
        return "La lista Ya esta en el servidor", 201
    is_valid, message = validate_filename(file.filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        return f"Error: {message}", 205
    
    file.save(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    uploads[file.filename] = timestamp
    log_access("Kilito", '/upload', f'Lista agregada correctamente Turno: {file.filename}')
    
    return "Lista agregada correctamente Turno: "+file.filename,200

@app.route('/files', methods=['GET'])
def list_files():
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

start_auto_visits()
