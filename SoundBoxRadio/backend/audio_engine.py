"""One paced PCM bus: 48 kHz, signed 16-bit little endian, two channels."""
import array
import audioop
import logging
import math
import os
import queue
import subprocess
import sys
import threading
import time

RATE = 48000
FRAMES = 960
BYTES = FRAMES * 4
SILENCE = bytes(BYTES)
LOG = logging.getLogger(__name__)


def _device_name(value):
    try:
        repaired = value.encode('cp1251').decode('utf-8')
        if repaired != value and value.count('Р') >= 2:
            return repaired
    except (UnicodeError, AttributeError):
        pass
    return value


def _put_latest(destination, value):
    try:
        destination.put_nowait(value)
    except queue.Full:
        try:
            destination.get_nowait()
        except queue.Empty:
            pass
        destination.put_nowait(value)


class RadioEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.subscribers = set()
        self.running = False
        self.track = None
        self.process = None
        self.music = queue.Queue(maxsize=21)
        self.music_generation = 0
        self.music_buffering = True
        self.mic = self.mic_stream = None
        self.mic_queue = queue.Queue(maxsize=12)
        self.mic_channels, self.mic_rate = 1, RATE
        self.mic_pcm = bytearray()
        self.resample_state = None
        self.highpass_x = self.highpass_y = 0.0
        self.mic_error = self.last_error = None
        self.music_volume, self.mic_volume, self.master_volume = 70, 70, 80
        self.music_muted = self.mic_muted = self.output_muted = False
        self.limiter_gain = 1.0
        self.music_peak = self.mic_peak = self.output_peak = 0.0
        self.dropped_frames = self.music_underruns = self.mic_overflows = 0
        self.on_track_finished = None
        self.stop_event = threading.Event()

    def ensure_running(self):
        with self.lock:
            if not self.running:
                self.running = True
                threading.Thread(target=self._broadcast, name='pcm-bus', daemon=True).start()

    def subscribe(self):
        self.ensure_running()
        subscriber = queue.Queue(maxsize=12)
        with self.lock:
            self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self.lock:
            self.subscribers.discard(subscriber)

    def _flush_listeners(self):
        for subscriber in self.subscribers:
            while True:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    break

    def set_levels(self, **values):
        allowed = {'music_volume', 'mic_volume', 'master_volume',
                   'music_muted', 'mic_muted', 'output_muted'}
        if not values or set(values) - allowed:
            raise ValueError('Укажите громкость или отключение источника')
        for name, value in values.items():
            if name.endswith('_volume'):
                if type(value) is not int or not 0 <= value <= 100:
                    raise ValueError('Громкость должна быть целым числом от 0 до 100')
            elif type(value) is not bool:
                raise ValueError('Состояние отключения должно быть true или false')
        with self.lock:
            for name, value in values.items():
                setattr(self, name, value)
            self._flush_listeners()

    def _stop_music_locked(self):
        self.music_generation += 1
        process, self.process = self.process, None
        self.track = None
        self.music = queue.Queue(maxsize=21)
        self.music_buffering = True
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    @staticmethod
    def ffmpeg_path():
        # A local binary is mandatory; never depend on PATH or download at runtime.
        import imageio_ffmpeg
        folder = os.path.join(os.path.dirname(imageio_ffmpeg.__file__), 'binaries')
        candidates = [os.path.join(folder, name) for name in os.listdir(folder)
                      if name.startswith('ffmpeg-') and name.endswith('.exe')]
        if not candidates:
            raise RuntimeError('В проекте отсутствует локальный FFmpeg')
        return candidates[0]

    def play(self, path, track):
        if not os.path.isfile(path):
            raise FileNotFoundError('Аудиофайл не найден на сервере')
        ffmpeg = self.ffmpeg_path()
        with self.lock:
            self._stop_music_locked()
            command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                       '-i', path, '-vn', '-f', 's16le', '-acodec', 'pcm_s16le',
                       '-ac', '2', '-ar', str(RATE), 'pipe:1']
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=BYTES * 4,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError as exc:
                raise RuntimeError(f'Не удалось запустить FFmpeg: {exc}') from exc
            self.process, self.track = process, track
            self.last_error = None
            self.output_muted = False
            threading.Thread(target=self._read_music,
                args=(process, self.music, self.music_generation), daemon=True).start()
            self.ensure_running()

    def _read_music(self, process, destination, generation):
        try:
            while True:
                chunk = process.stdout.read(BYTES)
                if not chunk:
                    break
                while not self.stop_event.is_set():
                    with self.lock:
                        if generation != self.music_generation:
                            return
                    try:
                        destination.put(chunk.ljust(BYTES, b'\0'), timeout=0.1)
                        break
                    except queue.Full:
                        continue
            code = process.wait()
            with self.lock:
                if generation == self.music_generation:
                    self.process = None
                    if code:
                        self.last_error = f'Ошибка декодирования аудиофайла ({code})'
        except Exception:
            LOG.exception('Decoder failed')
            with self.lock:
                if generation == self.music_generation:
                    self.last_error = 'Ошибка чтения аудиофайла'
                    self.process = None
        finally:
            process.stdout.close()

    def stop_music(self):
        with self.lock:
            self._stop_music_locked()
            self._flush_listeners()

    def start_mic(self, device_index=None):
        import pyaudio
        with self.lock:
            if self.mic_stream:
                return
            try:
                audio = pyaudio.PyAudio()
            except OSError as exc:
                self.mic_error = str(exc)
                raise RuntimeError(f'Аудиодрайвер недоступен: {exc}') from exc
            stream = None
            try:
                info = (audio.get_default_input_device_info() if device_index is None
                        else audio.get_device_info_by_index(device_index))
                if info['maxInputChannels'] < 1:
                    raise RuntimeError('Выбранное устройство не поддерживает запись')
                rates = list(dict.fromkeys([RATE, int(info['defaultSampleRate']), 44100]))
                channels = [1, 2] if info['maxInputChannels'] >= 2 else [1]
                self.mic_queue = queue.Queue(maxsize=12)
                self.mic_pcm.clear()
                self.resample_state = None
                self.highpass_x = self.highpass_y = 0.0
                last_error = None
                for rate in rates:
                    for count in channels:
                        try:
                            stream = audio.open(format=pyaudio.paInt16, channels=count,
                                rate=rate, input=True, input_device_index=int(info['index']),
                                frames_per_buffer=round(rate * 0.02),
                                stream_callback=self._mic_callback, start=False)
                            self.mic_rate, self.mic_channels = rate, count
                            break
                        except (OSError, ValueError) as exc:
                            last_error = exc
                    if stream:
                        break
                if stream is None:
                    raise RuntimeError(f'Недоступный формат записи: {last_error}')
                stream.start_stream()
            except Exception as exc:
                if stream:
                    stream.close()
                audio.terminate()
                self.mic_error = str(exc)
                raise RuntimeError(f'Не удалось открыть микрофон: {exc}') from exc
            self.mic, self.mic_stream = audio, stream
            self.mic_error = None
            self.output_muted = False
            self.ensure_running()

    @staticmethod
    def input_devices():
        import pyaudio
        try:
            audio = pyaudio.PyAudio()
        except OSError as exc:
            raise RuntimeError(f'Аудиодрайвер недоступен: {exc}') from exc
        try:
            try:
                default = audio.get_default_input_device_info()['index']
            except OSError:
                default = None
            result = []
            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)
                if info['maxInputChannels'] > 0:
                    host = audio.get_host_api_info_by_index(info['hostApi'])['name']
                    result.append({'id': index, 'name': _device_name(info['name']),
                                   'host': host, 'default': index == default})
            return result
        finally:
            audio.terminate()

    def _mic_callback(self, data, frame_count, time_info, status):
        import pyaudio
        # The audio driver callback only copies bytes. DSP runs on the PCM bus.
        if status:
            self.mic_overflows += 1
        if data:
            _put_latest(self.mic_queue, data)
        return None, pyaudio.paContinue

    def _convert_mic(self, data):
        if self.mic_channels == 2:
            data = audioop.tomono(data, 2, 0.5, 0.5)
        if self.mic_rate != RATE:
            data, self.resample_state = audioop.ratecv(
                data, 2, 1, self.mic_rate, RATE, self.resample_state)
        # DC/rumble removal at 70 Hz, with state retained across callback blocks.
        values = array.array('h', data)
        if sys.byteorder != 'little':
            values.byteswap()
        coefficient = math.exp(-2 * math.pi * 70 / RATE)
        previous_x, previous_y = self.highpass_x, self.highpass_y
        for index, value in enumerate(values):
            previous_y = coefficient * (previous_y + value - previous_x)
            previous_x = value
            values[index] = max(-32768, min(32767, round(previous_y)))
        self.highpass_x, self.highpass_y = previous_x, previous_y
        if sys.byteorder != 'little':
            values.byteswap()
        return values.tobytes()

    def _mic_frame(self):
        while len(self.mic_pcm) < FRAMES * 2:
            try:
                self.mic_pcm.extend(self._convert_mic(self.mic_queue.get_nowait()))
            except queue.Empty:
                break
        frame = bytes(self.mic_pcm[:FRAMES * 2])
        del self.mic_pcm[:FRAMES * 2]
        return frame.ljust(FRAMES * 2, b'\0')

    def stop_mic(self):
        with self.lock:
            stream, audio = self.mic_stream, self.mic
            self.mic_stream = self.mic = None
            self.mic_queue = queue.Queue(maxsize=12)
            self.mic_pcm.clear()
            self.mic_error = None
            self._flush_listeners()
        if stream:
            try:
                stream.stop_stream()
            except OSError:
                LOG.warning('Microphone was already disconnected', exc_info=True)
            finally:
                try:
                    stream.close()
                finally:
                    audio.terminate()

    def panic(self):
        with self.lock:
            self.output_muted = True
            self._stop_music_locked()
            self._flush_listeners()
        self.stop_mic()

    def _mix(self, music, mic):
        stereo = array.array('h', music)
        mono = array.array('h', mic or bytes(FRAMES * 2))
        if sys.byteorder != 'little':
            stereo.byteswap()
            mono.byteswap()
        with self.lock:
            mg = 0 if self.music_muted else self.music_volume / 100
            vg = 0 if self.mic_muted else self.mic_volume / 100
            master = 0 if self.output_muted else self.master_volume / 100
        self.music_peak = max(map(abs, stereo), default=0) / 32768
        self.mic_peak = max(map(abs, mono), default=0) / 32768
        mixed = [stereo[i] * mg + mono[i // 2] * vg for i in range(FRAMES * 2)]
        peak = max(map(abs, mixed), default=0)
        target = min(1.0, 29490 / max(peak, 1))
        # Linked stereo peak limiter: immediate attack, 200 ms release, no flat clipping.
        self.limiter_gain = min(target, self.limiter_gain + (1 - self.limiter_gain) * 0.095)
        gain = self.limiter_gain * master
        result = array.array('h', (round(value * gain) for value in mixed))
        self.output_peak = max(map(abs, result), default=0) / 32768
        if sys.byteorder != 'little':
            result.byteswap()
        return result.tobytes()

    def _broadcast(self):
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            finished = False
            try:
                with self.lock:
                    music_queue, process = self.music, self.process
                    generation = self.music_generation
                    if self.music_buffering and (music_queue.qsize() >= 3 or process is None):
                        self.music_buffering = False
                    buffering = self.music_buffering
                try:
                    music = SILENCE if buffering else music_queue.get_nowait()
                except queue.Empty:
                    music = SILENCE
                    if process is not None:
                        self.music_underruns += 1
                        with self.lock:
                            if self.music is music_queue:
                                self.music_buffering = True
                with self.lock:
                    mic = self._mic_frame() if self.mic_stream is not None else None
                if process is None and music_queue.empty():
                    with self.lock:
                        if self.music is music_queue and self.track is not None:
                            self.track = None
                            finished = True
                frame = self._mix(music, mic)
                with self.lock:
                    for subscriber in self.subscribers:
                        if subscriber.full():
                            self.dropped_frames += 1
                        _put_latest(subscriber, frame)
                if finished and self.on_track_finished:
                    threading.Thread(target=self.on_track_finished,
                                     args=(generation,), daemon=True).start()
            except Exception:
                LOG.exception('PCM bus failed')
                self.last_error = 'Ошибка формирования аудиопотока'
            deadline += FRAMES / RATE
            delay = deadline - time.monotonic()
            if delay > 0:
                self.stop_event.wait(delay)
            elif delay < -0.1:
                deadline = time.monotonic()

    def close(self):
        self.panic()
        self.stop_event.set()

    def status(self):
        with self.lock:
            return {'is_live': bool(self.track or self.mic_stream) and not self.output_muted,
                    'current_track': self.track, 'mic_active': self.mic_stream is not None,
                    'listeners': len(self.subscribers), 'queue_size': self.music.qsize(),
                    'mic_error': self.mic_error, 'last_error': self.last_error,
                    'dropped_frames': self.dropped_frames, 'music_underruns': self.music_underruns,
                    'mic_overflows': self.mic_overflows, 'music_volume': self.music_volume,
                    'mic_volume': self.mic_volume, 'master_volume': self.master_volume,
                    'music_muted': self.music_muted, 'mic_muted': self.mic_muted,
                    'output_muted': self.output_muted, 'sample_rate': RATE,
                    'music_peak': round(self.music_peak * 100),
                    'mic_peak': round(self.mic_peak * 100),
                    'mic_peak_samples': round(self.mic_peak * 32768),
                    'output_peak': round(self.output_peak * 100),
                    'limiter_db': round(-20 * math.log10(max(self.limiter_gain, 0.001)), 1)}
