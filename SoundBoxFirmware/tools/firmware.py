"""Build / flash using only the toolchain stored in this project."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'runtime' / 'platformio'
ESPTOOL = CORE / 'packages' / 'tool-esptoolpy' / 'esptool.py'


def esptool(*arguments):
    subprocess.run([sys.executable, str(ESPTOOL), '--chip', 'esp32', *arguments], check=True)


def build():
    os.environ['PLATFORMIO_CORE_DIR'] = str(CORE)
    os.environ['PLATFORMIO_SETTING_ENABLE_TELEMETRY'] = 'false'
    os.environ['PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL'] = '999999'
    block_external_network()
    from platformio.__main__ import main as platformio_main
    result = platformio_main(['platformio', 'run', '-d', str(ROOT)])
    if result:
        raise SystemExit(result)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    compiled = ROOT / '.pio' / 'build' / 'esp32dev'
    shutil.copy2(compiled / 'firmware.bin', output / 'SoundBoxRadio-app.bin')
    esptool('merge_bin', '-o', str(output / 'SoundBoxRadio-full.bin'),
            '--flash_mode', 'dio', '--flash_freq', '40m', '--flash_size', '4MB',
            '0x1000', str(compiled / 'bootloader.bin'),
            '0x8000', str(compiled / 'partitions.bin'),
            '0xe000', str(CORE / 'packages' / 'framework-arduinoespressif32' / 'tools' / 'partitions' / 'boot_app0.bin'),
            '0x10000', str(compiled / 'firmware.bin'))
    manifest = {'project': 'SoundBoxFirmware', 'python': sys.version.split()[0],
                'format': 'PCM 48000 Hz, signed 16-bit LE, stereo',
                'pins': {'lrck': 25, 'din': 26, 'bck': 27}, 'sha256': {}}
    for name in ('src/main.cpp', 'platformio.ini', 'dist/SoundBoxRadio-app.bin',
                 'dist/SoundBoxRadio-full.bin'):
        manifest['sha256'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def block_external_network():
    """Fail if the local build tries package downloads or external DNS."""
    original_connect, original_resolve = socket.socket.connect, socket.getaddrinfo

    def check(host):
        if host in (None, '', 'localhost', socket.gethostname()):
            return
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise OSError('Offline firmware build blocked DNS: ' + str(host)) from exc
        if not (address.is_private or address.is_loopback):
            raise OSError('Offline firmware build blocked external address: ' + str(host))

    def local_connect(connection, address):
        check(address[0])
        return original_connect(connection, address)

    def local_resolve(host, *args, **kwargs):
        check(host)
        return original_resolve(host, *args, **kwargs)

    socket.socket.connect, socket.getaddrinfo = local_connect, local_resolve


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if not Path(sys.executable).resolve().is_relative_to(ROOT / 'runtime/python'):
        raise SystemExit('Используйте BUILD_FIRMWARE.cmd или FLASH_ESP32.cmd с Python внутри проекта.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--flash', metavar='COM_PORT')
    parser.add_argument('--list', action='store_true')
    options = parser.parse_args()
    if options.build:
        build()
    elif options.flash:
        image = ROOT / 'dist' / 'SoundBoxRadio-full.bin'
        if not image.is_file():
            parser.error('Сначала выполните BUILD_FIRMWARE.cmd')
        port = options.flash
        if port == 'auto':
            from serial.tools.list_ports import comports
            ports = [item for item in comports() if item.vid is not None]
            if not ports:
                parser.error('ESP32 USB не найден. Подключите плату кабелем USB с передачей данных.')
            for index, item in enumerate(ports, 1):
                print(f'{index}. {item.device}: {item.description}')
            try:
                selected = int(input('Номер ESP32 в списке: '))
                if not 1 <= selected <= len(ports):
                    raise ValueError
                port = ports[selected - 1].device
            except (ValueError, IndexError):
                parser.error('Неверный номер устройства')
        esptool('--port', port, '--baud', '460800', 'write_flash', '0x0', str(image))
    else:
        from serial.tools.list_ports import comports
        for port in comports():
            print(port.device, port.description)
