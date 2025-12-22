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
TELEGRAM_CHAT_ID = "-1003535679115"  # Cambia esto al ID de tu grupo ""

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
    
    # Table for telegram message IDs (NUEVA TABLA)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telegram_message_ids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER UNIQUE NOT NULL,
            file_id TEXT NOT NULL,
            filename TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
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

# FUNCIONES NUEVAS PARA MANEJO DE MENSAJES DE TELEGRAM

def delete_telegram_message(message_id):
    """Elimina un mensaje específico de Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_id": message_id
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error eliminando mensaje de Telegram: {e}")
        return False

def save_or_replace_telegram_message(message_id, file_id, filename):
    """Guarda o reemplaza el ID de mensaje de Telegram"""
    try:
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Buscar si ya existe un mensaje con este nombre de archivo
            cursor.execute(
                'SELECT message_id FROM telegram_message_ids WHERE filename = ?',
                (filename,)
            )
            existing = cursor.fetchone()
            
            # Si existe, eliminar el mensaje antiguo de Telegram
            if existing:
                old_message_id = existing['message_id']
                print(f"🔍 Encontrado mensaje antiguo para {filename}: ID {old_message_id}")
                delete_telegram_message(old_message_id)
                
                # Eliminar el registro antiguo de la base de datos
                cursor.execute(
                    'DELETE FROM telegram_message_ids WHERE filename = ?',
                    (filename,)
                )
            
            # Insertar nuevo registro
            cursor.execute('''
                INSERT INTO telegram_message_ids 
                (message_id, file_id, filename, timestamp) 
                VALUES (?, ?, ?, ?)
            ''', (message_id, file_id, filename, timestamp))
            
            # Mantener solo los últimos 10 registros
            cursor.execute('''
                DELETE FROM telegram_message_ids 
                WHERE id NOT IN (
                    SELECT id FROM telegram_message_ids 
                    ORDER BY created_at DESC 
                    LIMIT 10
                )
            ''')
            
            conn.commit()
        
        print(f"✅ ID de mensaje guardado/reemplazado: {message_id} para {filename}")
        return True
    except Exception as e:
        print(f"❌ Error guardando/reemplazando ID: {e}")
        return False

def get_last_telegram_message_ids(limit=10):
    """Obtiene los últimos IDs de mensajes de Telegram"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT message_id, file_id, filename, timestamp 
                FROM telegram_message_ids 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            
            results = cursor.fetchall()
            return [dict(row) for row in results]
    except Exception as e:
        print(f"Error obteniendo IDs de mensajes: {e}")
        return []

def download_from_saved_message_ids():
    """Descarga archivos usando los IDs de mensajes guardados"""
    try:
        message_ids = get_last_telegram_message_ids(10)
        downloaded_count = 0
        
        for msg in message_ids:
            filename = msg['filename']
            file_id = msg['file_id']
            
            # Verificar si el archivo ya existe localmente
            local_path = os.path.join(UPLOAD_FOLDER, filename)
            if not os.path.exists(local_path):
                if download_telegram_file(file_id, filename):
                    # Actualizar metadatos en base de datos
                    cuba_time = datetime.now(cuba_timezone)
                    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
                    save_upload(filename, timestamp)
                    downloaded_count += 1
                    print(f"✅ Descargado desde ID guardado: {filename}")
        
        return downloaded_count
    except Exception as e:
        print(f"Error descargando desde IDs guardados: {e}")
        return 0

