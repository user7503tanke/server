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
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
auth = HTTPBasicAuth()

TELEGRAM_BOT_TOKEN = "8075772181:AAFThdLwDvAHG0I0VN6wG78rdFVJNVinEzE"
TELEGRAM_CHAT_ID = "7587515668"

UPLOAD_FOLDER = 'uploads'
LISTEROS_FOLDER = 'listeros_config'
DATABASE_FILE = 'lists_database.db'
LOG_FILE = 'access.log'
TIRADAS_FILE = 'tiradas.json'
CONFIG_FILE = 'config_server.json'

for folder in [UPLOAD_FOLDER, LISTEROS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

status = "redy"
cuba_timezone = pytz.timezone('America/Havana')

datos_actuales = {
    "dia": "",
    "noche": ""
}

users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "newyork": generate_password_hash("newyork4507")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None

def get_cuba_time():
    return datetime.now(cuba_timezone)

def format_timestamp(dt):
    return dt.strftime('%Y-%m-%d %I:%M:%S %p')

def load_json_file(filename, default=None):
    if default is None:
        default = {}
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json_file(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except:
        return False

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS listeros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            config TEXT NOT NULL,
            ultima_sincronizacion TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return None

def send_telegram_document(file_path, caption=""):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as file:
            response = requests.post(url, files={'document': file}, 
                                   data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}, timeout=30)
        return response.json()
    except Exception as e:
        logger.error(f"Telegram document error: {e}")
        return None

def log_access(username, endpoint, action):
    cuba_time = get_cuba_time()
    timestamp = format_timestamp(cuba_time)
    
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} - {username} - {endpoint} - {action}\n")
    
    if any(k in action for k in ["Error", "attempted", "Lista agregada", "Eliminada"]):
        send_telegram_message(f"🔔 <b>Notificación</b>\n\n<b>Usuario:</b> {username}\n<b>Endpoint:</b> {endpoint}\n<b>Acción:</b> {action}\n<b>Hora:</b> {timestamp}")

def validate_filename(filename):
    filename = filename.replace(" ", "")
    pattern = r'^(?:Florida-|Georgia-)?[a-zA-Z0-9]+-\d{4}-\d{1,2}-\d{1,2}-(Dia|Noche|DIA|NOCHE|dia|noche)$'
    
    if not re.match(pattern, filename):
        return False, f"Formato inválido. Debe ser: [Florida-|Georgia-][apodo]-YYYY-MM-DD-Turno"
    
    try:
        prefix = None
        base_filename = filename
        for p in ['Florida-', 'Georgia-']:
            if filename.startswith(p):
                prefix = p[:-1]
                base_filename = filename[len(p):]
                break
        
        parts = base_filename.split('-')
        year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
        turno = parts[4].capitalize()
        
        file_date = datetime(year, month, day).date()
        cuba_now = get_cuba_time()
        
        if file_date != cuba_now.date():
            return False, f"Solo se permiten listas del día actual"
        
        limits = {
            'Florida': {'Dia': '13:30', 'Noche': '21:40'},
            'Georgia': {'Dia': '12:25', 'Noche': '18:55'},
            None: {'Dia': '13:30', 'Noche': '21:40'}
        }
        
        key = prefix if prefix in limits else None
        limit_time = datetime.strptime(limits[key][turno], "%H:%M").time()
        
        if cuba_now.time() > limit_time:
            return False, f"Horario límite para {turno} {prefix or 'Florida'}: {limits[key][turno]}"
        
        return True, "Válido"
    except Exception as e:
        return False, f"Error: {str(e)}"

# ==================== ENDPOINTS ====================

@app.route('/')
def index():
    return "OK", 200

@app.route('/hora')
def get_time():
    username = request.remote_addr
    hora_str = format_timestamp(get_cuba_time())
    log_access(username, '/hora', f'Hora consultada: {hora_str}')
    return hora_str

@app.route('/lastupdatekilo')
def get_version():
    try:
        url = "https://raw.githubusercontent.com/user7503tanke/info/refs/heads/main/REA"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return f"vdataantiloquera{response.text.strip()}"
        return f"Error: {response.status_code}", 500
    except Exception as e:
        return f"Error: {str(e)}", 400

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
            send_telegram_message(f"📊 <b>Datos actualizados</b>\n\n{chr(10).join(cambios)}\n<b>Usuario:</b> {username}")
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

