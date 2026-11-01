import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import './DebugRadio.css';

const streamUrl = '/api/radio/stream.wav';

export default function DebugRadio() {
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(false);
  const [audioError, setAudioError] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [reconnects, setReconnects] = useState(0);
  const audio = useRef(null);
  const wantsAudio = useRef(false);
  const retryTimer = useRef(null);
  const attempts = useRef(0);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await axios.get('/api/radio/status', { timeout: 4000 });
        if (active) { setStatus(response.data); setStatusError(false); }
      } catch {
        if (active) setStatusError(true);
      }
    };
    refresh();
    const interval = setInterval(refresh, 2000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  useEffect(() => () => {
    wantsAudio.current = false;
    clearTimeout(retryTimer.current);
    if (audio.current) { audio.current.pause(); audio.current.src = ''; }
  }, []);

  const connect = async () => {
    clearTimeout(retryTimer.current);
    if (audio.current) { audio.current.pause(); audio.current.src = ''; }
    const player = new Audio(streamUrl);
    audio.current = player;
    player.onplaying = () => { attempts.current = 0; setPlaying(true); setAudioError(null); };
    player.onpause = () => setPlaying(false);
    player.onerror = () => {
      setPlaying(false);
      setAudioError('Поток прервался. Пробуем восстановить соединение.');
      if (wantsAudio.current) {
        attempts.current += 1;
        retryTimer.current = setTimeout(() => {
          setReconnects(value => value + 1);
          connect();
        }, Math.min(1000 * 2 ** attempts.current, 10000));
      }
    };
    try { await player.play(); }
    catch (error) {
      if (error.name !== 'AbortError') {
        setAudioError(`Не удалось воспроизвести поток: ${error.message}`);
        wantsAudio.current = false;
      }
    }
  };

  const toggle = () => {
    if (wantsAudio.current) {
      wantsAudio.current = false;
      clearTimeout(retryTimer.current);
      audio.current?.pause();
      setPlaying(false);
    } else {
      wantsAudio.current = true;
      attempts.current = 0;
      connect();
    }
  };

  return <main className="debug-radio-container">
    <div className="debug-radio-card">
      <div className="debug-header"><h1>Диагностика эфира</h1><a href="/">Панель управления</a></div>
      <div className="stream-info"><div className="info-row"><span className="info-label">Поток для браузера</span><code className="stream-url">{new URL(streamUrl, window.location.href).href}</code></div></div>
      <div className="player-section">
        <div className="status-indicator"><span className={`status-led ${status?.is_live ? 'live' : 'offline'}`}>{status?.is_live ? '🔴 Эфир работает' : '○ Эфир не активен'}</span><span className="now-playing">{status?.current_track ? `${status.current_track.title} — ${status.current_track.artist}` : status?.mic_active ? 'Микрофон' : 'Ожидание источника'}</span></div>
        <div className="audio-controls"><button className="play-button" onClick={toggle}>{playing ? 'Остановить прослушивание' : 'Слушать эфир'}</button><button className="refresh-button" onClick={() => { wantsAudio.current = true; attempts.current = 0; connect(); }}>Переподключить</button></div>
        {(audioError || statusError || status?.last_error || status?.mic_error) && <div className="error-message" role="alert">{audioError || (statusError ? 'Нет связи с сервером' : status?.mic_error || status?.last_error)}</div>}
      </div>
      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">Слушателей</div><div className="stat-value">{status?.listeners ?? '—'}</div></div>
        <div className="stat-card"><div className="stat-label">Буфер музыки</div><div className="stat-value">{status?.queue_size ?? '—'}</div></div>
        <div className="stat-card"><div className="stat-label">Микрофон</div><div className="stat-value">{status?.mic_active ? 'ВКЛ' : 'ВЫКЛ'}</div></div>
        <div className="stat-card"><div className="stat-label">Пропущено кадров</div><div className="stat-value">{status?.dropped_frames ?? '—'}</div></div>
        <div className="stat-card"><div className="stat-label">Нехватка музыки</div><div className="stat-value">{status?.music_underruns ?? '—'}</div></div>
        <div className="stat-card"><div className="stat-label">Сбои захвата</div><div className="stat-value">{status?.mic_overflows ?? '—'}</div></div>
        <div className="stat-card"><div className="stat-label">Выход</div><div className="stat-value">{status?.output_peak ?? 0}%</div></div>
        <div className="stat-card"><div className="stat-label">Ограничение пиков</div><div className="stat-value">{status?.limiter_db ?? 0} дБ</div></div>
      </div>
      {reconnects > 0 && <p>Переподключений: {reconnects}</p>}
      <p>ESP32: <code>{new URL('/api/radio/stream', window.location.href).href}</code></p>
      <p>48 кГц · 16 бит · стерео. Задержка браузерного прослушивания зависит от браузера и отличается от задержки приёмника.</p>
    </div>
  </main>;
}
