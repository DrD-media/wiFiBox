"""Portable entry point. No installation, package resolution or internet requests."""
import importlib
import ipaddress
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import signal
import sys
import threading
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:5000/'


def block_external_network():
    """Used by the offline integration check; LAN and localhost remain available."""
    original = socket.socket.connect
    original_resolve = socket.getaddrinfo

    def local_resolve(host, *args, **kwargs):
        if host not in (None, '', 'localhost', socket.gethostname()):
            try:
                ip = ipaddress.ip_address(host)
            except ValueError as exc:
                raise OSError('Offline check blocked DNS: ' + str(host)) from exc
            if not (ip.is_private or ip.is_loopback):
                raise OSError('Offline check blocked external address: ' + str(host))
        return original_resolve(host, *args, **kwargs)

    def local_connect(sock, address):
        host = address[0]
        if host == 'localhost':
            host = '127.0.0.1'
        try:
            ip = ipaddress.ip_address(host)
        except ValueError as exc:
            raise OSError('Offline check blocked DNS: ' + host) from exc
        if not (ip.is_private or ip.is_loopback):
            raise OSError('Offline check blocked external connection: ' + host)
        return original(sock, address)
    socket.socket.connect = local_connect
    socket.getaddrinfo = local_resolve


def verify_local_files():
    expected = ROOT / 'runtime' / 'python'
    if not Path(sys.executable).resolve().is_relative_to(expected):
        raise RuntimeError('Запустите START_RADIO.cmd: он использует Python внутри проекта.')
    for name in ('flask', 'flask_cors', 'pyaudio', 'imageio_ffmpeg'):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(ROOT):
            raise RuntimeError('Библиотека найдена вне проекта: ' + name)
    if not (ROOT / 'frontend' / 'dist' / 'index.html').is_file():
        raise RuntimeError('Нет готового интерфейса. Запустите tools/build_web.cmd.')
    from audio_engine import RadioEngine
    RadioEngine.ffmpeg_path()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if hasattr(signal, 'SIGBREAK'):
        def stop_console(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, stop_console)
    verify_local_files()
    if '--self-check' in sys.argv:
        print('OK: Python, библиотеки, FFmpeg и интерфейс находятся внутри проекта.')
        return
    if os.environ.get('SOUNDBOX_OFFLINE_TEST') == '1':
        block_external_network()
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / 'server.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    from app import app, engine
    from werkzeug.serving import make_server, WSGIRequestHandler

    class RadioRequestHandler(WSGIRequestHandler):
        # ESP32 consumes a close-delimited PCM body. Werkzeug otherwise adds HTTP
        # chunk length lines even for an HTTP/1.0 request on a threaded server.
        protocol_version = 'HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(10)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        server = make_server('0.0.0.0', 5000, app, threaded=True,
                             request_handler=RadioRequestHandler)
    except (OSError, SystemExit) as exc:
        raise RuntimeError('Не удалось открыть порт 5000. Закройте прежнее окно сервера.') from exc
    print('SoundBoxRadio · автономный сервер\nПанель: ' + URL +
          '\nДля ESP32 укажите IPv4 этого компьютера и порт 5000.' +
          '\nДля остановки нажмите Ctrl+C.\n', flush=True)
    if '--no-browser' not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(URL)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        engine.close()
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.exception('Startup failed')
        print('Ошибка запуска: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
