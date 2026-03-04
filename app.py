from flask import Flask, jsonify, request, send_from_directory
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from datetime import datetime
import re
import requests
from contextlib import contextmanager
import os
import sqlite3
import json

app = Flask(__name__)
auth = HTTPBasicAuth()

# Configuración de Telegram
TELEGRAM_BOT_TOKEN = "8075772181:AAFThdLwDvAHG0I0VN6wG78rdFVJNVinEzE"
TELEGRAM_CHAT_ID = "7587515668"

datos_actuales = {
    "dia": "",
    "noche": ""
}

# Configuration
UPLOAD_FOLDER = 'uploads'
LISTEROS_FOLDER = 'listeros_config'  # Nueva carpeta para configuraciones de listeros
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(LISTEROS_FOLDER):
    os.makedirs(LISTEROS_FOLDER)

LOG_FILE = 'access.log'
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        f.write('')

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "status": "error",
        "message": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "status": "error",
        "message": "Internal server error"
    }), 500

# Database file
DATABASE_FILE = 'lists_database.db'

# Status
status = "redy"
cuba_timezone = pytz.timezone('America/Havana')

# Users
users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "Nathan": generate_password_hash("123nathan")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None

# Database helper functions
def init_database():
    """Initialize the SQLite database"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Table for uploads
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for downloads
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for status changes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS status_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for access count
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_count INTEGER DEFAULT 0,
            today_access INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # NUEVA TABLA: Listeros registrados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS listeros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            config TEXT NOT NULL,
            ultima_sincronizacion TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Initialize access stats if not exists
    cursor.execute('SELECT COUNT(*) FROM access_stats')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO access_stats (access_count, today_access) VALUES (0, 0)')
    
    conn.commit()
    conn.close()

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def save_upload(filename, timestamp):
    """Save upload record to database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO uploads (filename, timestamp) VALUES (?, ?)',
            (filename, timestamp)
        )
        conn.commit()

def get_uploads():
    """Get all uploads from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT filename, timestamp FROM uploads ORDER BY created_at DESC')
        return {row['filename']: row['timestamp'] for row in cursor.fetchall()}

def save_download(filename, timestamp):
    """Save download record to database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO downloads (filename, timestamp) VALUES (?, ?)',
            (filename, timestamp)
        )
        conn.commit()

def get_downloads():
    """Get all downloads from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT filename, timestamp FROM downloads ORDER BY created_at DESC')
        return {row['filename']: row['timestamp'] for row in cursor.fetchall()}

def save_status_change(change_text):
    """Save status change to database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO status_changes (change_text) VALUES (?)',
            (change_text,)
        )
        conn.commit()

def get_status_changes():
    """Get all status changes from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT change_text FROM status_changes ORDER BY created_at DESC')
        return [row['change_text'] for row in cursor.fetchall()]

def increment_access_count():
    """Increment access count in database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Increment total access count
        cursor.execute('UPDATE access_stats SET access_count = access_count + 1')
        
        # Increment today's access count
        cuba_time = datetime.now(cuba_timezone)
        today = cuba_time.strftime('%Y-%m-%d')
        cursor.execute('SELECT last_updated FROM access_stats')
        row = cursor.fetchone()
        if row:
            last_updated = row['last_updated']
        
        if last_updated and last_updated.startswith(today):
            cursor.execute('UPDATE access_stats SET today_access = today_access + 1')
        else:
            cursor.execute('UPDATE access_stats SET today_access = 1')
        
        cursor.execute('UPDATE access_stats SET last_updated = ?', (cuba_time.isoformat(),))
        conn.commit()

def get_access_stats():
    """Get access statistics from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT access_count, today_access FROM access_stats')
        row = cursor.fetchone()
        return row['access_count'], row['today_access']

def get_today_access_count():
    """Get today's access count"""
    _, today_access = get_access_stats()
    return today_access

