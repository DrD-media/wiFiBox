from flask import Flask, send_file, send_from_directory, jsonify, request, Response
from flask_cors import CORS
import os
import json
import threading
import queue
import time
import tempfile
import uuid
import socket
from functools import wraps
from audio_engine import RadioEngine, BYTES, RATE, SILENCE
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ============================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И НАСТРОЙКИ
# ============================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'frontend', 'dist'))

# Создаем необходимые директории
os.makedirs(os.path.join(BASE_DIR, 'music_files'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'covers'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'track_texts'), exist_ok=True)

engine = RadioEngine()
current_playlist = None
playlist_position = 0
playlist_lock = threading.Lock()
metadata_lock = threading.RLock()


def synchronized_metadata(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with metadata_lock:
            return function(*args, **kwargs)
    return wrapped


def save_json_data(filename, data):
    """Replace a catalog only after its complete JSON has reached disk."""
    path = os.path.join(BASE_DIR, filename)
    descriptor, temporary = tempfile.mkstemp(prefix='.save-', suffix='.json', dir=BASE_DIR)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def advance_playlist(expected_generation=None):
    global current_playlist, playlist_position
    with playlist_lock:
        if current_playlist is None or (expected_generation is not None and
                                       expected_generation != engine.music_generation):
            return
        ids = current_playlist.get('track_ids') or []
        playlist_position += 1
        if playlist_position >= len(ids):
            current_playlist = None
            return
        track_id = ids[playlist_position]
        with app.app_context():
            result = play_track(track_id)
        if result.status_code != 200:
            current_playlist = None
            engine.last_error = result.get_json().get('error', 'Не удалось запустить следующий трек')


engine.on_track_finished = advance_playlist


def load_tracks_data():
    path = os.path.join(BASE_DIR, 'music_data.json')
    if not os.path.exists(path):
        return {'tracks': []}
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)


def load_playlists():
    path = os.path.join(BASE_DIR, 'playlists.json')
    if not os.path.exists(path):
        return {'playlists': []}
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)


ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'm4a'}
ALLOWED_IMAGES = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALLOWED_TEXTS = {'txt'}


def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set


def safe_media_path(folder, filename):
    if not isinstance(filename, str) or not filename or filename in ('.', '..'):
        return None
    if os.path.basename(filename) != filename or '\\' in filename or '\x00' in filename:
        return None
    return os.path.join(BASE_DIR, folder, filename)


def api_error(message, status=500):
    app.logger.error(message)
    response = jsonify({'success': False, 'error': message})
    response.status_code = status
    return response


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception('Unhandled request error: %s', error)
    return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500


@app.before_request
def validate_json_object():
    if request.is_json and request.content_length and not isinstance(request.get_json(silent=True), dict):
        return api_error('Ожидается JSON-объект', 400)


# ============================================
# МАРШРУТЫ HTML И МЕДИФАЙЛОВ
# ============================================

@app.route('/')
@app.route('/dj')
@app.route('/debug/radio')
def frontend_page():
    if not os.path.isfile(os.path.join(FRONTEND_DIR, 'index.html')):
        return 'Интерфейс не собран. Запустите tools/build_web.cmd.', 503
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/assets/<path:filename>')
def frontend_asset(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'assets'), filename)


@app.route('/icons/<path:filename>')
def frontend_icon(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'icons'), filename)

@app.route('/api/cover/<filename>')
def get_cover(filename):
    return send_file(os.path.join(BASE_DIR, 'covers', filename))

@app.route('/music_files/<filename>')
def get_music_file(filename):
    return send_file(os.path.join(BASE_DIR, 'music_files', filename))

@app.route('/track_texts/<filename>')
def get_track_text(filename):
    return send_file(os.path.join(BASE_DIR, 'track_texts', filename))

# ============================================
# API РАДИОВЕЩАНИЯ И СТРИМА
# ============================================

def create_wav_header():
    import struct
    # Streaming WAV with unknown duration. The PCM payload stays continuous.
    return (b'RIFF' + struct.pack('<I', 0xFFFFFFFE) + b'WAVEfmt ' +
            struct.pack('<IHHIIHH', 16, 1, 2, RATE, RATE * 4, 4, 16) +
            b'data' + struct.pack('<I', 0xFFFFFFDA))


def stream_response(wav=False):
    def generate():
        subscriber = engine.subscribe()
        try:
            if wav:
                yield create_wav_header()
            while True:
                try:
                    yield subscriber.get(timeout=1)
                except queue.Empty:
                    yield SILENCE
        finally:
            engine.unsubscribe(subscriber)

    response = Response(generate(), mimetype='audio/wav' if wav else 'application/octet-stream')
    response.headers['Cache-Control'] = 'no-store, no-transform'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['X-Audio-Rate'] = str(RATE)
    response.headers['X-Audio-Channels'] = '2'
    response.headers['X-Audio-Bits'] = '16'
    response.headers['X-Audio-Format'] = 's16le'
    return response


