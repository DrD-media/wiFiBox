import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import OnAirPanel from './components/OnAirPanel/OnAirPanel';
import ContentManager from './components/ContentManager/ContentManager';
import EquipmentManager from './components/EquipmentManager/EquipmentManager';
import DebugRadio from './components/DebugRadio/DebugRadio';
import './App.css';

axios.defaults.timeout = 4000;
const levelFields = ['music_volume', 'mic_volume', 'master_volume', 'music_muted', 'mic_muted', 'output_muted'];

export default function App() {
  const [status, setStatus] = useState({ music_volume: 70, mic_volume: 70, master_volume: 80 });
  const [tracks, setTracks] = useState([]);
  const [playlists, setPlaylists] = useState([]);
  const [devices, setDevices] = useState([]);
  const [device, setDevice] = useState('');
  const [panel, setPanel] = useState('studio');
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState('');
  const queuedLevels = useRef({});
  const sendingLevels = useRef(false);
  const levelTimer = useRef(null);

  const applyStatus = useCallback(data => {
    setStatus(previous => {
      const next = { ...data };
      if (sendingLevels.current || Object.keys(queuedLevels.current).length) {
        levelFields.forEach(key => { next[key] = previous[key]; });
      }
      return next;
    });
  }, []);

  const loadCatalog = useCallback(async () => {
    try {
      const [music, lists] = await Promise.all([axios.get('/api/tracks'), axios.get('/api/playlists')]);
      setTracks(music.data); setPlaylists(lists.data);
    } catch (cause) { setError(cause.response?.data?.error || 'Не удалось загрузить библиотеку'); }
  }, []);

  useEffect(() => {
    loadCatalog();
    axios.get('/api/radio/mics').then(response => setDevices(response.data))
      .catch(cause => setError(cause.response?.data?.error || 'Не удалось прочитать список микрофонов'));
    let active = true, timer;
    const poll = async () => {
      try {
        const response = await axios.get('/api/radio/status', { timeout: 2000 });
        if (active) { applyStatus(response.data); setConnected(true); }
      } catch { if (active) setConnected(false); }
      if (active) timer = setTimeout(poll, 600);
    };
    poll();
    return () => { active = false; clearTimeout(timer); clearTimeout(levelTimer.current); };
  }, [applyStatus, loadCatalog]);

  const sendLevels = async () => {
    if (sendingLevels.current) return;
    sendingLevels.current = true;
    try {
      while (Object.keys(queuedLevels.current).length) {
        const patch = queuedLevels.current;
        queuedLevels.current = {};
        await axios.post('/api/radio/levels', patch);
      }
    } catch (cause) {
      queuedLevels.current = {};
      setError(cause.response?.data?.error || 'Не удалось изменить громкость');
    } finally { sendingLevels.current = false; }
  };

  const changeLevels = patch => {
    setStatus(previous => ({ ...previous, ...patch }));
    queuedLevels.current = { ...queuedLevels.current, ...patch };
    clearTimeout(levelTimer.current);
    if (Object.keys(patch).some(key => key.endsWith('_muted'))) sendLevels();
    else levelTimer.current = setTimeout(sendLevels, 80);
  };

  const action = async (name, url, body, urgent = false) => {
    if (pending && !urgent) return;
    setPending(name); setError('');
    try {
      await axios.post(url, body);
      const response = await axios.get('/api/radio/status');
      applyStatus(response.data); setConnected(true);
    } catch (cause) { setError(cause.response?.data?.error || cause.message || 'Ошибка управления эфиром'); }
    finally { setPending(''); }
  };

  const studio = <div className="studio-app">
    <header className="studio-header">
      <a className="studio-brand" href="/"><span className="brand-mark">◉</span><span>SoundBox<span className="brand-light">Radio</span><small>Локальная радиостудия</small></span></a>
      <nav aria-label="Разделы">
        {[['studio', 'Эфир'], ['library', 'Медиатека'], ['hardware', 'Подключение']].map(([key, label]) =>
          <button key={key} className={panel === key ? 'selected' : ''} onClick={() => { setPanel(key); if (key === 'studio') loadCatalog(); }}>{label}</button>)}
      </nav>
      <span className={`connection-pill ${connected ? 'online' : ''}`}><i />{connected ? 'Сервер доступен' : 'Нет связи с сервером'}</span>
    </header>
    {!connected && <div className="studio-notice" role="status">Ожидаем локальный сервер. Соединение восстановится автоматически.</div>}
    {(error || status.last_error || status.mic_error) && <div className="studio-notice error" role="alert"><span>{error || status.mic_error || status.last_error}</span><button aria-label="Закрыть сообщение" onClick={() => setError('')}>×</button></div>}
    {panel === 'studio' && <OnAirPanel status={status} tracks={tracks} playlists={playlists}
      devices={devices} device={device} setDevice={setDevice} pending={pending} connected={connected}
      changeLevels={changeLevels} refresh={loadCatalog}
      playTrack={id => action('track', `/api/radio/play/${id}`)}
      playPlaylist={id => action('playlist', `/api/radio/playlist/${id}`)}
      toggleMic={() => action('mic', '/api/radio/mic', { action: status.mic_active ? 'off' : 'on', device_index: device === '' ? null : Number(device) })}
      panic={() => { clearTimeout(levelTimer.current); queuedLevels.current = {}; action('panic', '/api/radio/stop', {}, true); }} />}
    {panel === 'library' && <ContentManager />}
    {panel === 'hardware' && <EquipmentManager />}
    <footer className="studio-footer"><span>48 кГц · PCM · локальная сеть</span><span>{status.listeners || 0} подключений · выход {status.output_peak || 0}%</span><a href="/debug/radio">Прослушивание и диагностика ↗</a></footer>
  </div>;

  return <BrowserRouter><Routes>
    <Route path="/" element={studio} />
    <Route path="/debug/radio" element={<DebugRadio />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></BrowserRouter>;
}