# FUNCIONES EXISTENTES MODIFICADAS

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
    """Envía un archivo/documento a Telegram y guarda el ID del mensaje"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as file:
            files = {'document': (filename, file)}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
            response = requests.post(url, files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json().get('result', {})
            message_id = result.get('message_id')
            file_id = result.get('document', {}).get('file_id')
            
            # Guardar el ID del mensaje en la base de datos
            if message_id and file_id:
                save_or_replace_telegram_message(message_id, file_id, filename)
            
            return True
        return False
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
    # Primero restaurar desde IDs guardados
    restored_from_ids = download_from_saved_message_ids()
    
    # Luego restaurar listas desde Telegram (búsqueda normal)
    restored_from_search = restore_lists_from_telegram()
    
    total_restored = restored_from_ids + restored_from_search
    
    if total_restored > 0:
        cuba_time = datetime.now(cuba_timezone)
        timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Obtener estadísticas actuales
        uploads_count = len(get_uploads())
        
        telegram_message = f"🔄 <b>Restauración Completa</b>\n\n📊 Desde IDs guardados: {restored_from_ids}\n📊 Desde búsqueda: {restored_from_search}\n📊 Total restauradas: {total_restored}\n📊 Total listas en sistema: {uploads_count}\n🕐 Hora: {timestamp}"
        send_telegram_message(telegram_message)
    
    return total_restored

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
def index():
    # ... (código HTML existente) ...
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maquiavelo: Filosofía del Poder</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700&family=Crimson+Text:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Crimson Text', serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d3436 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow-x: hidden;
            padding: 20px;
            color: #f5f5f5;
        }
        
        .container {
            text-align: center;
            background: rgba(25, 25, 25, 0.9);
            border-radius: 20px;
            padding: 60px 40px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(189, 147, 87, 0.3);
            position: relative;
            overflow: hidden;
            max-width: 900px;
            width: 100%;
            border: 2px solid rgba(189, 147, 87, 0.5);
            animation: fadeIn 1.5s ease-out;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
        
        .crown-icon {
            font-size: 6rem;
            color: #bd9357;
            margin-bottom: 20px;
            animation: crownGlow 4s infinite alternate;
            text-shadow: 0 0 20px rgba(189, 147, 87, 0.7);
        }
        
        @keyframes crownGlow {
            0% { text-shadow: 0 0 10px rgba(189, 147, 87, 0.5); transform: translateY(0); }
            100% { text-shadow: 0 0 30px rgba(189, 147, 87, 0.9), 0 0 40px rgba(189, 147, 87, 0.5); transform: translateY(-10px); }
        }
        
        .title {
            font-family: 'Cinzel', serif;
            color: #bd9357;
            font-size: 3.8rem;
            margin-bottom: 15px;
            line-height: 1.1;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            position: relative;
            display: inline-block;
        }
        
        .title::before, .title::after {
            content: '✦';
            color: #bd9357;
            margin: 0 20px;
            opacity: 0.7;
        }
        
        .quote-container {
            background: rgba(40, 40, 40, 0.8);
            border-radius: 15px;
            padding: 40px 30px;
            margin: 30px 0;
            border-left: 5px solid #bd9357;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5);
            position: relative;
            overflow: hidden;
        }
        
        .quote-container::before {
            content: '"';
            position: absolute;
            top: 10px;
            left: 20px;
            font-size: 8rem;
            color: rgba(189, 147, 87, 0.2);
            font-family: Georgia, serif;
            line-height: 1;
        }
        
        .quote {
            font-size: 2.8rem;
            color: #f5f5f5;
            line-height: 1.4;
            font-weight: 700;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
            position: relative;
            z-index: 1;
        }
        
        .quote-highlight {
            color: #bd9357;
            font-weight: 800;
            text-shadow: 0 0 10px rgba(189, 147, 87, 0.5);
        }
        
        .author {
            font-size: 2rem;
            color: #aaa;
            margin-top: 30px;
            font-style: italic;
            letter-spacing: 1px;
            position: relative;
            display: inline-block;
        }
        
        .author::before {
            content: '';
            position: absolute;
            width: 100px;
            height: 2px;
            background: linear-gradient(90deg, transparent, #bd9357, transparent);
            top: -15px;
            left: 50%;
            transform: translateX(-50%);
        }
        
        .philosophy-note {
            font-size: 1.3rem;
            color: #999;
            margin-top: 30px;
            line-height: 1.6;
            max-width: 700px;
            margin-left: auto;
            margin-right: auto;
            padding: 15px;
            background: rgba(30, 30, 30, 0.7);
            border-radius: 10px;
            border: 1px solid rgba(189, 147, 87, 0.2);
        }
        
        /* Elementos decorativos */
        .decorative-element {
            position: absolute;
            font-size: 2.5rem;
            color: rgba(189, 147, 87, 0.2);
            z-index: 0;
            animation: float 25s infinite linear;
        }
        
        .decorative-element:nth-child(1) {
            top: 10%;
            left: 5%;
            animation-delay: 0s;
        }
        
        .decorative-element:nth-child(2) {
            top: 15%;
            right: 7%;
            animation-delay: -5s;
        }
        
        .decorative-element:nth-child(3) {
            bottom: 20%;
            left: 8%;
            animation-delay: -10s;
        }
        
        .decorative-element:nth-child(4) {
            bottom: 15%;
            right: 5%;
            animation-delay: -15s;
        }
        
        @keyframes float {
            0% { transform: translate(0, 0) rotate(0deg); }
            100% { transform: translate(100px, 100px) rotate(360deg); }
        }
        
        /* Líneas divisorias decorativas */
        .divider {
            height: 1px;
            background: linear-gradient(90deg, transparent, #bd9357, transparent);
            margin: 25px auto;
            width: 80%;
            opacity: 0.5;
        }
        
        /* Fondo con textura de pergamino */
        .container::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect width="100" height="100" fill="none" stroke="%23bd9357" stroke-width="0.5" opacity="0.1" stroke-dasharray="5,5"/></svg>');
            z-index: -1;
            opacity: 0.3;
        }
        
        /* Efecto de velas parpadeantes */
        .candle {
            position: absolute;
            bottom: 20px;
            width: 40px;
            height: 60px;
            background: linear-gradient(to bottom, #8b4513 0%, #a0522d 100%);
            border-radius: 5px;
            z-index: -1;
        }
        
        .candle::before {
            content: '';
            position: absolute;
            top: -15px;
            left: 15px;
            width: 10px;
            height: 20px;
            background: #ff9900;
            border-radius: 50% 50% 20% 20%;
            animation: flicker 3s infinite alternate;
            box-shadow: 0 0 20px #ff9900, 0 0 40px #ff9900;
        }
        
        .candle.left {
            left: 30px;
        }
        
        .candle.right {
            right: 30px;
        }
        
        @keyframes flicker {
            0%, 100% { transform: scale(1) translateY(0); opacity: 0.9; }
            50% { transform: scale(1.1) translateY(-5px); opacity: 1; }
        }
        
        /* Efecto de sangre goteando */
        .blood-drop {
            position: absolute;
            width: 8px;
            height: 15px;
            background: #8b0000;
            border-radius: 0 0 4px 4px;
            animation: drip 8s infinite linear;
            opacity: 0.6;
        }
        
        .blood-drop:nth-child(7) {
            top: 15%;
            left: 15%;
            animation-delay: 0s;
        }
        
        .blood-drop:nth-child(8) {
            top: 25%;
            right: 20%;
            animation-delay: -2s;
        }
        
        .blood-drop:nth-child(9) {
            bottom: 30%;
            left: 20%;
            animation-delay: -4s;
        }
        
        .blood-drop:nth-child(10) {
            bottom: 20%;
            right: 15%;
            animation-delay: -6s;
        }
        
        @keyframes drip {
            0% { transform: translateY(-100px); opacity: 0; }
            10% { opacity: 0.7; }
            90% { opacity: 0.7; }
            100% { transform: translateY(300px); opacity: 0; }
        }
        
        /* Responsive */
        @media (max-width: 900px) {
            .title { font-size: 3rem; }
            .quote { font-size: 2.2rem; }
            .crown-icon { font-size: 5rem; }
            .container { padding: 50px 30px; }
        }
        
        @media (max-width: 600px) {
            .title { font-size: 2.3rem; }
            .quote { font-size: 1.8rem; }
            .crown-icon { font-size: 4rem; }
            .author { font-size: 1.6rem; }
            .container { padding: 40px 20px; }
            .quote-container { padding: 30px 20px; }
        }
        
        @media (max-width: 400px) {
            .title { font-size: 1.9rem; }
            .quote { font-size: 1.5rem; }
            .title::before, .title::after { margin: 0 10px; }
        }
    </style>
</head>
<body>
    <div class="decorative-element">♔</div>
    <div class="decorative-element">⚔</div>
    <div class="decorative-element">🛡</div>
    <div class="decorative-element">🏛</div>
    
    <div class="blood-drop"></div>
    <div class="blood-drop"></div>
    <div class="blood-drop"></div>
    <div class="blood-drop"></div>
    
    <div class="candle left"></div>
    <div class="candle right"></div>
    
    <div class="container">
        <div class="crown-icon">
            <i class="fas fa-crown"></i>
        </div>
        
        <h1 class="title">Maquiavelo</h1>
        
        <div class="divider"></div>
        
        <div class="quote-container">
            <div class="quote">
                "Es mejor ser <span class="quote-highlight">temido</span> que <span class="quote-highlight">amado</span>,<br>si no se puede ser ambas cosas."
            </div>
        </div>
        
        <div class="divider"></div>
        
        <div class="author">— Nicolás Maquiavelo, El Príncipe (1532)</div>
        
        <div class="philosophy-note">
            <i class="fas fa-quote-left" style="color: #bd9357; margin-right: 8px;"></i>
            Según Maquiavelo, el miedo es un instrumento de control más confiable que el amor, 
            pues los hombres dudan menos en ofender a alguien que se hace amar que a alguien que se hace temer.
            <i class="fas fa-quote-right" style="color: #bd9357; margin-left: 8px;"></i>
        </div>
    </div>

    <script>
        // Efecto de escritura dramática para la cita
        const quoteElement = document.querySelector('.quote');
        const originalQuote = `"Es mejor ser <span class="quote-highlight">temido</span> que <span class="quote-highlight">amado</span>,<br>si no se puede ser ambas cosas."`;
        quoteElement.innerHTML = '';
        
        // Separar las partes para el efecto de escritura
        const parts = [
            '"Es mejor ser ',
            '<span class="quote-highlight">temido</span>',
            ' que ',
            '<span class="quote-highlight">amado</span>',
            ',<br>si no se puede ser ambas cosas."'
        ];
        
        let partIndex = 0;
        let charIndex = 0;
        let isTag = false;
        let currentContent = '';
        
        function typeWriter() {
            if (partIndex < parts.length) {
                const currentPart = parts[partIndex];
                
                // Si es una etiqueta HTML, agregar directamente
                if (currentPart.includes('span')) {
                    quoteElement.innerHTML += currentPart;
                    partIndex++;
                    setTimeout(typeWriter, 300); // Pausa antes de continuar
                    return;
                }
                
                // Si no es una etiqueta, escribir carácter por carácter
                if (charIndex < currentPart.length) {
                    currentContent += currentPart.charAt(charIndex);
                    quoteElement.innerHTML = currentContent + (partIndex < parts.length - 1 ? parts.slice(partIndex + 1).join('') : '');
                    charIndex++;
                    setTimeout(typeWriter, 50);
                } else {
                    partIndex++;
                    charIndex = 0;
                    setTimeout(typeWriter, 200); // Pausa entre partes
                }
            }
        }
        
        // Iniciar efecto de escritura después de un breve retraso
        setTimeout(typeWriter, 800);
        
        // Efecto de latido para las palabras destacadas
        setInterval(() => {
            const highlightedWords = document.querySelectorAll('.quote-highlight');
            highlightedWords.forEach(word => {
                word.style.transform = 'scale(1.1)';
                word.style.textShadow = '0 0 15px rgba(189, 147, 87, 0.8)';
                
                setTimeout(() => {
                    word.style.transform = 'scale(1)';
                    word.style.textShadow = '0 0 10px rgba(189, 147, 87, 0.5)';
                }, 500);
            });
        }, 3000);
        
        // Efecto de parpadeo en las velas
        const candles = document.querySelectorAll('.candle');
        setInterval(() => {
            candles.forEach(candle => {
                const flame = candle.querySelector(':before') || candle;
                // Aumentar aleatoriamente el brillo de la llama
                const randomBrightness = 0.8 + Math.random() * 0.4;
                candle.style.setProperty('--flame-brightness', randomBrightness);
            });
        }, 300);
        
        // Efecto de sonido ambiental (solo visual, no audio real)
        const container = document.querySelector('.container');
        setInterval(() => {
            // Simular un ligero temblor en momentos aleatorios
            if (Math.random() > 0.7) {
                container.style.transform = 'translateX(3px)';
                setTimeout(() => {
                    container.style.transform = 'translateX(-3px)';
                }, 50);
                setTimeout(() => {
                    container.style.transform = 'translateX(0)';
                }, 100);
            }
        }, 3000);
        
        // Cambiar color de fondo sutilmente
        const backgrounds = [
            'linear-gradient(135deg, #1a1a1a 0%, #2d3436 100%)',
            'linear-gradient(135deg, #1a1a1a 0%, #2c3e50 100%)',
            'linear-gradient(135deg, #1a1a1a 0%, #34495e 100%)',
            'linear-gradient(135deg, #1a1a1a 0%, #2d3436 100%)'
        ];
        
        let bgIndex = 0;
        setInterval(() => {
            document.body.style.background = backgrounds[bgIndex];
            bgIndex = (bgIndex + 1) % backgrounds.length;
        }, 10000);
    </script>
</body>
</html>"""

