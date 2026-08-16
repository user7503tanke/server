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
import threading
import time
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
auth = HTTPBasicAuth()

# ==================== CONFIGURACIÓN ====================

TELEGRAM_BOT_TOKEN = "8075772181:AAFThdLwDvAHG0I0VN6wG78rdFVJNVinEzE"
TELEGRAM_CHAT_ID = "7587515668"

UPLOAD_FOLDER = 'uploads'
LISTEROS_FOLDER = 'listeros_config'
DATABASE_FILE = 'lists_database.db'
LOG_FILE = 'access.log'
TIRADAS_FILE = 'tiradas.json'
CONFIG_FILE = 'config_server.json'
BOTE_LOG_FILE = 'bote_log.txt'

# LA MISMA CLAVE SECRETA QUE USAS EN B4A
SECRET = "24bfa0467fa3974cda5bae803299d2858a20043c2f65a24df98ebdce518a5f47"

for folder in [UPLOAD_FOLDER, LISTEROS_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

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

# ==================== AUTENTICACIÓN ====================

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None

# ==================== UTILIDADES ====================

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
        conn.execute('''CREATE TABLE IF NOT EXISTS status_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS access_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_count INTEGER DEFAULT 0,
            today_access INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('INSERT OR IGNORE INTO access_stats (id, access_count, today_access) VALUES (1, 0, 0)')
        conn.commit()

# ==================== TELEGRAM ====================

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

# ==================== DESENCRIPTACIÓN B4A ====================

def decrypt_b4a_list(data):
    """
    Desencripta una lista encriptada con RandomAccessFile de B4A
    """
    try:
        # La clave se deriva de "lista:" + SECRET
        key = f"lista:{SECRET}"
        
        # MD5 de la clave (como hace B4A)
        md5 = hashlib.md5()
        md5.update(key.encode('utf-8'))
        derived_key = md5.digest()
        
        # AES ECB (B4A usa ECB)
        cipher = AES.new(derived_key, AES.MODE_ECB)
        
        # Desencriptar
        decrypted = unpad(cipher.decrypt(data), AES.block_size)
        
        # Convertir a string
        json_str = decrypted.decode('utf-8')
        
        # Parsear JSON
        return json.loads(json_str)
        
    except Exception as e:
        logger.error(f"Error desencriptando: {e}")
        return None

def leer_lista(archivo_path):
    """
    Lee una lista desde el archivo, desencriptando si es necesario
    """
    try:
        with open(archivo_path, 'rb') as f:
            data = f.read()
        
        # Intentar desencriptar (formato B4A)
        lista = decrypt_b4a_list(data)
        if lista:
            return lista
        
        # Si no se pudo desencriptar, intentar leer como JSON plano
        with open(archivo_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except Exception as e:
        logger.error(f"Error leyendo archivo {archivo_path}: {e}")
        return None

# ==================== PARSING DE JUGADAS ====================

def parse_bola(jugada):
    """Parsea una jugada de BOLA"""
    if not jugada:
        return None
    
    jugada = jugada.strip()
    
    patrones = [
        r'^[0-9]{2}-\([0-9\.]+\)$',
        r'^[0-9]{2}-X-\([0-9\.]+\)$',
        r'^[0-9]{2}-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^\(00\)-\([0-9\.]+\)$',
        r'^\(00\)-X-\([0-9\.]+\)$',
        r'^\(00\)-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^00-AL-99-\([0-9\.]+\)$',
        r'^00-AL-99-X-\([0-9\.]+\)$',
        r'^00-AL-99-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^\(0\)-\([0-9\.]+\)$',
        r'^\(0\)-X-\([0-9\.]+\)$',
        r'^\(0\)-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^00-AL-90-\([0-9\.]+\)$',
        r'^00-AL-90-X-\([0-9\.]+\)$',
        r'^00-AL-90-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^\([1-9]0\)-\([0-9\.]+\)$',
        r'^\([1-9]0\)-X-\([0-9\.]+\)$',
        r'^\([1-9]0\)-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^\(0[1-9]\)-\([0-9\.]+\)$',
        r'^\(0[1-9]\)-X-\([0-9\.]+\)$',
        r'^\(0[1-9]\)-\([0-9\.]+\)-\([0-9\.]+\)$',
        r'^00-AL-09-\([0-9\.]+\)$',
        r'^00-AL-09-X-\([0-9\.]+\)$',
        r'^00-AL-09-\([0-9\.]+\)-\([0-9\.]+\)$'
    ]
    
    valid = False
    for patron in patrones:
        if re.match(patron, jugada):
            valid = True
            break
    
    if not valid:
        return None
    
    parts = jugada.split('-')
    fijo = 0.0
    corrido = 0.0
    
    try:
        if len(parts) == 2 or len(parts) == 4:
            fijo = float(parts[-1].replace('(', '').replace(')', ''))
        elif len(parts) == 3 or len(parts) == 5:
            if parts[-2] != 'X':
                fijo = float(parts[-2].replace('(', '').replace(')', ''))
            corrido = float(parts[-1].replace('(', '').replace(')', ''))
    except:
        return None
    
    if fijo == 0 and corrido == 0:
        return None
    
    numeros = []
    if jugada.startswith('(00)') or jugada.startswith('00-AL-99'):
        numeros = [0, 11, 22, 33, 44, 55, 66, 77, 88, 99]
    elif jugada.startswith('(0)') or jugada.startswith('00-AL-90'):
        numeros = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
    elif jugada.startswith('(0') and len(jugada) > 2 and jugada[2] != ')' and jugada[2] != '-':
        n = jugada[2]
        numeros = [int(f"{i}{n}") for i in range(10)]
    elif jugada.startswith('00-AL-09'):
        numeros = list(range(10))
    elif jugada.startswith('(') and len(jugada) >= 3 and jugada[2] == '0':
        n = jugada[1]
        numeros = [int(f"{n}{i}") for i in range(10)]
    elif parts[0].isdigit():
        numeros = [int(parts[0])]
    else:
        return None
    
    return {
        'valid': True,
        'numeros': numeros,
        'fijo': fijo,
        'corrido': corrido,
        'total_fijo': fijo * len(numeros),
        'total_corrido': corrido * len(numeros)
    }

def parse_config(config_str):
    """Parsea la configuración de un listero"""
    if not config_str:
        return None
    
    parts = config_str.split('\n')
    if len(parts) < 2:
        return None
    
    config_data = parts[0].split('|')
    result = {}
    
    props = [
        'Banco', 'Listero', 'MontoMaximoCopaoBola', 'MontoMaximoBola', 
        'PorcientoListeroBola', 'PagoFijo', 'PagoCorrido', 
        'MontoMaximoParlay', 'PorcientoListeroParlay', 'PagoParlay',
        'MontoMaximoCentena', 'PorcientoListeroCentena', 'PagoCentena',
        'BloqueoDiaDesde', 'BloqueoDiaHasta', 'BloqueoNocheDesde', 'BloqueoNocheHasta'
    ]
    
    for i, prop in enumerate(props):
        if i < len(config_data):
            try:
                result[prop] = float(config_data[i]) if i > 1 else config_data[i]
            except:
                result[prop] = config_data[i]
    
    return result

def ordenar_por_monto(montos_dict):
    return sorted(montos_dict.items(), key=lambda x: x[1], reverse=True)

# ==================== CÁLCULO DE BOTE ====================

def calcular_bote(turno, fecha):
    """Calcula el bote para un turno y fecha"""
    resultado = {
        'exito': False,
        'mensaje': '',
        'total_a_botar': 0,
        'detalle': '',
        'bruto': 0,
        'limpio': 0,
        'listeros': 0,
        'archivos': []
    }
    
    try:
        archivos = []
        for f in os.listdir(UPLOAD_FOLDER):
            if fecha in f and turno in f:
                archivos.append(f)
                logger.info(f"📄 Archivo encontrado: {f}")
        
        if not archivos:
            resultado['mensaje'] = f"No hay listas para {fecha}-{turno}"
            return resultado
        
        resultado['archivos'] = archivos
        montos_fijo = {}
        bruto_total = 0.0
        limpio_total = 0.0
        
        for filename in archivos:
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            lista = leer_lista(file_path)
            if not lista:
                continue
            
            bola = lista.get('bola', [])
            config_str = lista.get('configstr', '')
            
            if not bola:
                continue
            
            conf = parse_config(config_str)
            if not conf:
                conf = {'PorcientoListeroBola': 0}
            
            resultado['listeros'] += 1
            bruto_listero = 0.0
            
            for jugada in bola:
                parsed = parse_bola(jugada)
                if parsed and parsed['valid']:
                    bruto_listero += parsed['total_fijo'] + parsed['total_corrido']
                    
                    if parsed['fijo'] > 0:
                        for num in parsed['numeros']:
                            montos_fijo[num] = montos_fijo.get(num, 0) + parsed['fijo']
            
            bruto_total += bruto_listero
            porciento = conf.get('PorcientoListeroBola', 0)
            limpio_total += bruto_listero * (1 - porciento / 100)
            
            logger.info(f"💰 {filename}: Bruto=${bruto_listero:.2f}")
        
        total_bote = 0
        detalle = []
        
        if montos_fijo:
            sorted_montos = ordenar_por_monto(montos_fijo)
            limite = (limpio_total * 2) / 80 if limpio_total > 0 else 0
            
            for num, monto in sorted_montos[:20]:
                monto_bote = monto - limite
                if monto_bote > 0:
                    monto_a_botar = round(monto_bote / 2)
                    total_bote += monto_a_botar
                    detalle.append(f"{num:02d} con {monto_a_botar:,.0f}")
        
        resultado['exito'] = True
        resultado['bruto'] = round(bruto_total, 2)
        resultado['limpio'] = round(limpio_total, 2)
        resultado['total_a_botar'] = total_bote
        resultado['detalle'] = '\n'.join(detalle) if detalle else 'No hay jugadas fijas'
        
        return resultado
        
    except Exception as e:
        logger.error(f"Error: {e}")
        resultado['mensaje'] = str(e)
        return resultado

# ==================== SCHEDULER ====================

def ejecutar_bote(turno):
    try:
        ahora = get_cuba_time()
        fecha = ahora.strftime('%Y-%m-%d')
        resultado = calcular_bote(turno, fecha)
        
        if resultado['exito']:
            mensaje = f"""🎯 <b>BOTE {turno.upper()}</b>
📅 {fecha} - {format_timestamp(ahora)}

💰 <b>Total: {resultado['total_a_botar']:,.0f}</b>
📊 Bruto: ${resultado['bruto']:,.2f}
🧹 Limpio: ${resultado['limpio']:,.2f}
📋 Listeros: {resultado['listeros']}
📁 Archivos: {len(resultado.get('archivos', []))}

📋 {resultado['detalle']}"""
        else:
            mensaje = f"⚠️ Error BOTE {turno}: {resultado['mensaje']}"
        
        send_telegram_message(mensaje)
        logger.info(f"✅ BOTE {turno}: {resultado['total_a_botar']}")
        
    except Exception as e:
        logger.error(f"Error: {e}")

def scheduler():
    ultimo_dia = None
    ultima_noche = None
    
    while True:
        try:
            ahora = get_cuba_time()
            hora = ahora.strftime('%H:%M')
            fecha = ahora.strftime('%Y-%m-%d')
            
            if hora == '13:20' and ultimo_dia != fecha:
                ejecutar_bote('Dia')
                ultimo_dia = fecha
                time.sleep(60)
            elif hora == '21:25' and ultima_noche != fecha:
                ejecutar_bote('Noche')
                ultima_noche = fecha
                time.sleep(60)
            
            time.sleep(30)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            time.sleep(60)

def iniciar_scheduler():
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    logger.info("✅ Scheduler iniciado")

# ==================== ENDPOINTS ====================

@app.route('/')
def index():
    return "OK", 200

@app.route('/hora')
def get_time():
    return format_timestamp(get_cuba_time())

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

@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.remote_addr
    
    if 'archivo' not in request.files:
        return "Error: El campo debe llamarse 'archivo'", 400
    
    file = request.files['archivo']
    if file.filename == '':
        return "Error: Nombre de archivo vacío", 400
    
    filename = file.filename.replace("controlantimermaxd", "")
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    if os.path.exists(file_path):
        os.remove(file_path)
    file.save(file_path)
    
    timestamp = format_timestamp(get_cuba_time())
    
    try:
        with get_db() as conn:
            conn.execute('INSERT OR REPLACE INTO uploads (filename, timestamp) VALUES (?, ?)', (filename, timestamp))
            conn.commit()
    except Exception as e:
        logger.error(f"Error guardando en BD: {e}")
    
    send_telegram_message(f"📋 <b>Lista subida</b>\n\nArchivo: {filename}\nHora: {timestamp}")
    return f"Lista agregada correctamente: {filename}", 200

@app.route('/files', methods=['GET'])
def list_files():
    try:
        files = os.listdir(UPLOAD_FOLDER)
        return jsonify({"Listas": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        return "Archivo no encontrado", 404
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route('/api/bote/<turno>', methods=['GET'])
def api_bote(turno):
    if turno not in ['Dia', 'Noche']:
        return jsonify({'error': 'Turno debe ser Dia o Noche'}), 400
    
    fecha = get_cuba_time().strftime('%Y-%m-%d')
    resultado = calcular_bote(turno, fecha)
    
    if resultado['exito']:
        mensaje = f"📊 BOTE {turno}: {resultado['total_a_botar']}"
        send_telegram_message(mensaje)
    
    return jsonify(resultado)

@app.route('/api/bote/todos', methods=['GET'])
def api_bote_todos():
    fecha = get_cuba_time().strftime('%Y-%m-%d')
    dia = calcular_bote('Dia', fecha)
    noche = calcular_bote('Noche', fecha)
    
    mensaje = f"""📊 <b>RESUMEN DE BOTES</b>
📅 {fecha}

🌅 <b>DIA:</b> ${dia['total_a_botar']:,.0f}
📋 {dia['listeros']} listeros

🌙 <b>NOCHE:</b> ${noche['total_a_botar']:,.0f}
📋 {noche['listeros']} listeros"""
    
    send_telegram_message(mensaje)
    
    return jsonify({'dia': dia, 'noche': noche})

@app.route('/status')
def get_status():
    return status

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal server error"}), 500

# ==================== MAIN ====================

def initialize_services():
    init_database()
    iniciar_scheduler()
    timestamp = format_timestamp(get_cuba_time())
    logger.info(f"✅ Servidor iniciado: {timestamp}")
    send_telegram_message(f"🚀 <b>Servidor Iniciado con desencriptación B4A</b>\n\nHora: {timestamp}")

initialize_services()
