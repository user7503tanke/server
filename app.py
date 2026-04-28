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
LISTEROS_FOLDER = 'listeros_config'
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
    "newyork": generate_password_hash("newyork4507")
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS status_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_count INTEGER DEFAULT 0,
            today_access INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS listeros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            config TEXT NOT NULL,
            ultima_sincronizacion TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('SELECT COUNT(*) FROM access_stats')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO access_stats (access_count, today_access) VALUES (0, 0)')
    
    conn.commit()
    conn.close()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def save_upload(filename, timestamp):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO uploads (filename, timestamp) VALUES (?, ?)',
            (filename, timestamp)
        )
        conn.commit()

def get_uploads():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT filename, timestamp FROM uploads ORDER BY created_at DESC')
        return {row['filename']: row['timestamp'] for row in cursor.fetchall()}

def save_download(filename, timestamp):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO downloads (filename, timestamp) VALUES (?, ?)',
            (filename, timestamp)
        )
        conn.commit()

def get_downloads():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT filename, timestamp FROM downloads ORDER BY created_at DESC')
        return {row['filename']: row['timestamp'] for row in cursor.fetchall()}

def save_status_change(change_text):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO status_changes (change_text) VALUES (?)',
            (change_text,)
        )
        conn.commit()

def get_status_changes():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT change_text FROM status_changes ORDER BY created_at DESC')
        return [row['change_text'] for row in cursor.fetchall()]

def increment_access_count():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE access_stats SET access_count = access_count + 1')
        
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
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT access_count, today_access FROM access_stats')
        row = cursor.fetchone()
        return row['access_count'], row['today_access']

def send_telegram_message(message):
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
    
    increment_access_count()
    
    if "Error" in action or "attempted" in action or "Lista agregada" in action:
        telegram_message = f"🔔 <b>Notificación del Servidor</b>\n\n"
        telegram_message += f"<b>Usuario:</b> {username}\n"
        telegram_message += f"<b>Endpoint:</b> {endpoint}\n"
        telegram_message += f"<b>Acción:</b> {action}\n"
        telegram_message += f"<b>Hora:</b> {timestamp}"
        send_telegram_message(telegram_message)

def validate_filename(filename):
    filename = filename.replace(" ", "")
    # Patrón actualizado para permitir prefijos opcionales Florida- o Georgia-
    pattern = r'^(?:Florida-|Georgia-)?[a-zA-Z0-9]+-\d{4}-\d{1,2}-\d{1,2}-(Dia|Noche|DIA|NOCHE|dia|noche)$'
    if not re.match(pattern, filename):
        return False, f"Formato de nombre inválido. Debe ser: [Florida-|Georgia-][apodo]-YYYY-MM-DD-Turno. Recibido: {filename}"
    
    try:
        # Detectar el prefijo (Florida o Georgia)
        prefix = None
        base_filename = filename
        if filename.startswith('Florida-'):
            prefix = 'Florida'
            prefix_end = len('Florida-')
            base_filename = filename[prefix_end:]
        elif filename.startswith('Georgia-'):
            prefix = 'Georgia'
            prefix_end = len('Georgia-')
            base_filename = filename[prefix_end:]
        
        parts = base_filename.split('-')
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        turno = parts[4].capitalize()
        
        file_date = datetime(year, month, day)
        cuba_now = datetime.now(cuba_timezone)
        current_date = cuba_now.date()
        current_time = cuba_now.time()
        
        if file_date.date() != current_date:
            return False, f"Solo se pueden subir listas del día actual. Fecha del archivo: {file_date.date()}, Hoy: {current_date}"
        
        # Validar horarios según el prefijo
        if prefix == 'Florida':
            if turno == "Dia":
                limite_dia = datetime.strptime("13:30", "%H:%M").time()  # 1:30 PM
                if current_time > limite_dia:
                    return False, f"El turno Dia para Florida solo se puede subir antes de la 1:30 PM (hora actual: {current_time.strftime('%I:%M %p')})"
            elif turno == "Noche":
                limite_noche = datetime.strptime("21:40", "%H:%M").time()  # 9:40 PM
                if current_time > limite_noche:
                    return False, f"El turno Noche para Florida solo se puede subir antes de las 9:40 PM (hora actual: {current_time.strftime('%I:%M %p')})"
        
        elif prefix == 'Georgia':
            if turno == "Dia":
                limite_dia = datetime.strptime("12:25", "%H:%M").time()  # 12:25 PM
                if current_time > limite_dia:
                    return False, f"El turno Dia para Georgia solo se puede subir antes de las 12:25 PM (hora actual: {current_time.strftime('%I:%M %p')})"
            elif turno == "Noche":
                limite_noche = datetime.strptime("18:55", "%H:%M").time()  # 6:55 PM
                if current_time > limite_noche:
                    return False, f"El turno Noche para Georgia solo se puede subir antes de las 6:55 PM (hora actual: {current_time.strftime('%I:%M %p')})"
        
        else:
            # Sin prefijo (comportamiento por defecto, ej: Florida)
            if turno == "Dia":
                limite_dia = datetime.strptime("13:30", "%H:%M").time()
                if current_time > limite_dia:
                    return False, f"El turno Dia solo se puede subir antes de las 1:30 PM (hora actual: {current_time.strftime('%I:%M %p')})"
            elif turno == "Noche":
                limite_noche = datetime.strptime("21:40", "%H:%M").time()
                if current_time > limite_noche:
                    return False, f"El turno Noche solo se puede subir antes de las 9:40 PM (hora actual: {current_time.strftime('%I:%M %p')})"
        
        return True, "Válido"
    except ValueError as e:
        return False, f"Fecha inválida: {str(e)}"
    except Exception as e:
        return False, f"Error validando nombre: {str(e)}"
        # ============= FUNCIONES PARA LISTEROS =============