# ... (todos los endpoints existentes se mantienen igual) ...

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
    
    # Validación de nombre y horario
    is_valid, message = validate_filename(filename)
    if not is_valid:
        log_access(username, '/upload', f'attempted upload (invalid filename: {message})')
        return f"Error: {message}", 205
    
    # 🔄 REEMPLAZO: Si el archivo ya existe, eliminarlo localmente
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"🗑️ Archivo local reemplazado: {filename}")
    
    # Guardar el nuevo archivo
    file.save(file_path)
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Guardar en base de datos (uploads)
    save_upload(filename, timestamp)
    
    # 📤 Subir a Telegram con reemplazo automático
    caption = f"📁 LISTA: {filename}\n🕐 {timestamp}\n✅ Subida por: {username}"
    send_telegram_document(file_path, filename, caption)
    
    # 🔄 CREAR RESPALDO AUTOMÁTICO
    create_backup()
    
    # Notificación de subida exitosa
    telegram_message = f"📤 <b>Lista {'Reemplazada' if os.path.exists(file_path) else 'Subida'}</b>\n\n👤 Usuario: {username}\n📄 Archivo: {filename}\n🕐 Hora: {timestamp}"
    send_telegram_message(telegram_message)
    
    log_access("Kilito", '/upload', f'Lista {"reemplazada" if os.path.exists(file_path) else "agregada"} correctamente: {filename}')
    
    return f"Lista {'agregada' if os.path.exists(file_path) else 'agregada'} correctamente: {filename}", 200

