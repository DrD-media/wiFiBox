"""Exercise the portable launcher, real HTTP stream and optional physical microphone.

No catalog changes, recordings or external requests. Results go to docs/validation.json.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / 'runtime/python/python.exe'


def api(path, data=None):
    connection = http.client.HTTPConnection('127.0.0.1', 5000, timeout=8)
    try:
        connection.request('GET' if data is None else 'POST', path,
                           None if data is None else json.dumps(data),
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status != 200:
            raise RuntimeError(f'{path}: {response.status}: {result}')
        return result
    finally:
        connection.close()


def read_pcm(frames=150):
    with socket.create_connection(('127.0.0.1', 5000), timeout=5) as stream:
        stream.sendall(b'GET /api/radio/stream HTTP/1.0\r\nHost: localhost\r\n\r\n')
        body = bytearray()
        while b'\r\n\r\n' not in body:
            body.extend(stream.recv(997))
        header, body = bytes(body).split(b'\r\n\r\n', 1)
        assert b'200 OK' in header and b'Transfer-Encoding:' not in header
        for expected in (b'X-Audio-Rate: 48000', b'X-Audio-Channels: 2',
                         b'X-Audio-Bits: 16', b'X-Audio-Format: s16le'):
            assert expected in header, header
        started = time.monotonic()
        last_received, longest_gap = started, 0
        required = frames * 3840
        while len(body) < required:
            block = stream.recv(min(997, required - len(body)))
            assert block, 'Stream disconnected'
            now = time.monotonic()
            longest_gap = max(longest_gap, now - last_received)
            last_received = now
            body += block
        return {'bytes': required, 'seconds': round(time.monotonic() - started, 3),
                'longest_gap_ms': round(longest_gap * 1000, 1),
                'nonzero': any(body[:required])}


def main(microphone, seconds):
    try:
        with socket.create_connection(('127.0.0.1', 5000), timeout=0.3):
            raise RuntimeError('Закройте прежний сервер перед проверкой порта 5000.')
    except (ConnectionRefusedError, TimeoutError):
        pass
    environment = os.environ.copy()
    environment.update(PATH='', PYTHONHOME='invalid-system-python',
                       PYTHONPATH='invalid-system-packages', SOUNDBOX_OFFLINE_TEST='1')
    report = {'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'checks': {},
              'physical_esp32_tested': False, 'ui_visual_tested': False}
    log = ROOT / 'logs/offline-check.log'
    log.parent.mkdir(exist_ok=True)
    with log.open('wb') as output:
        process = subprocess.Popen([os.environ['COMSPEC'], '/d', '/c',
                                   str(ROOT / 'START_RADIO.cmd'), '--no-browser'],
                                  cwd=ROOT, env=environment, stdout=output, stderr=output,
                                  creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    status = api('/api/radio/status')
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Portable launcher failed; see logs/offline-check.log')
                    time.sleep(0.1)
            report['checks']['launcher_empty_path_external_network_blocked'] = True
            connection = http.client.HTTPConnection('127.0.0.1', 5000)
            connection.request('GET', '/')
            response = connection.getresponse()
            html = response.read().decode('utf-8')
            assert response.status == 200 and 'SoundBoxRadio' in html
            connection.close()
            for path in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
                connection = http.client.HTTPConnection('127.0.0.1', 5000)
                connection.request('GET', path)
                response = connection.getresponse()
                assert response.status == 200 and response.read()
                connection.close()
            report['checks']['local_web_assets'] = True
            tracks = api('/api/tracks')
            track = next(item for item in tracks if
                         (ROOT / 'backend/music_files' / item['filename']).is_file())
            api('/api/radio/play/' + str(track['id']), {})
            if microphone:
                devices = api('/api/radio/mics')
                device = next((item for item in devices if 'SC3' in item['name']),
                              next((item for item in devices if item['default']), None))
                assert device, 'No physical microphone available'
                api('/api/radio/mic', {'action': 'on', 'device_index': device['id']})
                report['microphone'] = device
                time.sleep(0.3)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(read_pcm, round(seconds * 50)) for _ in range(2)]
                peak = 0
                while not all(future.done() for future in futures):
                    peak = max(peak, api('/api/radio/status')['mic_peak_samples'])
                    time.sleep(0.3)
                streams = [future.result() for future in futures]
            assert all(item['nonzero'] and seconds - 0.8 < item['seconds'] < seconds + 2
                       and item['longest_gap_ms'] < 500 for item in streams), streams
            report['checks'][f'two_clients_fragmented_pcm_{seconds}_seconds'] = streams
            status = api('/api/radio/status')
            assert status['current_track'] is not None
            if microphone:
                assert status['mic_active'] and status['mic_error'] is None
                report['checks']['simultaneous_music_microphone'] = {
                    key: status[key] for key in ('mic_active', 'mic_peak', 'mic_overflows',
                                                'music_underruns', 'output_peak', 'limiter_db')}
                report['checks']['simultaneous_music_microphone']['maximum_mic_peak_samples'] = peak
                api('/api/radio/mic', {'action': 'off'})
                api('/api/radio/mic', {'action': 'on', 'device_index': device['id']})
                api('/api/radio/mic', {'action': 'off'})
                report['checks']['microphone_reopen'] = True
            api('/api/radio/levels', {'master_volume': 0})
            time.sleep(0.1)
            assert not read_pcm(10)['nonzero']
            report['checks']['zero_volume_silence'] = True
            api('/api/radio/levels', {'master_volume': 80})
            api('/api/radio/stop', {})
            time.sleep(0.1)
            status = api('/api/radio/status')
            assert status['output_muted'] and not status['mic_active'] and not status['current_track']
            assert not read_pcm(10)['nonzero']
            report['checks']['emergency_stop_silence'] = True
        finally:
            # Graceful console Ctrl+Break applies only to the group created above.
            if process.poll() is None:
                process.send_signal(__import__('signal').CTRL_BREAK_EVENT)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'),
                                    '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    (ROOT / 'docs/validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--microphone', action='store_true')
    parser.add_argument('--seconds', type=int, default=3)
    args = parser.parse_args()
    if not 3 <= args.seconds <= 300:
        parser.error('--seconds: 3..300')
    main(args.microphone, args.seconds)