@app.route('/api/radio/stream')
def radio_stream():
    # Raw little-endian stereo PCM for the ESP32 I2S receiver.
    return stream_response()


@app.route('/api/radio/stream.wav')
def radio_stream_wav():
    return stream_response(wav=True)


def play_track(track_id):
    track = next((item for item in load_tracks_data().get('tracks', [])
                  if item.get('id') == track_id), None)
    if track is None:
        return api_error('Трек не найден', 404)
    filename = os.path.basename(track.get('filename', ''))
    if not filename:
        return api_error('У трека не указан файл', 400)
    try:
        engine.play(os.path.join(BASE_DIR, 'music_files', filename), track)
    except FileNotFoundError as exc:
        return api_error(str(exc), 404)
    except RuntimeError as exc:
        return api_error(str(exc), 503)
    return jsonify({'success': True, 'track': track, 'listeners': engine.status()['listeners']})


@app.route('/api/radio/play/<int:track_id>', methods=['POST'])
def radio_play(track_id):
    global current_playlist
    with playlist_lock:
        current_playlist = None
        return play_track(track_id)


@app.route('/api/radio/playlist/<int:playlist_id>', methods=['POST'])
def radio_playlist(playlist_id):
    global current_playlist, playlist_position
    playlist = next((item for item in load_playlists().get('playlists', [])
                     if item.get('id') == playlist_id), None)
    if playlist is None:
        return api_error('Плейлист не найден', 404)
    ids = playlist.get('track_ids') or []
    if not ids:
        return api_error('Плейлист пуст', 400)
    with playlist_lock:
        response = play_track(ids[0])
        if response.status_code == 200:
            current_playlist = playlist
            playlist_position = 0
        else:
            current_playlist = None
        return response


@app.route('/api/radio/mic', methods=['POST'])
def radio_mic():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('on', 'off'):
        return api_error('Укажите action: on или off', 400)
    device_index = data.get('device_index')
    if device_index is not None and (type(device_index) is not int or device_index < 0):
        return api_error('Некорректный номер микрофона', 400)
    try:
        if action == 'on':
            engine.start_mic(device_index)
        else:
            engine.stop_mic()
    except RuntimeError as exc:
        return api_error(str(exc), 503)
    return jsonify({'success': True, 'mic_active': engine.status()['mic_active']})


@app.route('/api/radio/mics')
def radio_mics():
    try:
        return jsonify(engine.input_devices())
    except RuntimeError as exc:
        return api_error(str(exc), 503)


@app.route('/api/radio/levels', methods=['POST'])
def radio_levels():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error('Ожидается объект с настройками звука', 400)
    try:
        engine.set_levels(**data)
    except ValueError as exc:
        return api_error(str(exc), 400)
    return jsonify({'success': True, **engine.status()})


@app.route('/api/system')
def system_info():
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET) if not info[4][0].startswith('127.')})
    except OSError:
        addresses = []
    return jsonify({'addresses': addresses, 'port': 5000, 'sample_rate': RATE,
                    'format': 'PCM signed 16-bit LE / stereo',
                    'hardware': 'ESP32 → PCM5102A → PAM8403',
                    'pins': {'lrck': 25, 'din': 26, 'bck': 27, 'button': 13, 'led': 14}})


@app.route('/api/radio/status')
def radio_status():
    with playlist_lock:
        playlist = current_playlist
    return jsonify({**engine.status(), 'current_playlist': playlist})


@app.route('/api/radio/stop', methods=['POST'])
def radio_stop():
    global current_playlist
    with playlist_lock:
        current_playlist = None
        engine.panic()
    return jsonify({'success': True})


# ============================================
# API УПРАВЛЕНИЯ ТРЕКАМИ И ПЛЕЙЛИСТАМИ
# ============================================

@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    tracks = load_tracks_data()
    return jsonify(tracks.get('tracks', []))

@app.route('/api/playlists', methods=['GET'])
def get_playlists():
    playlists = load_playlists()
    return jsonify(playlists.get('playlists', []))

