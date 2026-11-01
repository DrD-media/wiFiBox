import { useState } from 'react';
import TracksManager from './TracksManager';
import PlaylistsManager from './PlaylistsManager';
import './ContentManager.css';

export default function ContentManager() {
  const [tab, setTab] = useState('tracks');
  return <main className="content-manager">
    <div className="content-manager-container">
      <nav className="content-tabs" aria-label="Медиатека">
        <button className={`content-tab-btn ${tab === 'tracks' ? 'active' : ''}`} onClick={() => setTab('tracks')}>Треки</button>
        <button className={`content-tab-btn ${tab === 'playlists' ? 'active' : ''}`} onClick={() => setTab('playlists')}>Плейлисты</button>
      </nav>
      <div className="content-tab-panels">{tab === 'tracks' ? <TracksManager /> : <PlaylistsManager />}</div>
    </div>
  </main>;
}
