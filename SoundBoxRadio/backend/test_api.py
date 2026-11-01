import unittest
import json
import os
import tempfile
import time
import wave
from unittest.mock import patch

from app import BASE_DIR, app, engine, safe_media_path, save_json_data
from audio_engine import BYTES


class RadioApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_status_and_invalid_controls(self):
        status = self.client.get('/api/radio/status')
        self.assertEqual(status.status_code, 200)
        self.assertIn('dropped_frames', status.json)
        self.assertEqual(self.client.post('/api/radio/mic', json={'action': 'invalid'}).status_code, 400)
        self.assertEqual(self.client.post('/api/radio/levels', json={'mic_volume': 101}).status_code, 400)
        self.assertEqual(self.client.post('/api/radio/play/999999').status_code, 404)
        self.assertEqual(self.client.post('/api/radio/playlist/999999').status_code, 404)
        for route in ('/api/radio/mic', '/api/radio/levels', '/api/tracks', '/api/playlists'):
            self.assertEqual(self.client.post(route, json=['invalid']).status_code, 400)

    def test_independent_levels_and_emergency_stop(self):
        response = self.client.post('/api/radio/levels', json={'music_volume': 23, 'mic_volume': 74, 'master_volume': 50, 'music_muted': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['music_volume'], 23)
        self.assertEqual(response.json['mic_volume'], 74)
        self.assertTrue(response.json['music_muted'])
        self.assertEqual(self.client.post('/api/radio/stop').status_code, 200)
        self.assertTrue(self.client.get('/api/radio/status').json['output_muted'])
        engine.set_levels(music_volume=70, mic_volume=70, master_volume=80, music_muted=False, output_muted=False)

    def test_built_frontend_is_served_on_all_panel_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, 'assets'))
            with open(os.path.join(directory, 'index.html'), 'w', encoding='utf-8') as stream:
                stream.write('<title>DrD Radio</title>')
            with open(os.path.join(directory, 'assets', 'app.js'), 'w', encoding='utf-8') as stream:
                stream.write('window.ready = true')
            with patch('app.FRONTEND_DIR', directory):
                for route in ('/', '/dj', '/debug/radio'):
                    response = self.client.get(route)
                    self.assertIn(b'DrD Radio', response.data)
                    response.close()
                response = self.client.get('/assets/app.js')
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_catalog_save_and_media_path_guard(self):
        with tempfile.TemporaryDirectory() as directory, patch('app.BASE_DIR', directory):
            save_json_data('catalog.json', {'name': 'Радио'})
            with open(os.path.join(directory, 'catalog.json'), encoding='utf-8') as stream:
                self.assertEqual(json.load(stream)['name'], 'Радио')
            self.assertIsNone(safe_media_path('covers', '../other.txt'))
            self.assertIsNone(safe_media_path('covers', '..\\other.txt'))
            self.assertEqual(safe_media_path('covers', 'my cover.jpg'),
                             os.path.join(directory, 'covers', 'my cover.jpg'))

    def test_microphone_failure_is_reported(self):
        with patch.object(engine, 'start_mic', side_effect=RuntimeError('Нет устройства')):
            response = self.client.post('/api/radio/mic', json={'action': 'on'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('Нет устройства', response.json['error'])

    def test_playlist_advances_without_request_context_and_ignores_stale_end(self):
        import app as radio
        tracks = {'tracks': [{'id': number, 'filename': 'test.wav'} for number in (101, 102)]}
        playlists = {'playlists': [{'id': 77, 'track_ids': [101, 102]}]}
        try:
            with patch('app.load_tracks_data', return_value=tracks), \
                    patch('app.load_playlists', return_value=playlists), \
                    patch.object(engine, 'play') as play:
                response = self.client.post('/api/radio/playlist/77')
                self.assertEqual(response.status_code, 200)
                radio.advance_playlist(engine.music_generation - 1)
                self.assertEqual(play.call_count, 1)
                radio.advance_playlist(engine.music_generation)
                self.assertEqual(play.call_args.args[1]['id'], 102)
                self.assertEqual(radio.playlist_position, 1)
                radio.advance_playlist(engine.music_generation)
                self.assertIsNone(radio.current_playlist)
        finally:
            with radio.playlist_lock:
                radio.current_playlist = None

    def test_raw_and_wav_stream_are_independent(self):
        raw = self.client.get('/api/radio/stream', buffered=False)
        wav = self.client.get('/api/radio/stream.wav', buffered=False)
        try:
            self.assertEqual(raw.mimetype, 'application/octet-stream')
            self.assertEqual(wav.mimetype, 'audio/wav')
            self.assertEqual(next(raw.response), bytes(BYTES))
            self.assertTrue(next(wav.response).startswith(b'RIFF'))
            self.assertEqual(next(wav.response), bytes(BYTES))
            self.assertEqual(engine.status()['listeners'], 2)
        finally:
            raw.close()
            wav.close()
        self.assertEqual(engine.status()['listeners'], 0)

    def test_real_track_decodes_and_finishes(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', dir=os.path.join(BASE_DIR, 'music_files'), delete=False) as handle:
            path = handle.name
        try:
            with wave.open(path, 'wb') as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes((b'\x10\x00' * 2) * 4410)
            track = {'id': 42, 'filename': os.path.basename(path), 'title': 'Test'}
            with patch('app.load_tracks_data', return_value={'tracks': [track]}):
                response = self.client.post('/api/radio/play/42')
            self.assertEqual(response.status_code, 200)
            subscriber = engine.subscribe()
            try:
                chunks = [subscriber.get(timeout=1) for _ in range(10)]
                self.assertTrue(any(any(chunk) for chunk in chunks))
                deadline = time.monotonic() + 2
                while engine.status()['current_track'] and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertIsNone(engine.status()['current_track'])
            finally:
                engine.unsubscribe(subscriber)
                engine.stop_music()
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
