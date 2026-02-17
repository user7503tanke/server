from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import os
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui_cambiala_en_produccion'

# Archivos de datos
DATA_FILE = 'data.json'
CONFIG_FILE = 'config.json'

# Configuración por defecto
DEFAULT_CONFIG = {
    "admin_password": "admin123",  # Cambiar en producción
    "available_states": ["activo", "inactivo", "pendiente", "bloqueado"]
}

# Inicializar archivos si no existen
def init_files():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({}, f)
    
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

init_files()

# Decorador para requerir login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Cargar datos desde JSON
def load_data():
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

# Guardar datos en JSON
def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Cargar configuración
def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

# Guardar configuración
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Agregar log de cambios
def add_log(data, id, action, old_state=None, new_state=None):
    if 'logs' not in data:
        data['logs'] = []
    
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'id': id,
        'action': action,
        'old_state': old_state,
        'new_state': new_state
    }
    data['logs'].append(log_entry)
    
    # Mantener solo últimos 100 logs
    if len(data['logs']) > 100:
        data['logs'] = data['logs'][-100:]

# Rutas de la API
@app.route('/api/register/<id>', methods=['POST'])
def register_id(id):
    data = load_data()
    
    if id in data:
        return jsonify({'error': 'ID already exists'}), 400
    
    config = load_config()
    data[id] = {
        'state': config['available_states'][0],  # Primer estado como default
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    add_log(data, id, 'registered')
    save_data(data)
    
    return jsonify({'message': 'ID registered successfully', 'id': id, 'state': data[id]['state']}), 201

@app.route('/api/check/<id>', methods=['GET'])
def check_id(id):
    data = load_data()
    
    if id in data:
        return jsonify({'exists': True, 'id': id, 'state': data[id]['state']})
    else:
        return jsonify({'exists': False, 'id': id}), 404

@app.route('/api/state/<id>', methods=['GET'])
def get_state(id):
    data = load_data()
    
    if id not in data:
        return jsonify({'error': 'ID not found'}), 404
    
    return jsonify({
        'id': id,
        'state': data[id]['state'],
        'created_at': data[id]['created_at'],
        'updated_at': data[id]['updated_at']
    })

@app.route('/api/state/<id>', methods=['PUT'])
def update_state(id):
    data = load_data()
    
    if id not in data:
        return jsonify({'error': 'ID not found'}), 404
    
    new_state = request.json.get('state')
    if not new_state:
        return jsonify({'error': 'State is required'}), 400
    
    config = load_config()
    if new_state not in config['available_states']:
        return jsonify({'error': f'Invalid state. Available: {config["available_states"]}'}), 400
    
    old_state = data[id]['state']
    data[id]['state'] = new_state
    data[id]['updated_at'] = datetime.now().isoformat()
    
    add_log(data, id, 'state_updated', old_state, new_state)
    save_data(data)
    
    return jsonify({'message': 'State updated successfully', 'id': id, 'new_state': new_state})

@app.route('/api/delete/<id>', methods=['DELETE'])
def delete_id(id):
    data = load_data()
    
    if id not in data:
        return jsonify({'error': 'ID not found'}), 404
    
    add_log(data, id, 'deleted', data[id]['state'], None)
    del data[id]
    save_data(data)
    
    return jsonify({'message': 'ID deleted successfully', 'id': id})

# Rutas del panel web
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        config = load_config()
        
        if password == config['admin_password']:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return render_template('login.html', error='Contraseña incorrecta')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin():
    data = load_data()
    config = load_config()
    
    # Separar IDs y logs
    ids_data = {k: v for k, v in data.items() if k != 'logs'}
    logs = data.get('logs', [])
    
    return render_template('admin.html', 
                         data=ids_data, 
                         states=config['available_states'],
                         logs=reversed(logs))  # Mostrar logs más recientes primero

@app.route('/admin/update_state/<id>', methods=['POST'])
@login_required
def admin_update_state(id):
    data = load_data()
    
    if id not in data:
        return redirect(url_for('admin'))
    
    new_state = request.form.get('state')
    config = load_config()
    
    if new_state in config['available_states']:
        old_state = data[id]['state']
        data[id]['state'] = new_state
        data[id]['updated_at'] = datetime.now().isoformat()
        add_log(data, id, 'state_updated', old_state, new_state)
        save_data(data)
    
    return redirect(url_for('admin'))

@app.route('/admin/delete/<id>', methods=['POST'])
@login_required
def admin_delete(id):
    data = load_data()
    
    if id in data:
        add_log(data, id, 'deleted', data[id]['state'], None)
        del data[id]
        save_data(data)
    
    return redirect(url_for('admin'))

@app.route('/admin/add_state', methods=['POST'])
@login_required
def add_state():
    config = load_config()
    new_state = request.form.get('new_state')
    
    if new_state and new_state not in config['available_states']:
        config['available_states'].append(new_state)
        save_config(config)
    
    return redirect(url_for('admin'))

@app.route('/admin/remove_state/<state>', methods=['POST'])
@login_required
def remove_state(state):
    config = load_config()
    
    if state in config['available_states'] and len(config['available_states']) > 1:
        config['available_states'].remove(state)
        save_config(config)
        
        # Actualizar IDs que tenían ese estado al primer estado disponible
        data = load_data()
        default_state = config['available_states'][0]
        
        for id, info in data.items():
            if id != 'logs' and info['state'] == state:
                old_state = info['state']
                info['state'] = default_state
                info['updated_at'] = datetime.now().isoformat()
                add_log(data, id, 'state_updated', old_state, default_state)
        
        save_data(data)
    
    return redirect(url_for('admin'))

@app.route('/admin/add_id', methods=['POST'])
@login_required
def admin_add_id():
    new_id = request.form.get('new_id')
    
    if new_id:
        data = load_data()
        if new_id not in data:
            config = load_config()
            data[new_id] = {
                'state': config['available_states'][0],
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            add_log(data, new_id, 'registered')
            save_data(data)
    
    return redirect(url_for('admin'))

@app.route('/admin/change_password', methods=['POST'])
@login_required
def change_password():
    current = request.form.get('current_password')
    new = request.form.get('new_password')
    confirm = request.form.get('confirm_password')
    
    config = load_config()
    
    if current == config['admin_password'] and new == confirm and new:
        config['admin_password'] = new
        save_config(config)
    
    return redirect(url_for('admin'))

