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
import subprocess
import sys

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

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = "8075772181:AAFThdLwDvAHG0I0VN6wG78rdFVJNVinEzE"  # Reemplaza con tu token del bot
TELEGRAM_CHAT_ID = "7587515668"      # Reemplaza con tu chat ID

#######FIIIIIINAAAAALLLL###################
# Users
users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "Carlos": generate_password_hash("carlos334087"),
    "Nathan": generate_password_hash("123nathan")
}

# Helper functions
def send_telegram_message(message):
    """Envía un mensaje a través del bot de Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")
        return False

def log_access(username, endpoint, action):
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    global access_count
    access_count += 1
    
    # Enviar notificación a Telegram para acciones importantes
    if endpoint in ['/upload', '/download/', '/statuschange', '/delete/']:
        telegram_message = f"🔔 <b>Nueva acción detectada</b>\n\n👤 Usuario: {username}\n🌐 Endpoint: {endpoint}\n📝 Acción: {action}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)

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
    filename = filename.replace(" ","")
    pattern = r'^[a-zA-Z]+-\d{4}-\d{1,2}-\d{1,2}-(Dia|Noche|DIA|NOCHE|dia|noche)$'
    if not re.match(pattern, filename):
        return False, "Formato de nombre inválido. Debe ser: [apodo]-YYYY-MM-DD-Turno el tuyo es"+filename
    
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

# Script separado para visitas automáticas
def create_auto_visitor_script():
    """Crea un script separado para las visitas automáticas"""
    script_content = '''
import requests
import time
import random
from datetime import datetime
import pytz

cuba_timezone = pytz.timezone('America/Havana')

def auto_visits():
    """Función que hace visitas automáticas con intervalos aleatorios"""
    while True:
        try:
            # Obtener la URL base del servidor
            base_url = "https://revista-cu.onrender.com"
            
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
                    wait_time = random.randint(60, 120)
                    time.sleep(wait_time)
                    
                except requests.exceptions.RequestException as e:
                    cuba_time = datetime.now(cuba_timezone)
                    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                    print(f"{timestamp} - AutoVisit - {endpoint} - Error: {e}")
            
            # Esperar un tiempo aleatorio entre 120 y 60 segundos
            wait_time = random.randint(60, 120)
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"Error en auto_visits: {e}")
            wait_time = random.randint(20, 40)
            time.sleep(wait_time)

if __name__ == "__main__":
    print("Iniciando sistema de visitas automáticas...")
    auto_visits()
'''
    
    with open('auto_visitor.py', 'w') as f:
        f.write(script_content)

def start_auto_visits():
    """Inicia el proceso de visitas automáticas usando subprocess"""
    try:
        # Crear el script primero
        create_auto_visitor_script()
        
        # Iniciar el proceso
        process = subprocess.Popen([sys.executable, 'auto_visitor.py'])
        
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        print(f"{timestamp} - Proceso de visitas automáticas iniciado (PID: {process.pid})")
        
        return process
    except Exception as e:
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        print(f"{timestamp} - Error iniciando visitas automáticas: {e}")
        return None

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
        
        # Notificación especial para apertura de turno
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        telegram_message = f"🔄 <b>Turno Abierto</b>\n\n📋 Lista: {listero_value}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)
        
        return status, 200
    except Exception as e:
        return "destroy", 500

@app.route('/xiaomiserverupdate')
def get_sttus():
    return "Josemarti"

@app.route('/status_bank')
def gggg():
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
        
        # Notificación de cambio de estado
        status_emoji = "✅" if new_status == 'redy' else "❌"
        telegram_message = f"{status_emoji} <b>Cambio de Estado del Sistema</b>\n\n👤 Usuario: {username}\n🔄 Estado anterior: {status}\n🆕 Estado nuevo: {new_status}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)
        
        status = new_status
        log_access(username, '/statuschange', f"Estado cambiado a {new_status}")
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
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    downloads[filename] = timestamp
    
    # Notificación de descarga
    telegram_message = f"📥 <b>Lista Descargada</b>\n\n👤 Usuario: {username}\n📄 Archivo: {filename}\n🕐 Hora: {timestamp}"
    send_telegram_message(telegram_message)
    
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
    
    # Notificación de subida exitosa
    telegram_message = f"📤 <b>Lista Subida Exitosamente</b>\n\n👤 Usuario: {username}\n📄 Archivo: {file.filename}\n🕐 Hora: {timestamp}"
    send_telegram_message(telegram_message)
    
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
    
    # Notificación de eliminación
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    telegram_message = f"🗑️ <b>Lista Eliminada</b>\n\n👤 Usuario: {username}\n📄 Archivo: {filename}\n🕐 Hora: {timestamp}"
    send_telegram_message(telegram_message)
    
    log_access("Banco", f'/delete/{filename}', 'borrando lista')
    return "Lista eliminada correctamente"

# Enviar mensaje de inicio del servidor
def send_startup_message():
    """Envía un mensaje cuando el servidor se inicia"""
    time.sleep(5)  # Esperar a que el servidor esté completamente listo
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    startup_message = f"🚀 <b>Servidor Iniciado</b>\n\n🕐 Hora de inicio: {timestamp}\n📍 Timezone: America/Havana\n✅ Estado: Listo para recibir conexiones"
    send_telegram_message(startup_message)

# Variable global para mantener referencia al proceso
auto_visitor_process = None

# Iniciar servicios al arrancar
def initialize_services():
    """Inicializa todos los servicios al arrancar la aplicación"""
    # Mensaje de inicio
    startup_thread = threading.Thread(target=send_startup_message, daemon=True)
    startup_thread.start()
    
    # Visitas automáticas
    global auto_visitor_process
    auto_visitor_process = start_auto_visits()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    print(f"{timestamp} - Todos los servicios inicializados")

# Inicializar servicios cuando se importa el módulo
initialize_services()

