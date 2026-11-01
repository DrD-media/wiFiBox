import React, { useState, useEffect, useRef, useCallback } from 'react';
import Icon from '../Icon/Icon';
import axios from 'axios';

function PlaylistsManager() {
  const [playlists, setPlaylists] = useState([]);
  const [allTracks, setAllTracks] = useState([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [editForm, setEditForm] = useState({
    id: null,
    name: '',
    description: '',
    cover: '',
    type: 'user',
    owner_id: 1,
    is_public: 'yes',
    track_ids: []
  });
  const [originalPlaylist, setOriginalPlaylist] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState({ text: '', type: '' });
  
  // Refs для файловых инпутов
  const coverInputRef = useRef(null);
  const [uploadingFile, setUploadingFile] = useState(false);

  const showMessage = useCallback((text, type) => {
    setMessage({ text, type });
    setTimeout(() => setMessage({ text: '', type: '' }), 3000);
  }, []);

  const loadPlaylists = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await axios.get('/api/playlists');
      setPlaylists(response.data);
    } catch (error) {
      console.error('Ошибка загрузки плейлистов:', error);
      showMessage('Ошибка загрузки плейлистов', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [showMessage]);

  const loadAllTracks = useCallback(async () => {
    try {
      const response = await axios.get('/api/tracks');
      setAllTracks(response.data);
    } catch (error) {
      console.error('Ошибка загрузки треков:', error);
    }
  }, []);

  useEffect(() => {
    loadPlaylists();
    loadAllTracks();
  }, [loadPlaylists, loadAllTracks]);

  const handleSelectPlaylist = (playlist) => {
    setSelectedPlaylist(playlist);
    const formCopy = {
      id: playlist.id,
      name: playlist.name || '',
      description: playlist.description || '',
      cover: playlist.cover || '',
      type: playlist.type || 'user',
      owner_id: playlist.owner_id || 1,
      is_public: playlist.is_public || 'yes',
      track_ids: playlist.track_ids ? [...playlist.track_ids] : []
    };
    setEditForm(formCopy);
    setOriginalPlaylist(JSON.parse(JSON.stringify(formCopy)));
  };

  const handleFormChange = (field, value) => {
    setEditForm(prev => ({ ...prev, [field]: value }));
  };

  // Загрузка обложки
  const handleUploadCover = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    setUploadingFile(true);
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await axios.post('/api/upload/cover', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (response.data.success) {
        handleFormChange('cover', response.data.filename);
        showMessage('Обложка загружена', 'success');
      }
    } catch (error) {
      console.error('Ошибка загрузки обложки:', error);
      showMessage('Ошибка загрузки обложки', 'error');
    } finally {
      setUploadingFile(false);
      if (coverInputRef.current) coverInputRef.current.value = '';
    }
  };

  // Добавление трека в плейлист
  const addTrackToPlaylist = (trackId) => {
    if (editForm.track_ids.includes(trackId)) {
      showMessage('Трек уже в плейлисте', 'info');
      return;
    }
    setEditForm(prev => ({
      ...prev,
      track_ids: [...prev.track_ids, trackId]
    }));
  };

  // Удаление трека из плейлиста
  const removeTrackFromPlaylist = (trackId) => {
    setEditForm(prev => ({
      ...prev,
      track_ids: prev.track_ids.filter(id => id !== trackId)
    }));
  };

  // Перемещение трека вверх/вниз
  const moveTrack = (index, direction) => {
    const newTrackIds = [...editForm.track_ids];
    const newIndex = direction === 'up' ? index - 1 : index + 1;
    
    if (newIndex < 0 || newIndex >= newTrackIds.length) return;
    
    [newTrackIds[index], newTrackIds[newIndex]] = [newTrackIds[newIndex], newTrackIds[index]];
    setEditForm(prev => ({ ...prev, track_ids: newTrackIds }));
  };

  const handleSave = async () => {
    setIsLoading(true);
    try {
      const isNew = !playlists.some(p => p.id === editForm.id);
      
      // Обновляем дату последнего изменения
      const saveData = {
        ...editForm,
        last_updated: new Date().toISOString().split('T')[0]
      };
      
      let response;
      if (isNew) {
        response = await axios.post('/api/playlists', saveData);
      } else {
        response = await axios.put(`/api/playlists/${editForm.id}`, saveData);
      }
      
      if (response.data.success) {
        await loadPlaylists();
        const savedPlaylist = response.data.playlist;
        setSelectedPlaylist(savedPlaylist);
        const formCopy = {
          id: savedPlaylist.id,
          name: savedPlaylist.name || '',
          description: savedPlaylist.description || '',
          cover: savedPlaylist.cover || '',
          type: savedPlaylist.type || 'user',
          owner_id: savedPlaylist.owner_id || 1,
          is_public: savedPlaylist.is_public || 'yes',
          track_ids: savedPlaylist.track_ids || []
        };
        setEditForm(formCopy);
        setOriginalPlaylist(JSON.parse(JSON.stringify(formCopy)));
        showMessage(isNew ? 'Плейлист создан!' : 'Плейлист сохранён!', 'success');
      }
    } catch (error) {
      console.error('Ошибка сохранения:', error);
      showMessage('Ошибка сохранения плейлиста', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    if (originalPlaylist) {
      setEditForm(JSON.parse(JSON.stringify(originalPlaylist)));
      showMessage('Изменения отменены', 'info');
    }
  };

  const handleDelete = async () => {
    if (!selectedPlaylist) return;
    
    if (window.confirm(`Удалить плейлист "${selectedPlaylist.name}"?`)) {
      setIsLoading(true);
      try {
        await axios.delete(`/api/playlists/${editForm.id}`);
        await loadPlaylists();
        setSelectedPlaylist(null);
        setEditForm({
          id: null,
          name: '',
          description: '',
          cover: '',
          type: 'user',
          owner_id: 1,
          is_public: 'yes',
          track_ids: []
        });
        setOriginalPlaylist(null);
        showMessage('Плейлист удалён', 'success');
      } catch (error) {
        console.error('Ошибка удаления:', error);
        showMessage('Ошибка удаления плейлиста', 'error');
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleAddPlaylist = () => {
    const newPlaylist = {
      id: -Date.now(),
      name: 'Новый плейлист',
      description: '',
      cover: '',
      type: 'user',
      owner_id: 1,
      is_public: 'yes',
      track_ids: []
    };
    
    setSelectedPlaylist(newPlaylist);
    setEditForm(JSON.parse(JSON.stringify(newPlaylist)));
    setOriginalPlaylist(JSON.parse(JSON.stringify(newPlaylist)));
    showMessage('Создан новый плейлист. Заполните поля и добавьте треки.', 'info');
  };

  // Получение информации о треке по ID
  const getTrackById = (trackId) => {
    return allTracks.find(t => t.id === trackId);
  };

  // Треки не входящие в плейлист
  const availableTracks = allTracks.filter(track => !editForm.track_ids.includes(track.id));

  return (
    <div className="playlists-management">
      {message.text && (
        <div className={`message-toast ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="two-column-layout">
        {/* Левая колонка - список плейлистов */}
        <div className="playlists-list-column">
          <div className="playlists-list-header">
            <h3>Все плейлисты</h3>
            <span className="playlists-count">{playlists.length} плейлистов</span>
          </div>
          
          <div className="playlists-list-scroll">
            {isLoading && playlists.length === 0 ? (
              <div className="loading-placeholder">Загрузка...</div>
            ) : (
              playlists.map(playlist => (
                <div 
                  key={playlist.id}
                  className={`playlist-list-item ${selectedPlaylist?.id === playlist.id ? 'active' : ''}`}
                  onClick={() => handleSelectPlaylist(playlist)}
                >
                  <div className="playlist-list-cover">
                    {playlist.cover ? (
                      <img 
                        src={`/api/cover/${playlist.cover}`}
                        alt={playlist.name}
                        onError={(e) => {
                          e.target.onerror = null;
                          e.target.style.display = 'none';
                        }}
                      />
                    ) : (
                      <div className="mini-placeholder">📋</div>
                    )}
                  </div>
                  <div className="playlist-list-info">
                    <div className="playlist-list-title">{playlist.name}</div>
                    <div className="playlist-list-count">{playlist.track_ids?.length || 0} треков</div>
                  </div>
                </div>
              ))
            )}
          </div>
          
          <button className="add-playlist-btn" onClick={handleAddPlaylist}>
            <Icon name="add" type="emoji" size={18} />
            Создать плейлист
          </button>
        </div>

        {/* Правая колонка - редактирование */}
        <div className="playlist-edit-column">
          {selectedPlaylist ? (
            <div className="playlist-edit-form">
              <div className="form-header">
                <h3>Редактирование плейлиста</h3>
                <button className="delete-playlist-btn" onClick={handleDelete}>
                  <Icon name="close" type="emoji" size={16} />
                  Удалить
                </button>
              </div>

              <div className="form-scroll">
                {/* Основная информация */}
                <div className="form-section">
                  <h4>Основная информация</h4>
                  
                  <div className="form-row">
                    <div className="form-group full-width">
                      <label>Название плейлиста *</label>
                      <input
                        type="text"
                        value={editForm.name}
                        onChange={(e) => handleFormChange('name', e.target.value)}
                        placeholder="Введите название плейлиста"
                      />
                    </div>
                  </div>

                  <div className="form-group full-width">
                    <label>Описание плейлиста</label>
                    <textarea
                      value={editForm.description || ''}
                      onChange={(e) => handleFormChange('description', e.target.value)}
                      rows="3"
                      placeholder="Описание плейлиста..."
                    />
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label>Обложка</label>
                      <div className="file-input-group">
                        <input
                          type="text"
                          value={editForm.cover || ''}
                          onChange={(e) => handleFormChange('cover', e.target.value)}
                          placeholder="cover.jpg"
                          readOnly
                        />
                        <input
                          type="file"
                          ref={coverInputRef}
                          accept=".jpg,.jpeg,.png,.gif,.webp"
                          onChange={handleUploadCover}
                          style={{ display: 'none' }}
                        />
                        <button 
                          type="button"
                          className="file-select-btn"
                          onClick={() => coverInputRef.current?.click()}
                          disabled={uploadingFile}
                        >
                          <Icon name="upload" type="emoji" size={14} />
                          Выбрать обложку
                        </button>
                      </div>
                      <small>Файл обложки будет сохранён в папке covers/</small>
                    </div>
                    
                    <div className="form-group">
                      <label>Доступность</label>
                      <select
                        value={editForm.is_public}
                        onChange={(e) => handleFormChange('is_public', e.target.value)}
                      >
                        <option value="yes">Публичный</option>
                        <option value="no">Приватный</option>
                        <option value="partly">Частичный</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* Управление треками */}
                <div className="form-section tracks-management-section">
                  <h4>Управление треками</h4>
                  
                  <div className="tracks-dual-layout">
                    {/* Левый список - доступные треки */}
                    <div className="available-tracks-panel">
                      <div className="panel-title">
                        <h5>Доступные треки</h5>
                        <span className="tracks-count">{availableTracks.length} треков</span>
                      </div>
                      <div className="tracks-list-scroll">
                        {availableTracks.length === 0 ? (
                          <div className="empty-tracks-list">
                            <Icon name="musicNote" type="emoji" size={24} />
                            <p>Нет доступных треков</p>
                          </div>
                        ) : (
                          availableTracks.map(track => (
                            <div key={track.id} className="track-item available">
                              <div className="track-item-cover">
                                {track.cover ? (
                                  <img 
                                    src={`/api/cover/${track.cover}`}
                                    alt={track.title}
                                    onError={(e) => {
                                      e.target.onerror = null;
                                      e.target.style.display = 'none';
                                    }}
                                  />
                                ) : (
                                  <div className="mini-placeholder">🎵</div>
                                )}
                              </div>
                              <div className="track-item-info">
                                <div className="track-item-title">{track.title}</div>
                                <div className="track-item-artist">{track.artist}</div>
                              </div>
                              <button 
                                className="add-track-btn-mini"
                                onClick={() => addTrackToPlaylist(track.id)}
                                title="Добавить в плейлист"
                              >
                                <Icon name="add" type="emoji" size={14} />
                              </button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>

                    {/* Правый список - треки плейлиста */}
                    <div className="playlist-tracks-panel">
                      <div className="panel-title">
                        <h5>Треки плейлиста</h5>
                        <span className="tracks-count">{editForm.track_ids.length} треков</span>
                      </div>
                      <div className="tracks-list-scroll">
                        {editForm.track_ids.length === 0 ? (
                          <div className="empty-tracks-list">
                            <Icon name="list" type="emoji" size={24} />
                            <p>Нет треков в плейлисте</p>
                            <small>Добавьте треки из левого списка</small>
                          </div>
                        ) : (
                          editForm.track_ids.map((trackId, index) => {
                            const track = getTrackById(trackId);
                            if (!track) return null;
                            return (
                              <div key={trackId} className="track-item playlist-track">
                                <div className="track-order-handle">
                                  <button 
                                    className="move-btn"
                                    onClick={() => moveTrack(index, 'up')}
                                    disabled={index === 0}
                                    title="Переместить вверх"
                                  >
                                    <Icon name="arrowUp" type="emoji" size={12} />
                                  </button>
                                  <span className="track-order">{index + 1}</span>
                                  <button 
                                    className="move-btn"
                                    onClick={() => moveTrack(index, 'down')}
                                    disabled={index === editForm.track_ids.length - 1}
                                    title="Переместить вниз"
                                  >
                                    <Icon name="arrowDown" type="emoji" size={12} />
                                  </button>
                                </div>
                                <div className="track-item-cover">
                                  {track.cover ? (
                                    <img 
                                      src={`/api/cover/${track.cover}`}
                                      alt={track.title}
                                      onError={(e) => {
                                        e.target.onerror = null;
                                        e.target.style.display = 'none';
                                      }}
                                    />
                                  ) : (
                                    <div className="mini-placeholder">🎵</div>
                                  )}
                                </div>
                                <div className="track-item-info">
                                  <div className="track-item-title">{track.title}</div>
                                  <div className="track-item-artist">{track.artist}</div>
                                </div>
                                <button 
                                  className="remove-track-btn-mini"
                                  onClick={() => removeTrackFromPlaylist(trackId)}
                                  title="Удалить из плейлиста"
                                >
                                  <Icon name="close" type="emoji" size={12} />
                                </button>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="form-actions">
                <button className="reset-btn" onClick={handleReset}>
                  <Icon name="refresh" type="svg" size={16} />
                  Сбросить
                </button>
                <button className="save-btn" onClick={handleSave} disabled={isLoading}>
                  {isLoading ? 'Сохранение...' : 'Сохранить изменения'}
                </button>
              </div>
            </div>
          ) : (
            <div className="no-playlist-selected">
              <Icon name="list" type="emoji" size={48} />
              <h3>Плейлист не выбран</h3>
              <p>Выберите плейлист из списка слева или создайте новый</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default PlaylistsManager;