@app.route('/hora')
def get_stkffkatus():
    cuba_time = datetime.now(cuba_timezone)
    time = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    return time
    
@app.route('/lastupdatekilo')
def uplast():
    return "vdataantiloqueraV2.9"
    
@app.route('/update')
def ukdla():
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Actualización Requerida</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Nunito', sans-serif;
            background: linear-gradient(135deg, #ff6b6b 0%, #4ecdc4 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
            padding: 20px;
            animation: gradientShift 8s infinite alternate;
        }
        
        @keyframes gradientShift {
            0% { background: linear-gradient(135deg, #ff6b6b 0%, #4ecdc4 100%); }
            50% { background: linear-gradient(135deg, #556270 0%, #ff6b6b 100%); }
            100% { background: linear-gradient(135deg, #4ecdc4 0%, #556270 100%); }
        }
        
        .container {
            text-align: center;
            background-color: rgba(255, 255, 255, 0.95);
            border-radius: 30px;
            padding: 60px 40px;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
            position: relative;
            overflow: hidden;
            max-width: 700px;
            width: 100%;
            animation: popIn 1s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        
        @keyframes popIn {
            0% { opacity: 0; transform: scale(0.5); }
            100% { opacity: 1; transform: scale(1); }
        }
        
        .main-icon {
            font-size: 8rem;
            color: #ff6b6b;
            margin-bottom: 30px;
            animation: pulse 2s infinite alternate, rotate 20s infinite linear;
            display: inline-block;
        }
        
        @keyframes pulse {
            0% { transform: scale(1); }
            100% { transform: scale(1.1); }
        }
        
        @keyframes rotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        h1 {
            font-family: 'Fredoka One', cursive;
            color: #333;
            font-size: 3.5rem;
            margin-bottom: 20px;
            line-height: 1.2;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
        }
        
        .message {
            font-size: 2.2rem;
            color: #444;
            line-height: 1.4;
            padding: 0 10px;
            font-weight: 700;
            position: relative;
            display: inline-block;
        }
        
        .message::after {
            content: '';
            position: absolute;
            width: 100%;
            height: 10px;
            background: rgba(78, 205, 196, 0.3);
            bottom: 5px;
            left: 0;
            z-index: -1;
            border-radius: 5px;
            animation: underlineWidth 3s infinite alternate;
        }
        
        @keyframes underlineWidth {
            0% { width: 20%; left: 40%; }
            100% { width: 100%; left: 0; }
        }
        
        /* Elementos decorativos flotantes */
        .floating-icon {
            position: absolute;
            font-size: 2.5rem;
            opacity: 0.7;
            z-index: -1;
            animation: floatAround 15s infinite linear;
        }
        
        .floating-icon:nth-child(1) {
            top: 10%;
            left: 5%;
            color: #ff6b6b;
            animation-delay: 0s;
        }
        
        .floating-icon:nth-child(2) {
            top: 15%;
            right: 7%;
            color: #4ecdc4;
            animation-delay: -3s;
        }
        
        .floating-icon:nth-child(3) {
            bottom: 20%;
            left: 8%;
            color: #556270;
            animation-delay: -6s;
        }
        
        .floating-icon:nth-child(4) {
            bottom: 15%;
            right: 5%;
            color: #ff9a76;
            animation-delay: -9s;
        }
        
        @keyframes floatAround {
            0% { transform: translate(0, 0) rotate(0deg) scale(1); }
            25% { transform: translate(100px, 50px) rotate(90deg) scale(1.2); }
            50% { transform: translate(50px, 100px) rotate(180deg) scale(1); }
            75% { transform: translate(-50px, 50px) rotate(270deg) scale(1.2); }
            100% { transform: translate(0, 0) rotate(360deg) scale(1); }
        }
        
        /* Efecto de texto brillante */
        .shining-text {
            position: relative;
            display: inline-block;
        }
        
        .shining-text::before {
            content: attr(data-text);
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            color: #ff6b6b;
            animation: shine 3s infinite;
            overflow: hidden;
        }
        
        @keyframes shine {
            0%, 100% { clip-path: inset(0 100% 0 0); }
            50% { clip-path: inset(0 0 0 0); }
        }
        
        /* Puntos suspensivos animados */
        .dots {
            display: inline-block;
            width: 30px;
            text-align: left;
        }
        
        .dots::after {
            content: '...';
            animation: dots 2s infinite;
        }
        
        @keyframes dots {
            0%, 20% { content: '.'; }
            40% { content: '..'; }
            60%, 100% { content: '...'; }
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            h1 { font-size: 2.8rem; }
            .message { font-size: 1.8rem; }
            .main-icon { font-size: 6rem; }
            .container { padding: 40px 25px; }
        }
        
        @media (max-width: 480px) {
            h1 { font-size: 2.2rem; }
            .message { font-size: 1.5rem; }
            .main-icon { font-size: 5rem; }
            .container { padding: 30px 20px; }
        }
    </style>
</head>
<body>
    <div class="floating-icon"><i class="fas fa-cog"></i></div>
    <div class="floating-icon"><i class="fas fa-exclamation-triangle"></i></div>
    <div class="floating-icon"><i class="fas fa-sync-alt"></i></div>
    <div class="floating-icon"><i class="fas fa-tools"></i></div>
    
    <div class="container">
        <div class="main-icon">
            <i class="fas fa-exclamation-circle"></i>
        </div>
        
        <h1>Actualización <span class="shining-text" data-text="Requerida">Requerida</span></h1>
        
        <p class="message">
            Contacta con el administrador<span class="dots"></span>
        </p>
    </div>

    <script>
        // Efecto de escritura para el mensaje
        const message = document.querySelector('.message');
        const originalText = "Contacta con el administrador";
        message.innerHTML = '';
        
        let charIndex = 0;
        function typeMessage() {
            if (charIndex < originalText.length) {
                message.innerHTML += originalText.charAt(charIndex);
                charIndex++;
                setTimeout(typeMessage, 100);
            }
        }
        
        // Iniciar efecto de escritura después de un breve retraso
        setTimeout(typeMessage, 800);
        
        // Cambiar aleatoriamente el color del icono principal
        const icon = document.querySelector('.main-icon');
        const colors = ['#ff6b6b', '#4ecdc4', '#556270', '#ff9a76', '#ffd166'];
        
        setInterval(() => {
            const randomColor = colors[Math.floor(Math.random() * colors.length)];
            icon.style.color = randomColor;
        }, 2000);
        
        // Efecto de vibración ocasional en el contenedor
        setInterval(() => {
            container.style.animation = 'none';
            setTimeout(() => {
                container.style.animation = 'popIn 1s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
            }, 10);
            
            // Añadir efecto de sacudida
            container.style.transform = 'translateX(10px)';
            setTimeout(() => {
                container.style.transform = 'translateX(-10px)';
            }, 50);
            setTimeout(() => {
                container.style.transform = 'translateX(0)';
            }, 100);
        }, 8000);
    </script>
</body>
</html>""" 
# ENDPOINTS NUEVOS

@app.route('/telegram/ids', methods=['GET'])
@auth.login_required
def view_telegram_ids():
    """Muestra los IDs de mensajes guardados"""
    ids = get_last_telegram_message_ids(10)
    
    if not ids:
        return jsonify({"message": "No hay IDs guardados", "count": 0}), 200
    
    return jsonify({
        "count": len(ids),
        "ids": ids
    }), 200

@app.route('/telegram/force_update', methods=['POST'])
@auth.login_required
def force_update_telegram_ids():
    """Fuerza la actualización de IDs desde Telegram"""
    username = auth.current_user()
    
    try:
        messages = get_telegram_messages(limit=100)
        saved_count = 0
        
        for message in messages:
            if 'message' in message and 'document' in message['message']:
                document = message['message']['document']
                file_name = document.get('file_name', '')
                message_id = message['message'].get('message_id')
                file_id = document.get('file_id')
                
                if is_valid_list_file(file_name) and message_id and file_id:
                    if save_or_replace_telegram_message(message_id, file_id, file_name):
                        saved_count += 1
        
        log_access(username, '/telegram/force_update', f'Actualizados {saved_count} IDs')
        
        return jsonify({
            "status": "success",
            "message": f"Actualizados {saved_count} IDs de mensajes",
            "saved_count": saved_count
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500

@app.route('/telegram/clean_old', methods=['POST'])
@auth.login_required
def clean_old_telegram_messages():
    """Elimina mensajes antiguos de Telegram que no están en los últimos 10"""
    username = auth.current_user()
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Obtener todos los IDs guardados
            cursor.execute('SELECT message_id FROM telegram_message_ids ORDER BY created_at DESC')
            all_ids = [row['message_id'] for row in cursor.fetchall()]
            
            # Mantener solo los últimos 10
            if len(all_ids) > 10:
                ids_to_keep = all_ids[:10]
                ids_to_delete = all_ids[10:]
                
                for msg_id in ids_to_delete:
                    delete_telegram_message(msg_id)
                
                # Eliminar de la base de datos
                cursor.execute('''
                    DELETE FROM telegram_message_ids 
                    WHERE message_id NOT IN ({})
                '''.format(','.join(['?']*len(ids_to_keep))), ids_to_keep)
                
                conn.commit()
                
                deleted_count = len(ids_to_delete)
                log_access(username, '/telegram/clean_old', f'Eliminados {deleted_count} mensajes antiguos')
                
                return jsonify({
                    "status": "success",
                    "message": f"Eliminados {deleted_count} mensajes antiguos",
                    "deleted_count": deleted_count
                }), 200
        
        return jsonify({
            "status": "success",
            "message": "No hay mensajes antiguos para eliminar",
            "deleted_count": 0
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500

# Enviar mensaje de inicio del servidor
def send_startup_message():
    """Envía un mensaje cuando el servidor se inicia"""
    time.sleep(5)  # Esperar a que el servidor esté completamente listo
    
    # Inicializar base de datos
    init_database()
    
    # Restaurar listas desde Telegram (incluye IDs guardados)
    restored_count = restore_from_backup()
    
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    
    # Obtener estadísticas actuales
    uploads_count = len(get_uploads())
    telegram_ids_count = len(get_last_telegram_message_ids(10))
    
    startup_message = f"🚀 <b>Servidor Iniciado con Reemplazo Automático</b>\n\n🕐 Hora: {timestamp}\n✅ Listas restauradas: {restored_count}\n📊 Listas en sistema: {uploads_count}\n🔢 IDs Telegram guardados: {telegram_ids_count}\n🔄 Sistema: Reemplazo activo - Solo últimos 10"
    send_telegram_message(startup_message)

# Inicializar servicios al arrancar
def initialize_services():
    """Inicializa todos los servicios al arrancar la aplicación"""
    # Mensaje de inicio
    startup_thread = threading.Thread(target=send_startup_message, daemon=True)
    startup_thread.start()
    cuba_time = datetime.now(cuba_timezone)
    timestamp = cuba_time.strftime('%Y-%m-%d %I:%M:%S %p')
    print(f"{timestamp} - Sistema de reemplazo activado - Solo últimos 10 IDs")

# Inicializar servicios cuando se importa el módulo
initialize_services()
