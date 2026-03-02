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

def log_access(username, endpoint, action):
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    # Incrementar contador en base de datos
    increment_access_count()

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
                return False, "El turno Dia solo se puede subir antes de las 1:30 PM"
        
        elif turno == "Noche":
            limite_noche = datetime.strptime("21:44", "%H:%M").time()
            if current_time > limite_noche:
                return False, "El turno Noche solo se puede subir antes de las 9:44 PM"
        
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
@auth.login_required
def sync_listero():
    """
    Endpoint para recibir configuración de listeros desde la app
    """
    username = auth.current_user()
    
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
@auth.login_required
def get_listeros_completos():
    """
    Endpoint para obtener lista de todos los listeros sincronizados
    """
    username = auth.current_user()
    
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
@auth.login_required
def get_listero_config(nombre):
    """
    Endpoint para obtener configuración de un listero específico
    """
    username = auth.current_user()
    
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
@auth.login_required
def get_listeros_stats():
    """
    Endpoint para obtener estadísticas de listeros
    """
    username = auth.current_user()
    
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
            "/download/<filename> - Descargar archivo [Auth]",
            "/upload - Subir archivo (POST) [Auth]",
            "/delete/<filename> - Eliminar archivo (DELETE) [Auth]",
            "/db_stats - Estadísticas de base de datos [Auth]",
            # Nuevos endpoints para listeros
            "/api/sync-listero - Sincronizar listero (POST) [Auth]",
            "/api/listeros-completos - Listar listeros [Auth]",
            "/api/listero/<nombre> - Obtener listero [Auth]",
            "/api/listeros/estadisticas - Estadísticas de listeros [Auth]"
        ]
    })

@app.route('/datos', methods=['GET'])
def obtener_datos():
    """Endpoint para obtener los datos actuales"""
    return jsonify(datos_actuales)

@app.route('/actualizar', methods=['POST'])
def actualizar_datos():
    """Endpoint para actualizar los datos"""
    global datos_actuales
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No se recibieron datos"}), 400
        
        # Actualizar datos si vienen en la petición
        if 'dia' in data:
            datos_actuales['dia'] = data['dia']
        if 'noche' in data:
            datos_actuales['noche'] = data['noche']
        
        return jsonify({
            "mensaje": "Datos actualizados correctamente",
            "datos": datos_actuales
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sincronizar', methods=['POST'])
def sincronizar():
    """Endpoint para sincronizar datos bidireccionalmente"""
    try:
        data = request.get_json()
        
        # Actualizar con datos recibidos
        if data:
            if 'dia' in data:
                datos_actuales['dia'] = data['dia']
            if 'noche' in data:
                datos_actuales['noche'] = data['noche']
        
        # Devolver datos actualizados
        return jsonify({
            "mensaje": "Sincronización completada",
            "datos": datos_actuales
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/status')
def get_status():
    log_access("Apps", '/status', 'Consultado')
    return status

@app.route('/hora')
def get_time():
    cuba_time = datetime.now(cuba_timezone)
    return cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')

@app.route('/openturn', methods=['GET', 'POST'])
def openturn():
    try:
        listero_value = request.get_data(as_text=True)
        log_access("Abriendo turno", '/openturn', f'bien - {listero_value}')
        return status, 200
    except Exception as e:
        return "destroy", 500

@app.route('/xiaomiserverupdate')
def get_status_alias():
    return "Josemarti"

@app.route('/status_bank')
def get_status_bank():
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
        change_text = f"{status} -> {new_status} at {timestamp} by {username}"
        
        # Guardar en base de datos
        save_status_change(change_text)
        
        status = new_status
        log_access(username, '/statuschange', f"Estado cambiado a {new_status}")
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
@auth.login_required
def download_file(filename):
    username = auth.current_user()
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
@auth.login_required
def upload_file():
    username = auth.current_user()
    if 'archivo' not in request.files:
        log_access(username, '/upload', 'attempted upload (no file part)')
        return "Error: El campo debe llamarse 'archivo'", 400
    
    file = request.files['archivo']
    if file.filename == '':
        log_access(username, '/upload', 'attempted upload (empty filename)')
        return "Error: Nombre de archivo vacío", 400
    
    # Validar el nombre del archivo
    filename = file.filename
    filename = filename.replace("controlantimermaxd", "")
    is_valid, message = validate_filename(filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
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
    
    os.remove(file_path)
    
    log_access(username, f'/delete/{filename}', 'Lista eliminada')
    return "Lista eliminada correctamente"

@app.route('/db_stats', methods=['GET'])
@auth.login_required
def get_db_stats():
    """Endpoint para ver estadísticas de la base de datos"""
    username = auth.current_user()
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

# Inicializar servicios cuando se importa el módulo
initialize_services()

