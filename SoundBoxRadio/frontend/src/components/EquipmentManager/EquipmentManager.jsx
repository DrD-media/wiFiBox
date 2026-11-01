import { useEffect, useState } from 'react';
import axios from 'axios';

export default function EquipmentManager() {
  const [system, setSystem] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { axios.get('/api/system').then(response => setSystem(response.data)).catch(() => setError('Не удалось прочитать параметры сервера')); }, []);
  return <main className="hardware-panel"><h1>Подключение приёмника</h1><div className="hardware-grid">
    <section className="hardware-card"><h2>1. Сервер в локальной сети</h2><p>Компьютер и ESP32 должны быть в одной сети Wi-Fi. Интернет для работы не нужен. В настройках приёмника укажите IPv4 компьютера и порт <strong>5000</strong>.</p>{system?.addresses?.map(ip => <code key={ip}>{ip} : 5000</code>)}{error && <p role="alert">{error}</p>}<p>Если адресов несколько, выберите адрес адаптера вашей Wi-Fi сети. В Windows разрешите серверу входящие соединения TCP 5000 в частной сети.</p></section>
    <section className="hardware-card"><h2>2. Настройка ESP32</h2><p>Удерживайте кнопку на GPIO13 три секунды. Подключитесь к сети <strong>SoundBoxRadio-Setup</strong> и откройте <strong>192.168.4.1</strong>. Сохраните Wi-Fi и адрес сервера.</p><p>После подключения веб-страница ESP32 показывает буфер, разрывы сети и локальную громкость. Короткое нажатие кнопки включает тишину; повторное возвращает звук.</p></section>
    <section className="hardware-card"><h2>PCM5102A → PAM8403</h2><table><tbody>{[['ESP32 GPIO25', 'LCK / LRCK'], ['ESP32 GPIO26', 'DIN'], ['ESP32 GPIO27', 'BCK'], ['GPIO13 → кнопка', 'GND'], ['GPIO14 → LED', '330 Ом → GND']].map(([left, right]) => <tr key={left}><td>{left}</td><td>{right}</td></tr>)}</tbody></table><p>FMT, SCK, DEMP, FLT → GND. XSMT → 3.3 V. Прошивка уменьшает уровень ЦАП для PAM8403 и передаёт полный моносигнал на оба выхода, чтобы один динамик воспроизводил оба канала музыки.</p></section>
    <section className="hardware-card"><h2>Проверка звука</h2><p>Сначала запустите музыку с выключенным микрофоном. Затем откройте микрофон и проверьте его уровень. Все три регулятора работают от 0 до 100; кнопки тишины сохраняют текущую громкость.</p><p>Если при малой громкости остаётся хрип, проверьте питание 5 V, общую землю и динамик. Обновлённые сервер и прошивку необходимо использовать вместе: поток теперь 48 кГц.</p><a href="/debug/radio">Открыть диагностику эфира →</a></section>
  </div></main>;
}
