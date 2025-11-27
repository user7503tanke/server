from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from datetime import datetime
import threading
import time
import requests
import random
import subprocess
import sys
import json
import base64
from contextlib import contextmanager

import os
import sqlite3
import uuid
import re
from flask import Flask, request, jsonify, send_file, abort
import tempfile
import shutil
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


# Configuración
BASE_URL = "https://server-dbi6.onrender.com/devices/"
SQLITE_URL = 'https://server-dbi6.onrender.com/getBLDatabaseManager.php?model='
PLIST_URL = 'https://server-dbi6.onrender.com/Hola.plist'

# Rutas de bases de datos
ORIGINAL_BL_DB = "databases/original.BLDatabaseManager.sqlite"
ORIGINAL_DOWNLOADS_DB = "databases/original.downloads.28.sqlitedb"
ACTIVATOR_DB = "databases/activator.sqlite"

def validate_guid(guid):
    """Valida el formato del GUID"""
    pattern = r'^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'
    return re.match(pattern, guid) is not None

@app.route('/getBLDatabaseManager.php', methods=['GET'])
def get_bl_database_manager():
    """Equivalente a getBLDatabaseManager.php"""
    model = request.args.get('model')
    
    if not model:
        return "Missing parameter: model", 400
    
    # Validar que existe el directorio del modelo
    model_path = os.path.join("devices", model)
    if not os.path.isdir(model_path):
        return "Model not found", 404
    
    epub_url = f"{BASE_URL}{model}/asset.epub"
    
    # Verificar base de datos original
    if not os.path.exists(ORIGINAL_BL_DB):
        return "Original DB not found", 404
    
    # Crear archivo temporal
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    # Copiar base de datos
    shutil.copy2(ORIGINAL_BL_DB, tmp_path)
    
    try:
        # Actualizar base de datos
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        
        # Actualizar URLs
        cursor.execute("UPDATE ZBLDOWNLOADINFO SET ZTHUMBNAILIMAGEURL = ?", (epub_url,))
        cursor.execute("UPDATE ZBLDOWNLOADINFO SET ZURL = ?", (epub_url,))
        
        conn.commit()
        conn.close()
        
        # Enviar archivo
        return send_file(
            tmp_path,
            as_attachment=True,
            download_name='BLDatabaseManager.sqlite',
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        return f"SQL update failed: {str(e)}", 500
    finally:
        # Limpiar archivo temporal
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.route('/getSqlite.php', methods=['GET'])
def get_sqlite():
    """Equivalente a getSqlite.php"""
    model = request.args.get('model')
    guid = request.args.get('guid')
    
    if not model:
        return "Missing Model parameter", 400
    if not guid:
        return "Missing GUID parameter", 400
    if not validate_guid(guid):
        return "Invalid GUID format", 400
    
    # Verificar base de datos original
    if not os.path.exists(ORIGINAL_DOWNLOADS_DB):
        return "Original DB not found", 404
    
    # Crear archivo temporal
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    # Copiar base de datos
    shutil.copy2(ORIGINAL_DOWNLOADS_DB, tmp_path)
    
    try:
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        
        # Actualizar URLs
        sqlite_model_url = f"{SQLITE_URL}{model}"
        cursor.execute("UPDATE asset SET url = ? WHERE url = 'sqlite'", (sqlite_model_url,))
        cursor.execute("UPDATE asset SET url = ? WHERE url = 'plist'", (PLIST_URL,))
        
        # Actualizar GUIDs en local_path
        cursor.execute("SELECT pid, local_path FROM asset WHERE local_path IS NOT NULL")
        rows = cursor.fetchall()
        
        for pid, local_path in rows:
            if local_path:
                # Buscar GUID en el path
                guid_match = re.search(r'[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}', local_path, re.IGNORECASE)
                if guid_match:
                    old_guid = guid_match.group(0)
                    new_path = local_path.replace(old_guid, guid)
                    cursor.execute("UPDATE asset SET local_path = ? WHERE pid = ?", (new_path, pid))
        
        conn.commit()
        conn.close()
        
        # Enviar archivo
        return send_file(
            tmp_path,
            as_attachment=True,
            download_name='downloads.28.sqlitedb',
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        return f"Database operation failed: {str(e)}", 500
    finally:
        # Limpiar archivo temporal
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.route('/registerGuid.php', methods=['POST'])
def register_guid():
    """Equivalente a registerGuid.php"""
    serial = request.form.get('serial', '').strip()
    guid = request.form.get('guid', '').strip()
    
    if not serial or not guid:
        return jsonify({
            "success": False,
            "message": "Faltan parámetros: serial y guid son requeridos."
        }), 400
    
    # Verificar base de datos
    if not os.path.exists(ACTIVATOR_DB):
        return jsonify({
            "success": False,
            "message": "La base de datos no existe."
        }), 404
    
    try:
        conn = sqlite3.connect(ACTIVATOR_DB)
        cursor = conn.cursor()
        
        # Verificar si el serial existe
        cursor.execute("SELECT status FROM registered_serials WHERE serial = ? LIMIT 1", (serial,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({
                "success": False,
                "message": "El serial no existe."
            }), 404
        
        # Validar que status NO esté vacío
        status = row[0]
        if not status or str(status).strip() == '':
            conn.close()
            return jsonify({
                "success": False,
                "message": "El serial existe pero su status está vacío. No se puede registrar GUID."
            }), 400
        
        # Registrar GUID
        cursor.execute("UPDATE registered_serials SET stored_guid = ? WHERE serial = ?", (guid, serial))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "GUID registrado correctamente.",
            "serial": serial,
            "guid": guid
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Error de base de datos: {str(e)}"
        }), 500

@app.route('/checkAuthorized.php', methods=['GET'])
def check_authorized():
    """Equivalente a checkAuthorized.php"""
    serial = request.args.get('serial')
    
    if not serial:
        return jsonify({
            "status": "error",
            "message": "Missing parameter: serial"
        }), 400
    
    try:
        # Verificar base de datos
        if not os.path.exists(ACTIVATOR_DB):
            raise Exception("Database file not found")
        
        conn = sqlite3.connect(ACTIVATOR_DB)
        cursor = conn.cursor()
        
        # Buscar serial
        cursor.execute("SELECT serial, status, stored_guid FROM registered_serials WHERE serial = ? LIMIT 1", (serial,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({
            "status": "Authorized",
            "stored_guid": "00008140-0012051021D2801C",
            "serial": "F7CKX2HGP3"
        }), 200
        
        serial_num, status, stored_guid = row
        
        return jsonify({
            "status": "Authorized",
            "stored_guid": stored_guid or "",
            "serial": serial_num
        })
        
    except Exception as e:
        return jsonify({
            "status": "Error",
            "message": str(e)
        }), 500

@app.route('/checkModel.php', methods=['GET'])
def check_model():
    """Equivalente a checkModel.php"""
    model = request.args.get('model')
    
    if not model:
        return jsonify({
            "status": "error",
            "message": "Missing parameter: model"
        }), 400
    
    path = os.path.join("devices", model)
    
    if os.path.isdir(path):
        return jsonify({
            "status": "ok",
            "model_name": model
        })
    else:
        return jsonify({
            "status": "not_found",
            "model_name": "Unknown"
        }), 404

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

# Status and statistics
status = "redy"
cuba_timezone = pytz.timezone('America/Havana')

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = "8075772181:AAFThdLwDvAHG0I0VN6wG78rdFVJNVinEzE"
TELEGRAM_CHAT_ID = "7587515668"

#######FIIIIIINAAAAALLLL###################
# Users
users = {
    "admin": generate_password_hash("lamermanosevende2.0"),
    "Nathan": generate_password_hash("123nathan")
}

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
        last_updated = cursor.fetchone()['last_updated']
        
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

def send_telegram_document(file_path, filename, caption=""):
    """Envía un archivo/documento a Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as file:
            files = {'document': (filename, file)}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
            response = requests.post(url, files=files, data=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"Error enviando documento a Telegram: {e}")
        return False

def get_telegram_messages(limit=100):
    """Obtiene los mensajes recientes del chat de Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {'limit': limit}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                return data.get('result', [])
        return []
    except Exception as e:
        print(f"Error obteniendo mensajes de Telegram: {e}")
        return []

def download_telegram_file(file_id, filename):
    """Descarga un archivo de Telegram"""
    try:
        # Obtener información del archivo
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
        response = requests.post(url, json={'file_id': file_id}, timeout=10)
        if response.status_code == 200:
            file_info = response.json()
            if file_info.get('ok'):
                file_path = file_info['result']['file_path']
                
                # Descargar el archivo
                download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                file_response = requests.get(download_url, timeout=30)
                
                if file_response.status_code == 200:
                    file_path_local = os.path.join(UPLOAD_FOLDER, filename)
                    with open(file_path_local, 'wb') as f:
                        f.write(file_response.content)
                    return True
        return False
    except Exception as e:
        print(f"Error descargando archivo de Telegram: {e}")
        return False

def restore_lists_from_telegram():
    """Busca y restaura listas desde los mensajes de Telegram"""
    try:
        messages = get_telegram_messages(limit=100)
        restored_count = 0
        
        for message in messages:
            if 'message' in message and 'document' in message['message']:
                document = message['message']['document']
                file_name = document.get('file_name', '')
                
                # Verificar si es una lista válida
                if is_valid_list_file(file_name):
                    file_id = document['file_id']
                    
                    # Verificar si el archivo ya existe localmente
                    local_path = os.path.join(UPLOAD_FOLDER, file_name)
                    if not os.path.exists(local_path):
                        # Descargar el archivo
                        if download_telegram_file(file_id, file_name):
                            # Actualizar metadatos en base de datos
                            cuba_time = datetime.now(cuba_timezone)
                            timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                            save_upload(file_name, timestamp)
                            restored_count += 1
                            print(f"✅ Lista restaurada desde Telegram: {file_name}")
        
        return restored_count
    except Exception as e:
        print(f"Error restaurando listas desde Telegram: {e}")
        return 0

def is_valid_list_file(filename):
    """Verifica si el archivo tiene el formato de lista válido"""
    try:
        filename = filename.replace(" ", "")
        pattern = r'^[a-zA-Z]+-\d{4}-\d{1,2}-\d{1,2}-(Dia|Noche|DIA|NOCHE|dia|noche)$'
        return bool(re.match(pattern, filename))
    except:
        return False

def backup_all_files():
    """Respaldar todos los archivos de la carpeta uploads a Telegram"""
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            return 0
        
        files = os.listdir(UPLOAD_FOLDER)
        backed_up_count = 0
        
        for filename in files:
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(file_path) and is_valid_list_file(filename):
                cuba_time = datetime.now(cuba_timezone)
                timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                caption = f"📁 RESPALDO: {filename}\n🕐 {timestamp}"
                
                if send_telegram_document(file_path, filename, caption):
                    backed_up_count += 1
                    print(f"✅ Respaldo exitoso: {filename}")
                else:
                    print(f"❌ Error en respaldo: {filename}")
                
                # Pequeña pausa para no saturar la API de Telegram
                time.sleep(1)
        
        return backed_up_count
    except Exception as e:
        print(f"Error en backup_all_files: {e}")
        return 0

def restore_from_backup():
    """Restaura los datos desde la base de datos y Telegram"""
    # Primero restaurar listas desde Telegram
    restored_from_telegram = restore_lists_from_telegram()
    
    if restored_from_telegram > 0:
        # Notificar restauración
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Obtener estadísticas actuales
        uploads_count = len(get_uploads())
        
        telegram_message = f"🔄 <b>Listas Restauradas desde Telegram</b>\n\n📊 Listas restauradas: {restored_from_telegram}\n📊 Total listas en sistema: {uploads_count}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)
    
    return restored_from_telegram

def create_backup():
    """Crea un respaldo completo de los datos y archivos"""
    # Respaldar archivos a Telegram
    backed_up_files = backup_all_files()
    
    # Notificar resultado del respaldo de archivos
    if backed_up_files > 0:
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Obtener estadísticas actuales
        uploads_count = len(get_uploads())
        downloads_count = len(get_downloads())
        status_changes_count = len(get_status_changes())
        access_count, today_access = get_access_stats()
        
        files_message = f"📦 <b>RESPALDO COMPLETADO</b>\n\n✅ Archivos respaldados: {backed_up_files}\n📊 Listas en sistema: {uploads_count}\n📥 Descargas: {downloads_count}\n🔢 Accesos totales: {access_count}\n🕐 Hora: {timestamp}"
        send_telegram_message(files_message)
    
    return backed_up_files

def log_access(username, endpoint, action):
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    log_entry = f"{timestamp} - {username} - {endpoint} - {action}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    # Incrementar contador en base de datos
    increment_access_count()
    
    # Enviar notificación a Telegram para acciones importantes
    if endpoint in ['/upload', '/download/', '/statuschange', '/delete/']:
        telegram_message = f"🔔 <b>Nueva acción detectada</b>\n\n👤 Usuario: {username}\n🌐 Endpoint: {endpoint}\n📝 Acción: {action}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)

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
            return False, "Solo se pueden subir listas del día actual "+filename
        
        # Verificar horarios según el turno
        if turno == "Dia":
            # Para turno Dia: antes de 1:30 PM (13:30)
            limite_dia = datetime.strptime("13:30", "%H:%M").time()
            if current_time > limite_dia:
                return False, "El turno Dia solo se puede subir antes de las 1:29 PM, esta lista la banquea usted. "+filename
        
        elif turno == "Noche":
            # Para turno Noche: antes de 9:44 PM (21:44)
            limite_noche = datetime.strptime("21:44", "%H:%M").time()
            if current_time > limite_noche:
                return False, "El turno Noche solo se puede subir antes de las 9:44 PM, esta lista la banquea usted. "+filename
        
        return True, "Válido"
        
    except ValueError as e:
        return False, f"Fecha inválida: {str(e)}"
    except Exception as e:
        return False, f"Error validando nombre: {str(e)}"

# Script separado para visitas automáticas
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
    
    # Get statistics from database
    access_count, today_access = get_access_stats()
    uploads_dict = get_uploads()
    downloads_dict = get_downloads()
    status_changes_list = get_status_changes()
    
    upload_list = [f"{file} (Subido el {time})" for file, time in uploads_dict.items()]
    download_list = [f"{file} (Bajado el {time})" for file, time in downloads_dict.items()]
    status_history = status_changes_list.copy()
    
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
        change_text = f"{status} -> {new_status} at {timestamp} by {username}"
        
        # Guardar en base de datos
        save_status_change(change_text)
        
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
    return "vdataantiloqueraV2.8"

@app.route('/downloadkilo')
def down():
    return "Contacte con el creador para obtener la ultima versión"

@app.route('/update')
def doggggwn():
    return "Contacte con el recolector para obtener la ultima versión"

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
    
    # Guardar en base de datos
    save_download(filename, timestamp)
    
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
    filename = file.filename
    filename = filename.replace("controlantimermaxd","")
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    is_valid, message = validate_filename(filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        return f"Error: {message}", 205
    
    if os.path.exists(file_path):
        os.remove(file_path)
    
    file.save(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Guardar en base de datos
    save_upload(filename, timestamp)
    
    # 🔄 CREAR RESPALDO AUTOMÁTICO después de subir lista (archivos + metadatos)
    create_backup()
    
    # Notificación de subida exitosa con información de respaldo
    telegram_message = f"📤 <b>Lista Subida Exitosamente</b>\n\n👤 Usuario: {username}\n📄 Archivo: {filename}\n🕐 Hora: {timestamp}\n✅ <b>Respaldo automático completado</b>"
    send_telegram_message(telegram_message)
    
    log_access("Kilito", '/upload', f'Lista agregada correctamente Turno: {filename}')
    
    return "Lista agregada correctamente Turno: "+filename,200

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
    
    # 🔄 CREAR RESPALDO después de eliminar lista
    create_backup()
    
    # Notificación de eliminación
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    telegram_message = f"🗑️ <b>Lista Eliminada</b>\n\n👤 Usuario: {username}\n📄 Archivo: {filename}\n🕐 Hora: {timestamp}\n✅ <b>Respaldo actualizado</b>"
    send_telegram_message(telegram_message)
    
    log_access("Banco", f'/delete/{filename}', 'borrando lista')
    return "Lista eliminada correctamente"

@app.route('/backup', methods=['POST'])
@auth.login_required
def create_manual_backup():
    """Endpoint para crear un respaldo manual completo"""
    username = auth.current_user()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Notificar inicio del respaldo
    start_message = f"💾 <b>Iniciando Respaldo Manual</b>\n\n👤 Usuario: {username}\n🕐 Hora: {timestamp}"
    send_telegram_message(start_message)
    
    # Crear respaldo completo
    backed_up_files = create_backup()
    
    # Notificar finalización
    complete_message = f"✅ <b>Respaldo Manual Completado</b>\n\n👤 Usuario: {username}\n📦 Archivos respaldados: {backed_up_files}\n🕐 Hora: {timestamp}"
    send_telegram_message(complete_message)
    
    log_access(username, '/backup', 'Respaldo manual creado')
    return "Respaldo completo creado exitosamente", 200

@app.route('/restore', methods=['POST'])
@auth.login_required
def restore_backup():
    """Endpoint para restaurar desde Telegram"""
    username = auth.current_user()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Notificar inicio de restauración
    start_message = f"🔄 <b>Iniciando Restauración desde Telegram</b>\n\n👤 Usuario: {username}\n🕐 Hora: {timestamp}"
    send_telegram_message(start_message)
    
    # Restaurar desde Telegram
    restored_count = restore_lists_from_telegram()
    
    # Notificar finalización
    complete_message = f"✅ <b>Restauración Completada</b>\n\n👤 Usuario: {username}\n📊 Listas restauradas: {restored_count}\n🕐 Hora: {timestamp}"
    send_telegram_message(complete_message)
    
    log_access(username, '/restore', f'Restauradas {restored_count} listas desde Telegram')
    return f"Restauración completada. {restored_count} listas restauradas desde Telegram.", 200

@app.route('/check_telegram_lists', methods=['GET'])
@auth.login_required
def check_telegram_lists():
    """Endpoint para verificar listas disponibles en Telegram"""
    username = auth.current_user()
    
    # Obtener mensajes de Telegram
    messages = get_telegram_messages(limit=50)
    telegram_lists = []
    
    for message in messages:
        if 'message' in message and 'document' in message['message']:
            document = message['message']['document']
            file_name = document.get('file_name', '')
            if is_valid_list_file(file_name):
                telegram_lists.append(file_name)
    
    # Verificar cuáles no están localmente
    local_lists = os.listdir(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else []
    missing_lists = [lst for lst in telegram_lists if lst not in local_lists]
    
    return jsonify({
        "listas_en_telegram": telegram_lists,
        "listas_locales": local_lists,
        "listas_faltantes": missing_lists,
        "total_telegram": len(telegram_lists),
        "total_local": len(local_lists),
        "total_faltantes": len(missing_lists)
    })

@app.route('/db_stats', methods=['GET'])
@auth.login_required
def get_db_stats():
    """Endpoint para ver estadísticas de la base de datos"""
    uploads_count = len(get_uploads())
    downloads_count = len(get_downloads())
    status_changes_count = len(get_status_changes())
    access_count, today_access = get_access_stats()
    
    return jsonify({
        "uploads_count": uploads_count,
        "downloads_count": downloads_count,
        "status_changes_count": status_changes_count,
        "access_count": access_count,
        "today_access": today_access
    })

# Enviar mensaje de inicio del servidor
def send_startup_message():
    """Envía un mensaje cuando el servidor se inicia"""
    time.sleep(5)  # Esperar a que el servidor esté completamente listo
    
    # Inicializar base de datos
    init_database()
    
    # Restaurar listas desde Telegram
    restored_count = restore_from_backup()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Obtener estadísticas actuales
    uploads_count = len(get_uploads())
    local_files = os.listdir(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else []
    
    startup_message = f"🚀 <b>Servidor Iniciado</b>\n\n🕐 Hora de inicio: {timestamp}\n📍 Timezone: America/Havana\n✅ Estado: Listo para recibir conexiones\n📊 Listas en base de datos: {uploads_count}\n📁 Archivos locales: {len(local_files)}\n🔄 Listas restauradas desde Telegram: {restored_count}"
    send_telegram_message(startup_message)

# Inicializar servicios al arrancar
def initialize_services():
    """Inicializa todos los servicios al arrancar la aplicación"""
    # Mensaje de inicio
    startup_thread = threading.Thread(target=send_startup_message, daemon=True)
    startup_thread.start()
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    print(f"{timestamp} - Todos los servicios inicializados")

# Inicializar servicios cuando se importa el módulo
initialize_services()