def send_telegram_message(message):
    """Envía un mensaje a Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")
        return None

def send_telegram_document(file_path, caption=""):
    """Envía un documento a Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as file:
            files = {'document': file}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
            response = requests.post(url, files=files, data=data, timeout=30)
        return response.json()
    except Exception as e:
        print(f"Error enviando documento a Telegram: {e}")
        return None

def log_access(username, endpoint, action):
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    # Incrementar contador en base de datos
    increment_access_count()
    
    # Enviar notificación a Telegram para acciones importantes
    if "Error" in action or "attempted" in action or "Lista agregada" in action:
        telegram_message = f"🔔 <b>Notificación del Servidor</b>\n\n"
        telegram_message += f"<b>Usuario:</b> {username}\n"
        telegram_message += f"<b>Endpoint:</b> {endpoint}\n"
        telegram_message += f"<b>Acción:</b> {action}\n"
        telegram_message += f"<b>Hora:</b> {timestamp}"
        send_telegram_message(telegram_message)

def validate_filename(filename):
    """
    Valida que el nombre del archivo siga el formato: [prefijo]-YYYY-MM-DD-Turno
    y que cumpla con los horarios establecidos para cada turno.
    """
    # Verificar el patrón del nombre
    filename = filename.replace(" ", "")
    pattern = r'^[a-zA-Z0-9]+-\d{4}-\d{1,2}-\d{1,2}-(Dia|Noche|DIA|NOCHE|dia|noche)$'
    if not re.match(pattern, filename):
        return False, f"Formato de nombre inválido. Debe ser: [apodo]-YYYY-MM-DD-Turno. Recibido: {filename}"
    
    # Extraer componentes
    try:
        parts = filename.split('-')
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        turno = parts[4].capitalize()
        
        # Verificar que la fecha sea válida
        file_date = datetime(year, month, day)
        
        # Obtener fecha y hora actual en Cuba
        cuba_now = datetime.now(cuba_timezone)
        current_date = cuba_now.date()
        current_time = cuba_now.time()
        
        # Verificar que la fecha del archivo sea hoy
        if file_date.date() != current_date:
            return False, f"Solo se pueden subir listas del día actual. Fecha del archivo: {file_date.date()}, Hoy: {current_date}"
        
        # Verificar horarios según el turno
        if turno == "Dia":
            limite_dia = datetime.strptime("13:30", "%H:%M").time()
            if current_time > limite_dia:
                return False, f"El turno Dia solo se puede subir antes de las 1:30 PM (hora actual: {current_time.strftime('%I:%M %p')})"
        
        elif turno == "Noche":
            limite_noche = datetime.strptime("21:44", "%H:%M").time()
            if current_time > limite_noche:
                return False, f"El turno Noche solo se puede subir antes de las 9:44 PM (hora actual: {current_time.strftime('%I:%M %p')})"
        
        return True, "Válido"
        
    except ValueError as e:
        return False, f"Fecha inválida: {str(e)}"
    except Exception as e:
        return False, f"Error validando nombre: {str(e)}"

# ============= NUEVAS FUNCIONES PARA LISTEROS =============

def save_listero_to_db(nombre, config_data, timestamp):
    """Guardar configuración de listero en la base de datos"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Convertir config_data a JSON string
        config_json = json.dumps(config_data, ensure_ascii=False)
        
        cursor.execute('''
            INSERT OR REPLACE INTO listeros (nombre, config, ultima_sincronizacion)
            VALUES (?, ?, ?)
        ''', (nombre, config_json, timestamp))
        conn.commit()

def get_all_listeros_from_db():
    """Obtener todos los listeros de la base de datos"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT nombre, config, ultima_sincronizacion FROM listeros ORDER BY nombre')
        rows = cursor.fetchall()
        
        listeros = []
        for row in rows:
            listeros.append({
                'nombre': row['nombre'],
                'ultima_sincronizacion': row['ultima_sincronizacion'],
                'config': json.loads(row['config'])
            })
        return listeros

