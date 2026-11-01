import array
import math
import queue
import unittest

from audio_engine import BYTES, FRAMES, RATE, RadioEngine, SILENCE, _put_latest, _device_name


def samples(data):
    return array.array('h', data)


def tone(amplitude=10000, frequency=1000, count=FRAMES, channels=2, rate=RATE):
    return array.array('h', (round(amplitude * math.sin(2 * math.pi * frequency * n / rate))
                           for n in range(count) for _ in range(channels))).tobytes()


class AudioEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = RadioEngine()

    def tearDown(self):
        self.engine.close()

    def test_windows_microphone_name_is_readable(self):
        broken = 'Микрофон'.encode('utf-8').decode('cp1251')
        self.assertEqual(_device_name(broken), 'Микрофон')
        self.assertEqual(_device_name('Microphone (fifine SC3)'), 'Microphone (fifine SC3)')

    def test_each_listener_receives_complete_identical_frames(self):
        first, second = self.engine.subscribe(), self.engine.subscribe()
        try:
            self.assertEqual(first.get(timeout=1), SILENCE)
            self.assertEqual(second.get(timeout=1), SILENCE)
            self.assertEqual(len(SILENCE), BYTES)
            self.assertEqual(self.engine.status()['listeners'], 2)
        finally:
            self.engine.unsubscribe(first); self.engine.unsubscribe(second)

    def test_slow_listener_drops_whole_frames_only(self):
        frames = queue.Queue(maxsize=2)
        for number in range(3):
            _put_latest(frames, number)
        self.assertEqual([frames.get_nowait(), frames.get_nowait()], [1, 2])

    def test_sources_always_mix_and_each_can_be_muted(self):
        self.engine.set_levels(music_volume=100, mic_volume=100, master_volume=100)
        music, mic = tone(5000), tone(3000, channels=1)
        mixed = samples(self.engine._mix(music, mic))
        expected = [a + b for a, b in zip(samples(music), samples(tone(3000)))]
        self.assertEqual(list(mixed), expected)
        self.engine.set_levels(music_muted=True)
        self.assertEqual(self.engine._mix(music, mic), tone(3000))
        self.engine.set_levels(mic_muted=True)
        self.assertEqual(self.engine._mix(music, mic), SILENCE)

    def test_full_scale_sum_is_limited_without_flat_clipping(self):
        self.engine.set_levels(music_volume=100, mic_volume=100, master_volume=100)
        source = tone(30000)
        output = samples(self.engine._mix(source, tone(30000, channels=1)))
        self.assertLessEqual(max(map(abs, output)), 29490)
        gain = self.engine.limiter_gain * 2
        residual = max(abs(actual - original * gain) for actual, original in zip(output, samples(source)))
        self.assertLessEqual(residual, 0.51)
        self.assertGreater(self.engine.status()['limiter_db'], 0)

    def test_zero_and_master_mute_produce_exact_silence(self):
        source = tone()
        self.engine.set_levels(master_volume=0)
        self.assertEqual(self.engine._mix(source, None), SILENCE)
        self.engine.set_levels(master_volume=100, output_muted=True)
        self.assertEqual(self.engine._mix(source, None), SILENCE)

    def test_44k1_microphone_resampling_keeps_state_between_chunks(self):
        data = tone(4000, rate=44100, count=44100, channels=1)
        self.engine.mic_rate = 44100
        blockwise = b''.join(self.engine._convert_mic(data[start:start+882]) for start in range(0, len(data), 882))
        reference = RadioEngine()
        reference.mic_rate = 44100
        try:
            self.assertEqual(blockwise, reference._convert_mic(data))
            self.assertLess(abs(len(blockwise)//2 - RATE), 2)
        finally:
            reference.close()

    def test_microphone_dc_is_removed(self):
        data = array.array('h', [10000] * FRAMES).tobytes()
        for _ in range(10):
            output = samples(self.engine._convert_mic(data))
        self.assertLess(max(map(abs, output)), 2)

    def test_gain_rejects_invalid_values(self):
        for values in ({'music_volume': -1}, {'mic_volume': 101}, {'master_volume': True},
                       {'music_muted': 'true'}, {'unknown': 10}, {}):
            with self.assertRaises(ValueError):
                self.engine.set_levels(**values)


if __name__ == '__main__':
    unittest.main()