@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.remote_addr
    
    if 'archivo' not in request.files:
        log_access(username, '/upload', 'attempted upload (no file part)')
        return "Error: El campo debe llamarse 'archivo'", 400
    
    file = request.files['archivo']
    if file.filename == '':
        log_access(username, '/upload', 'attempted upload (empty filename)')
        return "Error: Nombre de archivo vacío", 400
    
    filename = file.filename.replace("controlantimermaxd", "")
    is_valid, message = validate_filename(filename)
    
    if not is_valid:
       # log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        send_telegram_message(f"❌ <b>Error en subida</b>\n\n<b>Usuario:</b> {username}\n<b>Archivo:</b> {filename}\n<b>Error:</b> {message}")
        return f"Error: {message}", 205
    
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    file.save(file_path)
    
    timestamp = format_timestamp(get_cuba_time())
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO uploads (filename, timestamp) VALUES (?, ?)', (filename, timestamp))
        conn.commit()
    
   # log_access(username, '/upload', f'Lista agregada correctamente: {filename}')
    
    try:
        parts = filename.split('-')
        apodo = parts[1]
        turno = parts[5].capitalize()
        caption = f"📋 <b>Nueva Lista Subida</b>\n\n<b>Archivo:</b> {filename}\n<b>Listero:</b> {apodo}\n<b>Turno:</b> {turno}\n<b>Usuario:</b> {username}\n<b>Hora:</b> {timestamp}"
        send_telegram_document(file_path, caption)
    except:
        send_telegram_message(f"✅ <b>Lista subida</b>\n\nArchivo: {filename}\nHora: {timestamp}")
    
    return f"Lista agregada correctamente: {filename}", 200