@app.route('/api/tracks/<int:track_id>', methods=['PUT'])
@synchronized_metadata
def update_track(track_id):
    try:
        data = request.json or {}
        tracks_data = load_tracks_data()
        tracks = tracks_data.get('tracks', [])
        
        track_index = next((i for i, t in enumerate(tracks) if t['id'] == track_id), None)
        if track_index is None:
            return jsonify({'error': 'Track not found'}), 404
        
        for key, value in data.items():
            if key != 'id':
                tracks[track_index][key] = value
        
        save_json_data('music_data.json', tracks_data)
        
        return jsonify({'success': True, 'track': tracks[track_index]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracks/<int:track_id>', methods=['DELETE'])
@synchronized_metadata
def delete_track(track_id):
    try:
        tracks_data = load_tracks_data()
        tracks = tracks_data.get('tracks', [])
        
        track_to_delete = next((t for t in tracks if t['id'] == track_id), None)
        if track_to_delete is None:
            return jsonify({'error': 'Track not found'}), 404
        
        tracks = [t for t in tracks if t['id'] != track_id]
        tracks_data['tracks'] = tracks
        save_json_data('music_data.json', tracks_data)
        # Keep files that are still referenced by another track.
        used_audio = {t.get('filename') for t in tracks}
        used_covers = {t.get('cover') for t in tracks}
        used_texts = {text.get('filename') for t in tracks
                      for text in t.get('track_texts', []) if isinstance(text, dict)}
        resources = [('music_files', track_to_delete.get('filename'), used_audio),
                     ('covers', track_to_delete.get('cover'), used_covers)]
        resources.extend(('track_texts', text.get('filename'), used_texts)
                         for text in track_to_delete.get('track_texts', []) if isinstance(text, dict))
        for folder, filename, used in resources:
            path = safe_media_path(folder, filename)
            if path and filename not in used and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    app.logger.exception('Не удалось удалить медиафайл %s', path)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracks', methods=['POST'])
@synchronized_metadata
def create_track():
    try:
        data = request.json or {}
        tracks_data = load_tracks_data()
        tracks = tracks_data.get('tracks', [])
        
        new_id = max([t['id'] for t in tracks]) + 1 if tracks else 1
        
        new_track = {
            'id': new_id,
            'filename': data.get('filename', f'track_{new_id}.mp3'),
            'title': data.get('title', 'Новый трек'),
            'artist': data.get('artist', 'Неизвестный исполнитель'),
            'description': data.get('description', ''),
            'cover': data.get('cover', ''),
            'created_date': data.get('created_date', datetime.now().strftime('%Y-%m-%d')),
            'uploaded_by': data.get('uploaded_by', 1),
            'is_public': data.get('is_public', 'yes'),
            'track_texts': data.get('track_texts', [])
        }
        
        tracks.append(new_track)
        tracks_data['tracks'] = tracks
        
        save_json_data('music_data.json', tracks_data)
        
        return jsonify({'success': True, 'track': new_track})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload/mp3', methods=['POST'])
def upload_mp3():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename, ALLOWED_AUDIO):
            return jsonify({'error': 'Invalid file'}), 400
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(BASE_DIR, 'music_files', new_filename)
        file.save(filepath)
        
        return jsonify({'success': True, 'filename': new_filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload/cover', methods=['POST'])
def upload_cover():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGES):
            return jsonify({'error': 'Invalid file'}), 400
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = f"cover_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(BASE_DIR, 'covers', new_filename)
        file.save(filepath)
        
        return jsonify({'success': True, 'filename': new_filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload/text', methods=['POST'])
def upload_text():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename, ALLOWED_TEXTS):
            return jsonify({'error': 'Invalid file'}), 400
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = f"text_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(BASE_DIR, 'track_texts', new_filename)
        file.save(filepath)
        
        return jsonify({'success': True, 'filename': new_filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlists/<int:playlist_id>', methods=['PUT'])
@synchronized_metadata
def update_playlist(playlist_id):
    try:
        data = request.json or {}
        playlists_data = load_playlists()
        playlists = playlists_data.get('playlists', [])
        
        idx = next((i for i, p in enumerate(playlists) if p['id'] == playlist_id), None)
        if idx is None:
            return jsonify({'error': 'Playlist not found'}), 404
        
        for key, value in data.items():
            if key != 'id':
                playlists[idx][key] = value
        
        save_json_data('playlists.json', playlists_data)
        
        return jsonify({'success': True, 'playlist': playlists[idx]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlists/<int:playlist_id>', methods=['DELETE'])
@synchronized_metadata
def delete_playlist(playlist_id):
    try:
        playlists_data = load_playlists()
        playlists = [p for p in playlists_data.get('playlists', []) if p['id'] != playlist_id]
        playlists_data['playlists'] = playlists
        
        save_json_data('playlists.json', playlists_data)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlists', methods=['POST'])
@synchronized_metadata
def create_playlist():
    try:
        data = request.json or {}
        playlists_data = load_playlists()
        playlists = playlists_data.get('playlists', [])
        
        new_id = max([p['id'] for p in playlists]) + 1 if playlists else 1
        new_playlist = {
            'id': new_id,
            'name': data.get('name', 'Новый плейлист'),
            'type': data.get('type', 'user'),
            'owner_id': data.get('owner_id', 1),
            'cover': data.get('cover', ''),
            'created_date': data.get('created_date', datetime.now().strftime('%Y-%m-%d')),
            'last_updated': datetime.now().strftime('%Y-%m-%d'),
            'track_ids': data.get('track_ids', []),
            'description': data.get('description', ''),
            'is_public': data.get('is_public', 'yes')
        }
        
        playlists.append(new_playlist)
        playlists_data['playlists'] = playlists
        
        save_json_data('playlists.json', playlists_data)
        
        return jsonify({'success': True, 'playlist': new_playlist})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    raise SystemExit('Запустите START_RADIO.cmd в корне проекта.')
