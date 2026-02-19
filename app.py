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
def index():
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nicolás Maquiavelo - Frases y Pensamientos</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700&family=Raleway:wght@300;400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Raleway', sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f8f5f0;
            background-image: linear-gradient(to bottom, rgba(248, 245, 240, 0.9), rgba(248, 245, 240, 0.9)), url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect fill="%23d4b483" opacity="0.1" width="100" height="100"/><path fill="%238a6d3b" opacity="0.1" d="M20,20 L80,20 L80,80 L20,80 Z M25,25 L75,25 L75,75 L25,75 Z"/></svg>');
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header styles */
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 2px solid #8a6d3b;
            margin-bottom: 40px;
        }
        
        h1 {
            font-family: 'Cinzel', serif;
            font-size: 3.2rem;
            color: #5c4628;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.1);
            margin-bottom: 10px;
            letter-spacing: 2px;
        }
        
        .subtitle {
            font-size: 1.2rem;
            color: #8a6d3b;
            font-style: italic;
            margin-bottom: 20px;
        }
        
        /* Main content */
        .main-content {
            display: flex;
            flex-wrap: wrap;
            gap: 30px;
            margin-bottom: 40px;
        }
        
        .portrait-section {
            flex: 1;
            min-width: 300px;
            text-align: center;
        }
        
        .portrait {
            width: 100%;
            max-width: 400px;
            border-radius: 10px;
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.15);
            border: 8px solid #d4b483;
            margin-bottom: 20px;
            transition: transform 0.3s ease;
        }
        
        .portrait:hover {
            transform: scale(1.02);
        }
        
        .portrait-caption {
            font-style: italic;
            color: #666;
            font-size: 0.95rem;
        }
        
        .quotes-section {
            flex: 2;
            min-width: 300px;
        }
        
        .section-title {
            font-family: 'Cinzel', serif;
            font-size: 2rem;
            color: #5c4628;
            border-bottom: 1px solid #d4b483;
            padding-bottom: 10px;
            margin-bottom: 25px;
        }
        
        .quote-card {
            background-color: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 25px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
            border-left: 5px solid #8a6d3b;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .quote-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
        }
        
        .quote-text {
            font-size: 1.3rem;
            color: #444;
            font-style: italic;
            margin-bottom: 15px;
            line-height: 1.5;
        }
        
        .quote-reference {
            color: #8a6d3b;
            font-weight: 600;
            text-align: right;
            font-size: 0.95rem;
        }
        
        .quote-icon {
            color: #d4b483;
            font-size: 1.5rem;
            margin-right: 10px;
            vertical-align: middle;
        }
        
        /* Timeline section */
        .timeline-section {
            margin-bottom: 40px;
        }
        
        .timeline {
            position: relative;
            max-width: 800px;
            margin: 0 auto;
        }
        
        .timeline::before {
            content: '';
            position: absolute;
            width: 3px;
            background-color: #8a6d3b;
            top: 0;
            bottom: 0;
            left: 50%;
            margin-left: -1.5px;
        }
        
        .timeline-item {
            padding: 10px 40px;
            position: relative;
            width: 50%;
            box-sizing: border-box;
            margin-bottom: 30px;
        }
        
        .timeline-item:nth-child(odd) {
            left: 0;
        }
        
        .timeline-item:nth-child(even) {
            left: 50%;
        }
        
        .timeline-content {
            background-color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
            position: relative;
        }
        
        .timeline-year {
            font-family: 'Cinzel', serif;
            font-weight: 700;
            color: #8a6d3b;
            font-size: 1.2rem;
            margin-bottom: 10px;
        }
        
        .timeline-dot {
            position: absolute;
            width: 20px;
            height: 20px;
            right: -10px;
            background-color: #8a6d3b;
            border-radius: 50%;
            top: 15px;
        }
        
        .timeline-item:nth-child(even) .timeline-dot {
            left: -10px;
        }
        
        /* Footer */
        footer {
            text-align: center;
            padding: 25px;
            background-color: #5c4628;
            color: #f8f5f0;
            border-radius: 10px 10px 0 0;
            margin-top: 40px;
        }
        
        .footer-text {
            margin-bottom: 15px;
        }
        
        .quote-button {
            background-color: #8a6d3b;
            color: white;
            border: none;
            padding: 12px 25px;
            font-size: 1.1rem;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s ease;
            font-family: 'Cinzel', serif;
            letter-spacing: 1px;
            margin-top: 15px;
        }
        
        .quote-button:hover {
            background-color: #5c4628;
        }
        
        .social-icons {
            margin-top: 15px;
        }
        
        .social-icons a {
            color: #f8f5f0;
            font-size: 1.2rem;
            margin: 0 10px;
            transition: color 0.3s ease;
        }
        
        .social-icons a:hover {
            color: #d4b483;
        }
        
        /* Responsive adjustments */
        @media (max-width: 768px) {
            h1 {
                font-size: 2.5rem;
            }
            
            .timeline::before {
                left: 31px;
            }
            
            .timeline-item {
                width: 100%;
                padding-left: 70px;
                padding-right: 25px;
            }
            
            .timeline-item:nth-child(even) {
                left: 0;
            }
            
            .timeline-dot {
                left: 21px !important;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Nicolás Maquiavelo</h1>
            <p class="subtitle">Diplomático, filósofo político y escritor italiano del Renacimiento</p>
        </header>
        
        <main class="main-content">
            <section class="portrait-section">
                <h2 class="section-title">Retrato</h2>
                <div class="portrait-container">
                    <!-- Imagen de Maquiavelo generada con CSS placeholder -->
                    <div class="portrait" id="maquiaveloPortrait"></div>
                    <p class="portrait-caption">Retrato de Nicolás Maquiavelo (1469-1527)</p>
                </div>
                <div class="portrait-info">
                    <h3 class="section-title" style="font-size: 1.5rem; margin-top: 20px;">Biografía Resumida</h3>
                    <p>Nicolás Maquiavelo fue un diplomático, funcionario público, filósofo político y escritor italiano del Renacimiento. Es considerado el fundador de la filosofía política moderna, y su obra más famosa, "El Príncipe", escrita alrededor de 1513, se convirtió en un tratado fundamental sobre el ejercicio del poder.</p>
                </div>
            </section>
            
            <section class="quotes-section">
                <h2 class="section-title">Frases Célebres</h2>
                
                <div class="quote-card">
                    <i class="fas fa-quote-left quote-icon"></i>
                    <p class="quote-text">"Es mejor ser temido que amado, si no se puede ser ambas cosas."</p>
                    <p class="quote-reference">— De "El Príncipe", Capítulo XVII</p>
                </div>
                
                <div class="quote-card">
                    <i class="fas fa-quote-left quote-icon"></i>
                    <p class="quote-text">"El fin justifica los medios."</p>
                    <p class="quote-reference">— Atribuida a Maquiavelo, aunque no aparece textualmente en sus obras</p>
                </div>
                
                <div class="quote-card">
                    <i class="fas fa-quote-left quote-icon"></i>
                    <p class="quote-text">"Todos los profetas armados triunfaron, y los desarmados fueron destruidos."</p>
                    <p class="quote-reference">— De "El Príncipe", Capítulo VI</p>
                </div>
                
                <div class="quote-card">
                    <i class="fas fa-quote-left quote-icon"></i>
                    <p class="quote-text">"Los hombres ofenden antes al que aman que al que temen."</p>
                    <p class="quote-reference">— De "El Príncipe", Capítulo XVII</p>
                </div>
                
                <div class="quote-card">
                    <i class="fas fa-quote-left quote-icon"></i>
                    <p class="quote-text">"La principal base de todos los estados son las buenas leyes y las buenas armas."</p>
                    <p class="quote-reference">— De "El Príncipe", Capítulo XII</p>
                </div>
            </section>
        </main>
        
        <section class="timeline-section">
            <h2 class="section-title">Línea de Tiempo</h2>
            <div class="timeline">
                <div class="timeline-item">
                    <div class="timeline-content">
                        <div class="timeline-year">1469</div>
                        <p>Nacimiento de Nicolás Maquiavelo en Florencia, Italia.</p>
                    </div>
                    <div class="timeline-dot"></div>
                </div>
                
                <div class="timeline-item">
                    <div class="timeline-content">
                        <div class="timeline-year">1498</div>
                        <p>Es nombrado secretario de la Segunda Cancillería de la República de Florencia.</p>
                    </div>
                    <div class="timeline-dot"></div>
                </div>
                
                <div class="timeline-item">
                    <div class="timeline-content">
                        <div class="timeline-year">1513</div>
                        <p>Escribe su obra más famosa, "El Príncipe", dedicada a Lorenzo de Médici.</p>
                    </div>
                    <div class="timeline-dot"></div>
                </div>
                
                <div class="timeline-item">
                    <div class="timeline-content">
                        <div class="timeline-year">1520</div>
                        <p>Escribe "El arte de la guerra", su única obra política publicada en vida.</p>
                    </div>
                    <div class="timeline-dot"></div>
                </div>
                
                <div class="timeline-item">
                    <div class="timeline-content">
                        <div class="timeline-year">1527</div>
                        <p>Muerte de Maquiavelo en Florencia a los 58 años.</p>
                    </div>
                    <div class="timeline-dot"></div>
                </div>
            </div>
        </section>
        
        <footer>
            <p class="footer-text">"Maquiavelo no inventó la maquiavelismo, solo lo describió"</p>
            <button class="quote-button" id="newQuoteButton">Mostrar otra frase</button>
            <div class="social-icons">
                <a href="#"><i class="fab fa-twitter"></i></a>
                <a href="#"><i class="fab fa-facebook"></i></a>
                <a href="#"><i class="fab fa-instagram"></i></a>
                <a href="#"><i class="fas fa-share-alt"></i></a>
            </div>
            <p style="margin-top: 20px; font-size: 0.9rem;">© 2023 - Página dedicada a Nicolás Maquiavelo</p>
        </footer>
    </div>
    
    <script>
        // Datos de frases adicionales
        const additionalQuotes = [
            {
                text: "Nunca fue discreto dejar ganar a uno para que otro pierda.",
                reference: "— De 'El Príncipe'"
            },
            {
                text: "Donde hay buena disciplina, tiene que haber buen ejército.",
                reference: "— De 'El arte de la guerra'"
            },
            {
                text: "Aquellos que consiguen ser príncipes gracias a sus virtudes, se convierten en príncipes con dificultad, pero se mantienen con facilidad.",
                reference: "— De 'El Príncipe'"
            },
            {
                text: "Los hombres cambian de amores con más facilidad y ligereza que de miedos.",
                reference: "— De 'Discursos sobre la primera década de Tito Livio'"
            },
            {
                text: "El que quiere ser rico en un día, será ahorcado en un año.",
                reference: "— De 'El Príncipe'"
            },
            {
                text: "La naturaleza de los pueblos es casi siempre la misma; y es diversa y variable la de los gobiernos.",
                reference: "— De 'Discursos sobre la primera década de Tito Livio'"
            }
        ];
        
        // Frases iniciales
        const initialQuotes = [
            {
                text: "Es mejor ser temido que amado, si no se puede ser ambas cosas.",
                reference: "— De 'El Príncipe', Capítulo XVII"
            },
            {
                text: "El fin justifica los medios.",
                reference: "— Atribuida a Maquiavelo, aunque no aparece textualmente en sus obras"
            },
            {
                text: "Todos los profetas armados triunfaron, y los desarmados fueron destruidos.",
                reference: "— De 'El Príncipe', Capítulo VI"
            },
            {
                text: "Los hombres ofenden antes al que aman que al que temen.",
                reference: "— De 'El Príncipe', Capítulo XVII"
            },
            {
                text: "La principal base de todos los estados son las buenas leyes y las buenas armas.",
                reference: "— De 'El Príncipe', Capítulo XII"
            }
        ];
        
        // Combinar todas las frases
        const allQuotes = [...initialQuotes, ...additionalQuotes];
        
        // Elementos DOM
        const quoteButton = document.getElementById('newQuoteButton');
        const quoteCards = document.querySelectorAll('.quote-card');
        
        // Crear imagen de Maquiavelo con CSS
        const portrait = document.getElementById('maquiaveloPortrait');
        portrait.innerHTML = `
            <svg width="100%" height="100%" viewBox="0 0 400 500" xmlns="http://www.w3.org/2000/svg">
                <rect width="400" height="500" fill="#d4b483"/>
                <circle cx="200" cy="150" r="80" fill="#8a6d3b"/>
                <rect x="120" y="230" width="160" height="200" fill="#5c4628"/>
                <path d="M 120 230 Q 200 180 280 230" fill="none" stroke="#5c4628" stroke-width="4"/>
                <ellipse cx="160" cy="120" rx="20" ry="30" fill="#f8f5f0"/>
                <ellipse cx="240" cy="120" rx="20" ry="30" fill="#f8f5f0"/>
                <circle cx="160" cy="110" r="8" fill="#333"/>
                <circle cx="240" cy="110" r="8" fill="#333"/>
                <path d="M 170 160 Q 200 180 230 160" fill="none" stroke="#333" stroke-width="2"/>
                <rect x="170" y="250" width="60" height="80" fill="#333"/>
                <path d="M 140 430 L 260 430 L 250 480 L 150 480 Z" fill="#333"/>
            </svg>
        `;
        
        // Función para cambiar una frase aleatoriamente
        function changeRandomQuote() {
            // Obtener un índice aleatorio de todas las frases disponibles
            const randomIndex = Math.floor(Math.random() * allQuotes.length);
            const randomQuote = allQuotes[randomIndex];
            
            // Obtener un índice aleatorio de las tarjetas de frases visibles (excluyendo las dos primeras)
            const cardIndex = Math.floor(Math.random() * (quoteCards.length - 2)) + 2;
            const selectedCard = quoteCards[cardIndex];
            
            // Actualizar el contenido de la tarjeta seleccionada
            const quoteText = selectedCard.querySelector('.quote-text');
            const quoteReference = selectedCard.querySelector('.quote-reference');
            
            quoteText.textContent = `"${randomQuote.text}"`;
            quoteReference.textContent = randomQuote.reference;
            
            // Agregar efecto visual
            selectedCard.style.transform = 'scale(1.05)';
            selectedCard.style.boxShadow = '0 10px 25px rgba(0, 0, 0, 0.15)';
            
            setTimeout(() => {
                selectedCard.style.transform = '';
                selectedCard.style.boxShadow = '';
            }, 300);
        }
        
        // Evento para el botón
        quoteButton.addEventListener('click', changeRandomQuote);
        
        // Efecto adicional: cambiar color de fondo al pasar sobre las tarjetas
        quoteCards.forEach(card => {
            card.addEventListener('mouseenter', function() {
                this.style.backgroundColor = '#f8f5f0';
            });
            
            card.addEventListener('mouseleave', function() {
                this.style.backgroundColor = 'white';
            });
        });
        
        // Cambiar automáticamente una frase cada 15 segundos
        setInterval(changeRandomQuote, 15000);
        
        // Efecto de aparición para las tarjetas
        document.addEventListener('DOMContentLoaded', function() {
            quoteCards.forEach((card, index) => {
                card.style.opacity = '0';
                card.style.transform = 'translateY(20px)';
                
                setTimeout(() => {
                    card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0)';
                }, 100 * index);
            });
        });
    </script>
</body>
</html>""",200
    #with open(LOG_FILE, 'r') as f:
#        logs = f.readlines()
#    
#    # Get statistics from database
#    access_count, today_access = get_access_stats()
#    uploads_dict = get_uploads()
#    downloads_dict = get_downloads()
#    status_changes_list = get_status_changes()
#    
#    upload_list = [f"{file} (Subido el {time})" for file, time in uploads_dict.items()]
#    download_list = [f"{file} (Bajado el {time})" for file, time in downloads_dict.items()]
#    status_history = status_changes_list.copy()
    
    
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
    return "vdataantiloqueraV2.9"

@app.route('/downloadkilo')
def down():
    return "Contacte con el creador para obtener la ultima versión"

@app.route('/update')
def doggggwn():
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Contacta para la Última Versión</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&family=Montserrat:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Poppins', sans-serif;
            background: linear-gradient(135deg, #0c2461 0%, #1e3799 50%, #4a69bd 100%);
            color: #fff;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            overflow-x: hidden;
        }

        .container {
            max-width: 1200px;
            width: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 40px;
        }

        .header {
            text-align: center;
            animation: fadeInDown 1s ease-out;
        }

        .logo {
            font-size: 3.5rem;
            margin-bottom: 15px;
            color: #6a89cc;
            filter: drop-shadow(0 0 10px rgba(106, 137, 204, 0.5));
        }

        .title {
            font-family: 'Montserrat', sans-serif;
            font-size: 3.2rem;
            font-weight: 700;
            margin-bottom: 10px;
            background: linear-gradient(to right, #6a89cc, #82ccdd);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            line-height: 1.2;
        }

        .subtitle {
            font-size: 1.3rem;
            font-weight: 300;
            opacity: 0.9;
            max-width: 700px;
            margin: 0 auto 20px;
        }

        .highlight {
            color: #82ccdd;
            font-weight: 600;
        }

        .content {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 50px;
            width: 100%;
            animation: fadeInUp 1.2s ease-out 0.3s both;
        }

        .info-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            flex: 1;
            min-width: 300px;
            max-width: 500px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.4s ease, box-shadow 0.4s ease;
        }

        .info-card:hover {
            transform: translateY(-10px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
        }

        .card-title {
            font-size: 1.8rem;
            margin-bottom: 25px;
            color: #82ccdd;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .card-title i {
            font-size: 2rem;
        }

        .features {
            list-style: none;
            margin-bottom: 30px;
        }

        .features li {
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 1.1rem;
        }

        .features li i {
            color: #6a89cc;
            font-size: 1.3rem;
        }

        .contact-form {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .form-group label {
            font-weight: 500;
            color: #82ccdd;
        }

        .form-group input,
        .form-group textarea {
            padding: 15px;
            border-radius: 10px;
            border: none;
            background: rgba(255, 255, 255, 0.15);
            color: white;
            font-family: 'Poppins', sans-serif;
            font-size: 1rem;
            transition: all 0.3s ease;
        }

        .form-group input:focus,
        .form-group textarea:focus {
            outline: none;
            background: rgba(255, 255, 255, 0.25);
            box-shadow: 0 0 0 2px #6a89cc;
        }

        .form-group textarea {
            min-height: 150px;
            resize: vertical;
        }

        .submit-btn {
            background: linear-gradient(to right, #6a89cc, #82ccdd);
            color: white;
            border: none;
            padding: 18px;
            border-radius: 10px;
            font-family: 'Montserrat', sans-serif;
            font-size: 1.2rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 10px;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            letter-spacing: 1px;
        }

        .submit-btn:hover {
            background: linear-gradient(to right, #82ccdd, #6a89cc);
            transform: translateY(-3px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
        }

        .submit-btn:active {
            transform: translateY(0);
        }

        .floating-icons {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: -1;
        }

        .icon {
            position: absolute;
            font-size: 2rem;
            opacity: 0.1;
            color: #82ccdd;
            animation: float 15s infinite linear;
        }

        .version-badge {
            position: absolute;
            top: 20px;
            right: 20px;
            background: linear-gradient(45deg, #6a89cc, #82ccdd);
            padding: 10px 20px;
            border-radius: 50px;
            font-weight: 600;
            font-size: 0.9rem;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            animation: pulse 2s infinite;
        }

        .footer {
            text-align: center;
            margin-top: 20px;
            opacity: 0.7;
            font-size: 0.9rem;
            animation: fadeIn 2s ease-out 1.5s both;
        }

        /* Animaciones */
        @keyframes fadeInDown {
            from {
                opacity: 0;
                transform: translateY(-50px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(50px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeIn {
            from {
                opacity: 0;
            }
            to {
                opacity: 0.7;
            }
        }

        @keyframes float {
            0% {
                transform: translate(0, 0) rotate(0deg);
            }
            25% {
                transform: translate(20px, 50px) rotate(90deg);
            }
            50% {
                transform: translate(40px, 0) rotate(180deg);
            }
            75% {
                transform: translate(20px, -50px) rotate(270deg);
            }
            100% {
                transform: translate(0, 0) rotate(360deg);
            }
        }

        @keyframes pulse {
            0% {
                transform: scale(1);
            }
            50% {
                transform: scale(1.05);
            }
            100% {
                transform: scale(1);
            }
        }

        /* Responsive */
        @media (max-width: 768px) {
            .title {
                font-size: 2.5rem;
            }
            
            .subtitle {
                font-size: 1.1rem;
            }
            
            .info-card {
                padding: 30px 25px;
            }
            
            .content {
                gap: 30px;
            }
            
            .version-badge {
                position: relative;
                top: 0;
                right: 0;
                margin-bottom: 20px;
            }
            
            .container {
                gap: 30px;
            }
        }
    </style>
</head>
<body>
    <div class="floating-icons" id="floating-icons"></div>
    
    <div class="version-badge">ÚLTIMA VERSIÓN DISPONIBLE</div>
    
    <div class="container">
        <div class="header">
            <div class="logo">
                <i class="fas fa-rocket"></i>
            </div>
            <h1 class="title">Contacta con el Administrador</h1>
            <p class="subtitle">Para obtener acceso a la <span class="highlight">última versión</span> de nuestra plataforma, completa el formulario y nuestro equipo te contactará en menos de 24 horas.</p>
        </div>
        
        <div class="content">
            <div class="info-card">
                <h2 class="card-title"><i class="fas fa-star"></i> Beneficios de la nueva versión</h2>
                <ul class="features">
                    <li><i class="fas fa-check-circle"></i> Interfaz completamente renovada y más intuitiva</li>
                    <li><i class="fas fa-check-circle"></i> Rendimiento optimizado en un 40%</li>
                    <li><i class="fas fa-check-circle"></i> Nuevas funciones exclusivas para usuarios</li>
                    <li><i class="fas fa-check-circle"></i> Mayor seguridad y protección de datos</li>
                    <li><i class="fas fa-check-circle"></i> Soporte para dispositivos móviles mejorado</li>
                    <li><i class="fas fa-check-circle"></i> Integración con herramientas populares</li>
                </ul>
                <div class="card-title"><i class="fas fa-shield-alt"></i> Proceso rápido y seguro</div>
                <p>Una vez que envíes tu solicitud, el administrador verificará tu cuenta y te proporcionará acceso inmediato a todas las nuevas características.</p>
            </div>
            
            <div class="info-card">
                <h2 class="card-title"><i class="fas fa-paper-plane"></i> Solicita tu acceso</h2>
                <form class="contact-form" id="contactForm">
                    <div class="form-group">
                        <label for="name"><i class="fas fa-user"></i> Nombre completo</label>
                        <input type="text" id="name" placeholder="Ingresa tu nombre" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="email"><i class="fas fa-envelope"></i> Correo electrónico</label>
                        <input type="email" id="email" placeholder="ejemplo@correo.com" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="company"><i class="fas fa-building"></i> Empresa o organización (opcional)</label>
                        <input type="text" id="company" placeholder="Nombre de tu empresa">
                    </div>
                    
                    <div class="form-group">
                        <label for="message"><i class="fas fa-comment-alt"></i> Mensaje para el administrador</label>
                        <textarea id="message" placeholder="Explícanos por qué deseas obtener la última versión..." required>Me gustaría obtener acceso a la última versión de la plataforma para aprovechar todas las nuevas funciones y mejoras de rendimiento. Por favor, contáctame para proceder con el proceso.</textarea>
                    </div>
                    
                    <button type="submit" class="submit-btn">
                        <i class="fas fa-paper-plane"></i> Enviar solicitud
                    </button>
                </form>
            </div>
        </div>
        
        <div class="footer">
            <p>© 2023 Todos los derechos reservados | La última versión incluye mejoras significativas de rendimiento y seguridad</p>
        </div>
    </div>

    <script>
        // Crear iconos flotantes
        const floatingIcons = document.getElementById('floating-icons');
        const icons = ['fa-code', 'fa-cog', 'fa-bolt', 'fa-cloud', 'fa-database', 'fa-lock', 'fa-mobile-alt', 'fa-share-alt', 'fa-sync', 'fa-wifi'];
        
        for (let i = 0; i < 20; i++) {
            const icon = document.createElement('div');
            icon.classList.add('icon');
            icon.innerHTML = `<i class="fas ${icons[Math.floor(Math.random() * icons.length)]}"></i>`;
            
            // Posición aleatoria
            icon.style.left = `${Math.random() * 100}%`;
            icon.style.top = `${Math.random() * 100}%`;
            
            // Tamaño aleatorio
            const size = Math.random() * 2 + 1;
            icon.style.fontSize = `${size}rem`;
            
            // Retraso de animación aleatorio
            icon.style.animationDelay = `${Math.random() * 5}s`;
            icon.style.animationDuration = `${Math.random() * 10 + 10}s`;
            
            floatingIcons.appendChild(icon);
        }
        
        // Manejar el envío del formulario
        const contactForm = document.getElementById('contactForm');
        
        contactForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Obtener valores del formulario
            const name = document.getElementById('name').value;
            const email = document.getElementById('email').value;
            
            // Crear efecto de éxito
            const submitBtn = this.querySelector('.submit-btn');
            const originalText = submitBtn.innerHTML;
            
            submitBtn.innerHTML = '<i class="fas fa-check"></i> Solicitud enviada';
            submitBtn.style.background = 'linear-gradient(to right, #2ecc71, #27ae60)';
            
            // Mostrar mensaje de confirmación
            setTimeout(() => {
                alert(`¡Gracias ${name}! Tu solicitud ha sido enviada. El administrador te contactará en ${email} en menos de 24 horas.`);
                submitBtn.innerHTML = originalText;
                submitBtn.style.background = 'linear-gradient(to right, #6a89cc, #82ccdd)';
                contactForm.reset();
                
                // Restablecer el mensaje por defecto
                document.getElementById('message').value = "Me gustaría obtener acceso a la última versión de la plataforma para aprovechar todas las nuevas funciones y mejoras de rendimiento. Por favor, contáctame para proceder con el proceso.";
            }, 1500);
        });
        
        // Efecto de escritura para el título
        const title = document.querySelector('.title');
        const originalTitle = title.textContent;
        title.textContent = '';
        
        let i = 0;
        function typeWriter() {
            if (i < originalTitle.length) {
                title.textContent += originalTitle.charAt(i);
                i++;
                setTimeout(typeWriter, 50);
            }
        }
        
        // Iniciar la animación de escritura después de un breve retraso
        setTimeout(typeWriter, 500);
        
        // Efecto de aparición para los elementos de la lista
        const featureItems = document.querySelectorAll('.features li');
        featureItems.forEach((item, index) => {
            item.style.opacity = '0';
            item.style.transform = 'translateX(-20px)';
            
            setTimeout(() => {
                item.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                item.style.opacity = '1';
                item.style.transform = 'translateX(0)';
            }, 800 + (index * 150));
        });
    </script>
</body>
</html>"""

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
    
    startup_message = f"🚀 <b>Servidor Iniciado</b>\n\n🕐 Hora de inicio: {timestamp}\n📍 Timezone: America/Havana\n✅ Estado: Listo para recibir conexiones\n Lo mejor del word."
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