def save_listero_to_db(nombre, config_data, timestamp):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config_json = json.dumps(config_data, ensure_ascii=False)
        cursor.execute('''
            INSERT OR REPLACE INTO listeros (nombre, config, ultima_sincronizacion)
            VALUES (?, ?, ?)
        ''', (nombre, config_json, timestamp))
        conn.commit()

def get_all_listeros_from_db():
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

# ============= CONFIGURACIÓN PARA TIRADAS =============
TIRADAS_FILE = 'tiradas.json'

def load_tiradas():
    if os.path.exists(TIRADAS_FILE):
        try:
            with open(TIRADAS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_tiradas(tiradas):
    with open(TIRADAS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tiradas, f, indent=2, ensure_ascii=False)

# ============= FUNCIONES PARA TURNOS_STATUS Y CONFIG =============
TURNOS_STATUS_FILE = 'turnos_status_server.json'
CONFIG_FILE = 'config_server.json'

def load_turnos_status():
    if os.path.exists(TURNOS_STATUS_FILE):
        try:
            with open(TURNOS_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_turnos_status(data):
    with open(TURNOS_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ============= ENDPOINTS PARA TIRADAS (individuales) =============
@app.route('/api/tirada/<turno>', methods=['GET'])
def get_tirada(turno):
    username = request.remote_addr
    tiradas = load_tiradas()
    if turno in tiradas:
        log_access(username, f'/api/tirada/{turno}', 'Tirada obtenida')
        return jsonify({'turno': turno, 'tirada': tiradas[turno]})
    else:
        log_access(username, f'/api/tirada/{turno}', 'Tirada no encontrada')
        return jsonify({'turno': turno, 'tirada': '0-00-00-00'})

@app.route('/api/tirada/<turno>', methods=['POST'])
def set_tirada(turno):
    username = request.remote_addr
    try:
        data = request.get_json()
        if not data or 'tirada' not in data:
            log_access(username, f'/api/tirada/{turno}', 'Error: Datos incompletos')
            return jsonify({'error': 'Formato de datos incorrecto'}), 400
        tirada = data['tirada']
        tiradas = load_tiradas()
        tiradas[turno] = tirada
        save_tiradas(tiradas)
        log_access(username, f'/api/tirada/{turno}', f'Tirada guardada: {tirada}')
        return jsonify({'mensaje': 'Tirada guardada correctamente', 'turno': turno, 'tirada': tirada}), 200
    except Exception as e:
        log_access(username, f'/api/tirada/{turno}', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============= NUEVOS ENDPOINTS PARA SINCRONIZACIÓN COMPLETA =============
@app.route('/api/turnos-status', methods=['GET'])
@auth.login_required
def get_all_turnos_status():
    username = auth.current_user()
    try:
        data = load_turnos_status()
        log_access(username, '/api/turnos-status', 'Enviando turnos_status')
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/turnos-status', methods=['POST'])
@auth.login_required
def set_all_turnos_status():
    username = auth.current_user()
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'No data'}), 400
        save_turnos_status(data)
        log_access(username, '/api/turnos-status', 'Turnos_status actualizado')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tiradas/all', methods=['GET'])
@auth.login_required
def get_all_tiradas():
    username = auth.current_user()
    try:
        tiradas = load_tiradas()
        log_access(username, '/api/tiradas/all', 'Enviando todas las tiradas')
        return jsonify(tiradas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tiradas/all', methods=['POST'])
@auth.login_required
def set_all_tiradas():
    username = auth.current_user()
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'No data'}), 400
        save_tiradas(data)
        log_access(username, '/api/tiradas/all', 'Tiradas actualizadas')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET'])
@auth.login_required
def get_config():
    username = auth.current_user()
    try:
        config = load_config()
        log_access(username, '/api/config', 'Configuración enviada')
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
@auth.login_required
def set_config():
    username = auth.current_user()
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'No data'}), 400
        save_config(data)
        log_access(username, '/api/config', 'Configuración actualizada')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= ENDPOINTS EXISTENTES PARA LISTEROS =============