def get_listero_from_db(nombre):
    """Obtener un listero específico de la base de datos"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT nombre, config, ultima_sincronizacion FROM listeros WHERE nombre = ?', (nombre,))
        row = cursor.fetchone()
        
        if row:
            return {
                'nombre': row['nombre'],
                'ultima_sincronizacion': row['ultima_sincronizacion'],
                'config': json.loads(row['config'])
            }
        return None

# ============= NUEVOS ENDPOINTS PARA LISTEROS =============

@app.route('/api/sync-listero', methods=['POST'])
def sync_listero():
    """
    Endpoint para recibir configuración de listeros desde la app
    """
    username = request.remote_addr  # Usar IP como identificador
    
    try:
        data = request.get_json()
        
        if not data or 'nombre' not in data:
            log_access(username, '/api/sync-listero', 'Error: Datos incompletos')
            return jsonify({'error': 'Datos incompletos'}), 400
        
        nombre_listero = data['nombre']
        
        # Crear timestamp
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Guardar en base de datos
        save_listero_to_db(nombre_listero, data, timestamp)
        
        # También guardar archivo individual para compatibilidad
        archivo_listero = os.path.join(LISTEROS_FOLDER, f"{nombre_listero}.json")
        with open(archivo_listero, 'w', encoding='utf-8') as f:
            json.dump({
                'nombre': nombre_listero,
                'timestamp': timestamp,
                'data': data
            }, f, indent=2, ensure_ascii=False)
        
        log_access(username, '/api/sync-listero', f'Listero sincronizado: {nombre_listero}')
        
        return jsonify({
            'success': True,
            'message': f'Listero {nombre_listero} sincronizado correctamente',
            'timestamp': timestamp
        })
        
    except Exception as e:
        log_access(username, '/api/sync-listero', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listeros-completos', methods=['GET'])
def get_listeros_completos():
    """
    Endpoint para obtener lista de todos los listeros sincronizados
    """
    username = request.remote_addr
    
    try:
        listeros = get_all_listeros_from_db()
        
        log_access(username, '/api/listeros-completos', f'Listando {len(listeros)} listeros')
        
        return jsonify({
            'success': True,
            'listeros': listeros
        })
        
    except Exception as e:
        log_access(username, '/api/listeros-completos', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listero/<nombre>', methods=['GET'])
def get_listero_config(nombre):
    """
    Endpoint para obtener configuración de un listero específico
    """
    username = request.remote_addr
    
    try:
        # Buscar en base de datos
        listero = get_listero_from_db(nombre)
        
        if listero:
            log_access(username, f'/api/listero/{nombre}', 'Configuración encontrada')
            return jsonify(listero)
        
        # Si no está en BD, buscar en archivo individual
        archivo = os.path.join(LISTEROS_FOLDER, f"{nombre}.json")
        if os.path.exists(archivo):
            with open(archivo, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log_access(username, f'/api/listero/{nombre}', 'Configuración encontrada en archivo')
            return jsonify(data)
        
        log_access(username, f'/api/listero/{nombre}', 'Listero no encontrado')
        return jsonify({'error': 'Listero no encontrado'}), 404
            
    except Exception as e:
        log_access(username, f'/api/listero/{nombre}', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listeros/estadisticas', methods=['GET'])
def get_listeros_stats():
    """
    Endpoint para obtener estadísticas de listeros
    """
    username = request.remote_addr
    
    try:
        listeros = get_all_listeros_from_db()
        
        # Calcular estadísticas
        total = len(listeros)
        
        # Listeros sincronizados hoy
        cuba_time = datetime.now(cuba_timezone)
        hoy = cuba_time.strftime('%Y-%m-%d')
        sincronizados_hoy = 0
        
        for l in listeros:
            if hoy in l['ultima_sincronizacion']:
                sincronizados_hoy += 1
        
        log_access(username, '/api/listeros/estadisticas', f'Estadísticas calculadas')
        
        return jsonify({
            'success': True,
            'estadisticas': {
                'total_listeros': total,
                'sincronizados_hoy': sincronizados_hoy,
                'ultima_actualizacion': cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
            }
        })
        
    except Exception as e:
        log_access(username, '/api/listeros/estadisticas', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============= ENDPOINTS EXISTENTES =============

@app.route('/')
def index():
    return jsonify({
        "servidor": "Activo",
        "status": status,
        "endpoints": [
            "/status - Estado del servidor",
            "/hora - Hora actual en Cuba",
            "/openturn - Abrir turno",
            "/statuschange - Cambiar estado (POST) [Auth]",
            "/files - Listar archivos",
            "/download/<filename> - Descargar archivo",
            "/upload - Subir archivo (POST)",
            "/delete/<filename> - Eliminar archivo (DELETE) [Auth]",
            "/db_stats - Estadísticas de base de datos",
            # Nuevos endpoints para listeros
            "/api/sync-listero - Sincronizar listero (POST)",
            "/api/listeros-completos - Listar listeros",
            "/api/listero/<nombre> - Obtener listero",
            "/api/listeros/estadisticas - Estadísticas de listeros"
        ]
    })

@app.route('/datos', methods=['GET'])
def obtener_datos():
    """Endpoint para obtener los datos actuales"""
    username = request.remote_addr
    log_access(username, '/datos', 'Datos consultados')
    return jsonify(datos_actuales)

@app.route('/actualizar', methods=['POST'])
def actualizar_datos():
    """Endpoint para actualizar los datos"""
    global datos_actuales
    username = request.remote_addr
    
    try:
        data = request.get_json()
        
        if not data:
            log_access(username, '/actualizar', 'Error: No se recibieron datos')
            return jsonify({"error": "No se recibieron datos"}), 400
        
        # Actualizar datos si vienen en la petición
        cambios = []
        if 'dia' in data and data['dia'] != datos_actuales['dia']:
            datos_actuales['dia'] = data['dia']
            cambios.append(f"dia: {data['dia']}")
        if 'noche' in data and data['noche'] != datos_actuales['noche']:
            datos_actuales['noche'] = data['noche']
            cambios.append(f"noche: {data['noche']}")
        
        if cambios:
            log_access(username, '/actualizar', f'Datos actualizados: {", ".join(cambios)}')
        else:
            log_access(username, '/actualizar', 'Solicitud sin cambios')
        
        return jsonify({
            "mensaje": "Datos actualizados correctamente",
            "datos": datos_actuales
        }), 200
        
    except Exception as e:
        log_access(username, '/actualizar', f'Error: {str(e)}')
        return jsonify({"error": str(e)}), 500

@app.route('/sincronizar', methods=['POST'])
def sincronizar():
    """Endpoint para sincronizar datos bidireccionalmente"""
    username = request.remote_addr
    
    try:
        data = request.get_json()
        
        cambios = []
        # Actualizar con datos recibidos
        if data:
            if 'dia' in data and data['dia'] != datos_actuales['dia']:
                datos_actuales['dia'] = data['dia']
                cambios.append(f"dia: {data['dia']}")
            if 'noche' in data and data['noche'] != datos_actuales['noche']:
                datos_actuales['noche'] = data['noche']
                cambios.append(f"noche: {data['noche']}")
        
        if cambios:
            log_access(username, '/sincronizar', f'Sincronización: {", ".join(cambios)}')
        else:
            log_access(username, '/sincronizar', 'Sincronización sin cambios')
        
        # Devolver datos actualizados
        return jsonify({
            "mensaje": "Sincronización completada",
            "datos": datos_actuales
        }), 200
        
    except Exception as e:
        log_access(username, '/sincronizar', f'Error: {str(e)}')
        return jsonify({"error": str(e)}), 500

@app.route('/status')
def get_status():
    log_access("Apps", '/status', 'Consultado')
    return status

@app.route('/hora')
def get_time():
    username = request.remote_addr
    cuba_time = datetime.now(cuba_timezone)
    hora_str = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_access(username, '/hora', f'Hora consultada: {hora_str}')
    return hora_str

@app.route('/openturn', methods=['GET', 'POST'])
def openturn():
    try:
        listero_value = request.get_data(as_text=True)
        username = request.remote_addr
        log_access(username, '/openturn', f'Abrir turno - {listero_value}')
        return status, 200
    except Exception as e:
        username = request.remote_addr
        log_access(username, '/openturn', f'Error: {str(e)}')
        return "destroy", 500

@app.route('/xiaomiserverupdate')
def get_status_alias():
    username = request.remote_addr
    log_access(username, '/xiaomiserverupdate', 'Alias consultado')
    return "Josemarti"

@app.route('/status_bank')
def get_status_bank():
    username = request.remote_addr
    log_access(username, '/status_bank', 'Status bank consultado')
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
        old_status = status
        change_text = f"{old_status} -> {new_status} at {timestamp} by {username}"
        
        # Guardar en base de datos
        save_status_change(change_text)
        
        status = new_status
        log_access(username, '/statuschange', f"Estado cambiado de {old_status} a {new_status}")
        
        # Mensaje especial a Telegram
        telegram_msg = f"🔄 <b>Cambio de Estado</b>\n\n"
        telegram_msg += f"<b>Usuario:</b> {username}\n"
        telegram_msg += f"<b>Cambio:</b> {old_status} → {new_status}\n"
        telegram_msg += f"<b>Hora:</b> {timestamp}"
        send_telegram_message(telegram_msg)
        
        return f"Estado cambiado a {new_status}"
    return "Invalid status", 400

@app.route('/lastupdatekilo')
def get_version():
    try:
        url_contenido = "https://raw.githubusercontent.com/user7503tanke/info/refs/heads/main/REA"
        respuesta = requests.get(url_contenido)
        
        # Asegurarse de que la petición fue exitosa
        if respuesta.status_code == 200:
            contenido = respuesta.text.strip()
            return f"vdataantiloquera{contenido}"
        else:
            return f"Error al obtener el contenido: {respuesta.status_code}", 500
    except Exception as e:
        return f"Error en la conexión: {str(e)}", 400

@app.route('/downloadkilo')
def download_info():
    return "Contacte con el creador para obtener la ultima versión"

@app.route('/update')
def update_page():
    return "Para obtener la última versión, contacte al administrador."

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    username = request.remote_addr
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        log_access(username, f'/download/{filename}', 'attempted download (file not found)')
        return "Archivo no encontrado", 404
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Guardar en base de datos
    save_download(filename, timestamp)
    
    log_access(username, f'/download/{filename}', f'Descargando lista: {filename}')
    
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.remote_addr
    if 'archivo' not in request.files:
        log_access(username, '/upload', 'attempted upload (no file part)')
        send_telegram_message(f"⚠️ <b>Intento de subida fallido</b>\n\nUsuario: {username}\nError: No se envió el archivo")
        return "Error: El campo debe llamarse 'archivo'", 400
    
    file = request.files['archivo']
    if file.filename == '':
        log_access(username, '/upload', 'attempted upload (empty filename)')
        send_telegram_message(f"⚠️ <b>Intento de subida fallido</b>\n\nUsuario: {username}\nError: Nombre de archivo vacío")
        return "Error: Nombre de archivo vacío", 400
    
    # Validar el nombre del archivo
    filename = file.filename
    filename = filename.replace("controlantimermaxd", "")
    is_valid, message = validate_filename(filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        # Enviar notificación de error a Telegram
        error_msg = f"❌ <b>Error en subida de lista</b>\n\n"
        error_msg += f"<b>Usuario:</b> {username}\n"
        error_msg += f"<b>Archivo:</b> {filename}\n"
        error_msg += f"<b>Error:</b> {message}"
        send_telegram_message(error_msg)
        return f"Error: {message}", 205
    
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    # Si existe, eliminarlo (sobrescribir)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    file.save(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Guardar en base de datos
    save_upload(filename, timestamp)
    
    log_access(username, '/upload', f'Lista agregada correctamente: {filename}')
    
    # Enviar el archivo a Telegram
    try:
        # Extraer información del nombre
        parts = filename.split('-')
        apodo = parts[0]
        turno = parts[4].capitalize()
        
        caption = f"📋 <b>Nueva Lista Subida</b>\n\n"
        caption += f"<b>Archivo:</b> {filename}\n"
        caption += f"<b>Listero:</b> {apodo}\n"
        caption += f"<b>Turno:</b> {turno}\n"
        caption += f"<b>Usuario:</b> {username}\n"
        caption += f"<b>Hora:</b> {timestamp}"
        
        send_telegram_document(file_path, caption)
    except Exception as e:
        print(f"Error enviando archivo a Telegram: {e}")
        # Si falla el envío del archivo, al menos enviar mensaje
        send_telegram_message(f"✅ <b>Lista subida correctamente</b>\n\nArchivo: {filename}\nHora: {timestamp}\n(No se pudo enviar el archivo adjunto)")
    
    return f"Lista agregada correctamente: {filename}", 200


@app.route('/files', methods=['GET'])
def list_files():
    log_access("Banco", '/files', 'Listando archivos')
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
    
    # Obtener información antes de eliminar
    file_size = os.path.getsize(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    os.remove(file_path)
    
    log_access(username, f'/delete/{filename}', 'Lista eliminada')
    
    # Notificar a Telegram
    telegram_msg = f"🗑️ <b>Lista Eliminada</b>\n\n"
    telegram_msg += f"<b>Archivo:</b> {filename}\n"
    telegram_msg += f"<b>Tamaño:</b> {file_size} bytes\n"
    telegram_msg += f"<b>Eliminado por:</b> {username}\n"
    telegram_msg += f"<b>Hora:</b> {timestamp}"
    send_telegram_message(telegram_msg)
    
    return "Lista eliminada correctamente"

@app.route('/db_stats', methods=['GET'])
def get_db_stats():
    """Endpoint para ver estadísticas de la base de datos"""
    username = request.remote_addr
    uploads_count = len(get_uploads())
    downloads_count = len(get_downloads())
    status_changes_count = len(get_status_changes())
    access_count, today_access = get_access_stats()
    
    # Estadísticas de listeros
    listeros_count = len(get_all_listeros_from_db())
    
    log_access(username, '/db_stats', 'Estadísticas consultadas')
    
    return jsonify({
        "uploads_count": uploads_count,
        "downloads_count": downloads_count,
        "status_changes_count": status_changes_count,
        "access_count": access_count,
        "today_access": today_access,
        "listeros_count": listeros_count
    })

# Inicializar servicios al arrancar
def initialize_services():
    """Inicializa todos los servicios al arrancar la aplicación"""
    # Inicializar base de datos
    init_database()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    print(f"{timestamp} - Servidor iniciado. Estado: {status}")
    print(f"{timestamp} - Directorio uploads: {UPLOAD_FOLDER}")
    print(f"{timestamp} - Directorio listeros: {LISTEROS_FOLDER}")
    print(f"{timestamp} - Base de datos: {DATABASE_FILE}")
    
    # Enviar notificación de inicio a Telegram
    start_msg = f"🚀 <b>Servidor Iniciado</b>\n\n"
    start_msg += f"<b>Estado:</b> {status}\n"
    start_msg += f"<b>Hora:</b> {timestamp}\n"
    start_msg += f"<b>Uploads:</b> {UPLOAD_FOLDER}\n"
    start_msg += f"<b>Base de datos:</b> {DATABASE_FILE}"
    send_telegram_message(start_msg)

# Inicializar servicios cuando se importa el módulo
initialize_services()
