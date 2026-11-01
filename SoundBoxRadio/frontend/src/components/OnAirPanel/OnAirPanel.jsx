import { useState } from 'react';

function Channel({ title, subtitle, volume, muted, peak, onVolume, onMute, children }) {
  return <section className={`channel-strip ${muted ? 'muted' : ''}`}>
    <div className="channel-title"><h3>{title}</h3><span>{muted ? 'ВЫКЛ' : 'ВКЛ'}</span></div>
    <p>{subtitle}</p>
    <div className="channel-meter" role="meter" aria-label={`Уровень: ${title}`} aria-valuenow={peak || 0} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${Math.min(100, peak || 0)}%` }} /></div>
    <label className="fader-label">Громкость <output>{volume ?? 0}<small>%</small></output>
      <input aria-label={`Громкость: ${title}`} type="range" min="0" max="100" value={volume ?? 0} onChange={event => onVolume(Number(event.target.value))} />
    </label>
    <div className="fader-scale"><span>0 · тишина</span><span>100</span></div>
    <button className={`channel-mute ${muted ? 'engaged' : ''}`} aria-pressed={Boolean(muted)} onClick={onMute}>{muted ? 'Вернуть звук' : 'Отключить звук'}</button>
    {children}
  </section>;
}

export default function OnAirPanel({ status, tracks, playlists, devices, device, setDevice,
  pending, connected, changeLevels, playTrack, playPlaylist, toggleMic, panic, refresh }) {
  const [tab, setTab] = useState('tracks');
  const [search, setSearch] = useState('');
  const collection = tab === 'tracks' ? tracks : playlists;
  const filtered = collection.filter(item => `${item.title || item.name} ${item.artist || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <main className="studio-main">
    <section className="broadcast-banner">
      <div><span className={`onair-tag ${status.is_live ? 'live' : ''}`}><i />{status.is_live ? 'В ЭФИРЕ' : 'ОЖИДАНИЕ'}</span><h1>Пульт вещания</h1><p>Музыка и голос в одном эфире. Каждый источник управляется отдельно.</p></div>
      <button className="panic-button" onClick={panic} disabled={!connected}>■ Снять всё с эфира</button>
    </section>
    <div className="studio-layout">
      <div className="desk-column">
        <section className="playing-summary">
          {status.current_track?.cover ? <img src={`/api/cover/${encodeURIComponent(status.current_track.cover)}`} alt="Обложка трека" /> : <div className="record-placeholder">♫</div>}
          <div><small>СЕЙЧАС ИГРАЕТ</small><h2>{status.current_track?.title || (status.mic_active ? 'Прямой эфир с микрофона' : 'Выберите трек для эфира')}</h2><p>{status.current_track?.artist || 'Библиотека находится справа'}</p>{status.current_playlist && <small>Плейлист: {status.current_playlist.name}</small>}</div>
        </section>
        <div className="mixing-desk">
          <Channel title="Музыка" subtitle="Текущий трек или плейлист" volume={status.music_volume} muted={status.music_muted} peak={status.music_peak}
            onVolume={music_volume => changeLevels({ music_volume })} onMute={() => changeLevels({ music_muted: !status.music_muted })}>
            <span className="channel-status">{status.current_track ? 'Трек воспроизводится' : 'Источник ожидает трек'}</span>
          </Channel>
          <Channel title="Микрофон" subtitle="Звук с компьютера сервера" volume={status.mic_volume} muted={status.mic_muted} peak={status.mic_peak}
            onVolume={mic_volume => changeLevels({ mic_volume })} onMute={() => changeLevels({ mic_muted: !status.mic_muted })}>
            <label className="device-label">Устройство записи<select aria-label="Устройство записи" value={device} disabled={status.mic_active || Boolean(pending)} onChange={event => setDevice(event.target.value)}><option value="">По умолчанию в Windows</option>{devices.map(item => <option key={item.id} value={item.id}>{item.name} · {item.host}{item.default ? ' · основное' : ''}</option>)}</select></label>
            <button className={`mic-capture ${status.mic_active ? 'capturing' : ''}`} disabled={Boolean(pending) || !connected} onClick={toggleMic}>{pending === 'mic' ? 'Подключение…' : status.mic_active ? '■ Выключить микрофон' : '● Включить микрофон'}</button>
          </Channel>
          <Channel title="Эфир" subtitle="Общий выход на приёмники" volume={status.master_volume} muted={status.output_muted} peak={status.output_peak}
            onVolume={master_volume => changeLevels({ master_volume })} onMute={() => changeLevels({ output_muted: !status.output_muted })}>
            <div className="limiter-info"><span className="safe-dot" />Защита от перегрузки<small>{status.limiter_db > 0 ? `Снижение пиков: ${status.limiter_db} дБ` : 'Запас по уровню есть'}</small></div>
          </Channel>
        </div>
        <aside className="studio-tip">Микрофон и музыка звучат одновременно. «Отключить звук» сохраняет источник, а красная кнопка останавливает музыку и захват микрофона. Для проверки микрофона используйте наушники.</aside>
      </div>
      <section className="studio-library">
        <div className="library-heading"><h2>Библиотека</h2><button onClick={refresh} aria-label="Обновить библиотеку">↻</button></div>
        <div className="library-tabs"><button className={tab === 'tracks' ? 'selected' : ''} onClick={() => setTab('tracks')}>Треки <small>{tracks.length}</small></button><button className={tab === 'playlists' ? 'selected' : ''} onClick={() => setTab('playlists')}>Плейлисты <small>{playlists.length}</small></button></div>
        <input className="library-search" type="search" aria-label="Поиск в библиотеке" placeholder="Найти название или исполнителя…" value={search} onChange={event => setSearch(event.target.value)} />
        <div className="library-list">{filtered.map(item => <button key={item.id} className={`library-row ${tab === 'tracks' && status.current_track?.id === item.id ? 'current' : ''}`} disabled={Boolean(pending) || !connected} onClick={() => tab === 'tracks' ? playTrack(item.id) : playPlaylist(item.id)}>
          {item.cover ? <img loading="lazy" src={`/api/cover/${encodeURIComponent(item.cover)}`} alt="" /> : <span className="library-placeholder">♫</span>}<span className="library-track-text"><strong>{item.title || item.name}</strong><small>{item.artist || `${item.track_ids?.length || 0} треков`}</small></span><span className="library-play">▶</span>
        </button>)}{!filtered.length && <p className="library-empty">{collection.length ? 'По этому запросу ничего нет' : 'Добавьте записи в разделе «Медиатека»'}</p>}</div>
      </section>
    </div>
  </main>;
}