@app.route('/api/sync-listero', methods=['POST'])
def sync_listero():
    username = request.remote_addr
    try:
        data = request.get_json()
        if not data or 'nombre' not in data:
            log_access(username, '/api/sync-listero', 'Error: Datos incompletos')
            return jsonify({'error': 'Datos incompletos'}), 400
        nombre_listero = data['nombre']
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        save_listero_to_db(nombre_listero, data, timestamp)
        archivo_listero = os.path.join(LISTEROS_FOLDER, f"{nombre_listero}.json")
        with open(archivo_listero, 'w', encoding='utf-8') as f:
            json.dump({
                'nombre': nombre_listero,
                'timestamp': timestamp,
                'data': data
            }, f, indent=2, ensure_ascii=False)
        log_access(username, '/api/sync-listero', f'Listero sincronizado: {nombre_listero}')
        return jsonify({'success': True, 'message': f'Listero {nombre_listero} sincronizado correctamente', 'timestamp': timestamp})
    except Exception as e:
        log_access(username, '/api/sync-listero', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listeros-completos', methods=['GET'])
def get_listeros_completos():
    username = request.remote_addr
    try:
        listeros = get_all_listeros_from_db()
        log_access(username, '/api/listeros-completos', f'Listando {len(listeros)} listeros')
        return jsonify({'success': True, 'listeros': listeros})
    except Exception as e:
        log_access(username, '/api/listeros-completos', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listero/<nombre>', methods=['GET'])
def get_listero_config(nombre):
    username = request.remote_addr
    try:
        listero = get_listero_from_db(nombre)
        if listero:
            log_access(username, f'/api/listero/{nombre}', 'Configuración encontrada')
            return jsonify(listero)
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
    username = request.remote_addr
    try:
        listeros = get_all_listeros_from_db()
        total = len(listeros)
        cuba_time = datetime.now(cuba_timezone)
        hoy = cuba_time.strftime('%Y-%m-%d')
        sincronizados_hoy = 0
        for l in listeros:
            if hoy in l['ultima_sincronizacion']:
                sincronizados_hoy += 1
        log_access(username, '/api/listeros/estadisticas', 'Estadísticas calculadas')
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

# ============= ENDPOINTS ORIGINALES =============
@app.route('/')
def index():
    return "OK",200

@app.route('/datos', methods=['GET'])
def obtener_datos():
    username = request.remote_addr
    log_access(username, '/datos', 'Datos consultados')
    return jsonify(datos_actuales)

@app.route('/actualizar', methods=['POST'])
def actualizar_datos():
    global datos_actuales
    username = request.remote_addr
    try:
        data = request.get_json()
        if not data:
            log_access(username, '/actualizar', 'Error: No se recibieron datos')
            return jsonify({"error": "No se recibieron datos"}), 400
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
        return jsonify({"mensaje": "Datos actualizados correctamente", "datos": datos_actuales}), 200
    except Exception as e:
        log_access(username, '/actualizar', f'Error: {str(e)}')
        return jsonify({"error": str(e)}), 500

@app.route('/sincronizar', methods=['POST'])
def sincronizar():
    global datos_actuales
    username = request.remote_addr
    try:
        data = request.get_json()
        cambios = []
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
        return jsonify({"mensaje": "Sincronización completada", "datos": datos_actuales}), 200
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
        save_status_change(change_text)
        status = new_status
        log_access(username, '/statuschange', f"Estado cambiado de {old_status} a {new_status}")
        telegram_msg = f"🔄 <b>Cambio de Estado</b>\n\n<b>Usuario:</b> {username}\n<b>Cambio:</b> {old_status} → {new_status}\n<b>Hora:</b> {timestamp}"
        send_telegram_message(telegram_msg)
        return f"Estado cambiado a {new_status}"
    return "Invalid status", 400

@app.route('/lastupdatekilo')
def get_version():
    try:
        url_contenido = "https://raw.githubusercontent.com/user7503tanke/info/refs/heads/main/REA"
        respuesta = requests.get(url_contenido)
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
    filename = file.filename
    filename = filename.replace("controlantimermaxd", "")
    is_valid, message = validate_filename(filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        error_msg = f"❌ <b>Error en subida de lista</b>\n\n<b>Usuario:</b> {username}\n<b>Archivo:</b> {filename}\n<b>Error:</b> {message}"
        send_telegram_message(error_msg)
        return f"Error: {message}", 205
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    file.save(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    save_upload(filename, timestamp)
    log_access(username, '/upload', f'Lista agregada correctamente: {filename}')
    try:
        parts = filename.split('-')
        apodo = parts[0]
        turno = parts[4].capitalize()
        caption = f"📋 <b>Nueva Lista Subida</b>\n\n<b>Archivo:</b> {filename}\n<b>Listero:</b> {apodo}\n<b>Turno:</b> {turno}\n<b>Usuario:</b> {username}\n<b>Hora:</b> {timestamp}"
        send_telegram_document(file_path, caption)
    except Exception as e:
        print(f"Error enviando archivo a Telegram: {e}")
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
    file_size = os.path.getsize(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    os.remove(file_path)
    log_access(username, f'/delete/{filename}', 'Lista eliminada')
    telegram_msg = f"🗑️ <b>Lista Eliminada</b>\n\n<b>Archivo:</b> {filename}\n<b>Tamaño:</b> {file_size} bytes\n<b>Eliminado por:</b> {username}\n<b>Hora:</b> {timestamp}"
    send_telegram_message(telegram_msg)
    return "Lista eliminada correctamente"

@app.route('/db_stats', methods=['GET'])
def get_db_stats():
    username = request.remote_addr
    uploads_count = len(get_uploads())
    downloads_count = len(get_downloads())
    status_changes_count = len(get_status_changes())
    access_count, today_access = get_access_stats()
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

def initialize_services():
    init_database()
    tiradas = load_tiradas()
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    print(f"{timestamp} - Servidor iniciado. Estado: {status}")
    print(f"{timestamp} - Directorio uploads: {UPLOAD_FOLDER}")
    print(f"{timestamp} - Directorio listeros: {LISTEROS_FOLDER}")
    print(f"{timestamp} - Base de datos: {DATABASE_FILE}")
    start_msg = f"🚀 <b>Servidor Iniciado</b>\n\n<b>Estado:</b> {status}\n<b>Hora:</b> {timestamp}\n<b>Uploads:</b> {UPLOAD_FOLDER}\n<b>Base de datos:</b> {DATABASE_FILE}"
    send_telegram_message(start_msg)

initialize_services()