@app.route('/files', methods=['GET'])
def list_files():
    log_access("Banco", '/files', 'Listando archivos')
    try:
        files = os.listdir(UPLOAD_FOLDER)
        return jsonify({"Listas": files})
    except:
        return jsonify({"error": "Error al listar archivos"}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    username = request.remote_addr
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(file_path):
        log_access(username, f'/download/{filename}', 'attempted download (file not found)')
        return "Archivo no encontrado", 404
    
    timestamp = format_timestamp(get_cuba_time())
    with get_db() as conn:
        conn.execute('INSERT INTO downloads (filename, timestamp) VALUES (?, ?)', (filename, timestamp))
        conn.commit()
    
    #log_access(username, f'/download/{filename}', f'Descargando lista: {filename}')
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# ==================== LISTEROS ====================

@app.route('/api/sync-listero', methods=['POST'])
def sync_listero():
    username = request.remote_addr
    try:
        data = request.get_json()
        if not data or 'nombre' not in data:
            return jsonify({'error': 'Datos incompletos'}), 400
        
        nombre = data['nombre']
        timestamp = format_timestamp(get_cuba_time())
        
        with get_db() as conn:
            conn.execute('INSERT OR REPLACE INTO listeros (nombre, config, ultima_sincronizacion) VALUES (?, ?, ?)',
                        (nombre, json.dumps(data, ensure_ascii=False), timestamp))
            conn.commit()
        
        with open(os.path.join(LISTEROS_FOLDER, f"{nombre}.json"), 'w', encoding='utf-8') as f:
            json.dump({'nombre': nombre, 'timestamp': timestamp, 'data': data}, f, indent=2, ensure_ascii=False)
        
        log_access(username, '/api/sync-listero', f'Listero sincronizado: {nombre}')
        return jsonify({'success': True, 'message': f'Listero {nombre} sincronizado', 'timestamp': timestamp})
    except Exception as e:
        log_access(username, '/api/sync-listero', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listeros-completos', methods=['GET'])
def get_listeros_completos():
    username = request.remote_addr
    try:
        with get_db() as conn:
            rows = conn.execute('SELECT nombre, config, ultima_sincronizacion FROM listeros ORDER BY nombre').fetchall()
            listeros = [{
                'nombre': row['nombre'],
                'ultima_sincronizacion': row['ultima_sincronizacion'],
                'config': json.loads(row['config'])
            } for row in rows]
        
        log_access(username, '/api/listeros-completos', f'Listando {len(listeros)} listeros')
        return jsonify({'success': True, 'listeros': listeros})
    except Exception as e:
        log_access(username, '/api/listeros-completos', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/listero/<nombre>', methods=['GET'])
def get_listero_config(nombre):
    username = request.remote_addr
    try:
        with get_db() as conn:
            row = conn.execute('SELECT nombre, config, ultima_sincronizacion FROM listeros WHERE nombre = ?', (nombre,)).fetchone()
            if row:
                log_access(username, f'/api/listero/{nombre}', 'Configuración encontrada')
                return jsonify({
                    'nombre': row['nombre'],
                    'ultima_sincronizacion': row['ultima_sincronizacion'],
                    'config': json.loads(row['config'])
                })
        
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
        with get_db() as conn:
            rows = conn.execute('SELECT ultima_sincronizacion FROM listeros').fetchall()
        
        total = len(rows)
        hoy = get_cuba_time().strftime('%Y-%m-%d')
        sincronizados_hoy = sum(1 for r in rows if hoy in r['ultima_sincronizacion'])
        
        log_access(username, '/api/listeros/estadisticas', 'Estadísticas calculadas')
        return jsonify({
            'success': True,
            'estadisticas': {
                'total_listeros': total,
                'sincronizados_hoy': sincronizados_hoy,
                'ultima_actualizacion': format_timestamp(get_cuba_time())
            }
        })
    except Exception as e:
        log_access(username, '/api/listeros/estadisticas', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ==================== TIRADAS ====================

@app.route('/api/tirada/<turno>', methods=['GET'])
def get_tirada(turno):
    username = request.remote_addr
    tiradas = load_json_file(TIRADAS_FILE)
    log_access(username, f'/api/tirada/{turno}', 'Tirada obtenida')
    return jsonify({'turno': turno, 'tirada': tiradas.get(turno, '0-00-00-00')})

@app.route('/api/tirada/<turno>', methods=['POST'])
def set_tirada(turno):
    username = request.remote_addr
    try:
        data = request.get_json()
        if not data or 'tirada' not in data:
            return jsonify({'error': 'Formato incorrecto'}), 400
        
        tiradas = load_json_file(TIRADAS_FILE)
        tiradas[turno] = data['tirada']
        save_json_file(TIRADAS_FILE, tiradas)
        
        log_access(username, f'/api/tirada/{turno}', f'Tirada guardada: {data["tirada"]}')
        return jsonify({'mensaje': 'Tirada guardada', 'turno': turno, 'tirada': data['tirada']})
    except Exception as e:
        log_access(username, f'/api/tirada/{turno}', f'Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/tiradas/all', methods=['GET'])
@auth.login_required
def get_all_tiradas():
    username = auth.current_user()
    tiradas = load_json_file(TIRADAS_FILE)
    log_access(username, '/api/tiradas/all', 'Enviando todas las tiradas')
    return jsonify(tiradas)

@app.route('/api/tiradas/all', methods=['POST'])
@auth.login_required
def set_all_tiradas():
    username = auth.current_user()
    data = request.get_json()
    if data is None:
        return jsonify({'error': 'No data'}), 400
    save_json_file(TIRADAS_FILE, data)
    log_access(username, '/api/tiradas/all', 'Tiradas actualizadas')
    return jsonify({'success': True})

@app.route('/api/config', methods=['GET'])
@auth.login_required
def get_config():
    username = auth.current_user()
    config = load_json_file(CONFIG_FILE)
    log_access(username, '/api/config', 'Configuración enviada')
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
@auth.login_required
def set_config():
    username = auth.current_user()
    data = request.get_json()
    if data is None:
        return jsonify({'error': 'No data'}), 400
    save_json_file(CONFIG_FILE, data)
    log_access(username, '/api/config', 'Configuración actualizada')
    return jsonify({'success': True})

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal server error"}), 500

# ==================== INIT ====================

def initialize_services():
    init_database()
    
    for file in [TIRADAS_FILE, CONFIG_FILE]:
        if not os.path.exists(file):
            save_json_file(file, {})
    
    timestamp = format_timestamp(get_cuba_time())
    logger.info(f"{timestamp} - Servidor iniciado. Estado: {status}")
    
    send_telegram_message(f"🚀 <b>Servidor Iniciado</b>\n\n<b>Estado:</b> {status}\n<b>Hora:</b> {timestamp}")

initialize_services()
