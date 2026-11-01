import React, { useState, useEffect, useRef, useCallback } from 'react';
import Icon from '../Icon/Icon';
import axios from 'axios';

function TracksManager() {
  const [tracks, setTracks] = useState([]);
  const [selectedTrack, setSelectedTrack] = useState(null);
  const [editForm, setEditForm] = useState({
    id: null,
    filename: '',
    title: '',
    artist: '',
    description: '',
    cover: '',
    created_date: '',
    is_public: 'yes',
    track_texts: []
  });
  const [originalTrack, setOriginalTrack] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState({ text: '', type: '' });
  
  // Refs для файловых инпутов
  const mp3InputRef = useRef(null);
  const coverInputRef = useRef(null);
  const [uploadingFile, setUploadingFile] = useState(false);

  const showMessage = useCallback((text, type) => {
    setMessage({ text, type });
    setTimeout(() => setMessage({ text: '', type: '' }), 3000);
  }, []);

  const loadTracks = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await axios.get('/api/tracks');
      setTracks(response.data);
    } catch (error) {
      console.error('Ошибка загрузки треков:', error);
      showMessage('Ошибка загрузки треков', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [showMessage]);

  useEffect(() => {
    loadTracks();
  }, [loadTracks]);

  const handleSelectTrack = (track) => {
    setSelectedTrack(track);
    const formCopy = {
      id: track.id,
      filename: track.filename || '',
      title: track.title || '',
      artist: track.artist || '',
      description: track.description || '',
      cover: track.cover || '',
      created_date: track.created_date || '',
      is_public: track.is_public || 'yes',
      track_texts: track.track_texts ? [...track.track_texts] : []
    };
    setEditForm(formCopy);
    setOriginalTrack(JSON.parse(JSON.stringify(formCopy)));
  };

  const handleFormChange = (field, value) => {
    setEditForm(prev => ({ ...prev, [field]: value }));
  };

  const handleTextChange = (index, field, value) => {
    const updatedTexts = [...editForm.track_texts];
    updatedTexts[index] = { ...updatedTexts[index], [field]: value };
    setEditForm(prev => ({ ...prev, track_texts: updatedTexts }));
  };

  const addTextFile = () => {
    const newId = editForm.track_texts.length > 0 
      ? Math.max(...editForm.track_texts.map(t => t.id)) + 1 
      : 1;
    setEditForm(prev => ({
      ...prev,
      track_texts: [
        ...prev.track_texts,
        { id: newId, title: 'Новый текст', filename: '', language: 'ru' }
      ]
    }));
  };

  const removeTextFile = (index) => {
    const updatedTexts = editForm.track_texts.filter((_, i) => i !== index);
    setEditForm(prev => ({ ...prev, track_texts: updatedTexts }));
  };

  // Загрузка MP3 файла
  const handleUploadMp3 = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    setUploadingFile(true);
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await axios.post('/api/upload/mp3', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (response.data.success) {
        handleFormChange('filename', response.data.filename);
        showMessage('MP3 файл загружен', 'success');
      }
    } catch (error) {
      console.error('Ошибка загрузки MP3:', error);
      showMessage('Ошибка загрузки MP3 файла', 'error');
    } finally {
      setUploadingFile(false);
      if (mp3InputRef.current) mp3InputRef.current.value = '';
    }
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

  // Загрузка текста для конкретного текстового файла
  const handleUploadText = async (event, index) => {
    const file = event.target.files[0];
    if (!file) return;
    
    setUploadingFile(true);
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await axios.post('/api/upload/text', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (response.data.success) {
        handleTextChange(index, 'filename', response.data.filename);
        showMessage('Текст загружен', 'success');
      }
    } catch (error) {
      console.error('Ошибка загрузки текста:', error);
      showMessage('Ошибка загрузки текста', 'error');
    } finally {
      setUploadingFile(false);
    }
  };

  const handleSave = async () => {
    setIsLoading(true);
    try {
      // Если это новый трек (id отрицательный или отсутствует в списке)
      const isNew = !tracks.some(t => t.id === editForm.id);
      
      let response;
      if (isNew) {
        response = await axios.post('/api/tracks', editForm);
      } else {
        response = await axios.put(`/api/tracks/${editForm.id}`, editForm);
      }
      
      if (response.data.success) {
        await loadTracks();
        const savedTrack = response.data.track;
        setSelectedTrack(savedTrack);
        const formCopy = {
          id: savedTrack.id,
          filename: savedTrack.filename || '',
          title: savedTrack.title || '',
          artist: savedTrack.artist || '',
          description: savedTrack.description || '',
          cover: savedTrack.cover || '',
          created_date: savedTrack.created_date || '',
          is_public: savedTrack.is_public || 'yes',
          track_texts: savedTrack.track_texts ? [...savedTrack.track_texts] : []
        };
        setEditForm(formCopy);
        setOriginalTrack(JSON.parse(JSON.stringify(formCopy)));
        showMessage(isNew ? 'Трек создан!' : 'Трек сохранён!', 'success');
      }
    } catch (error) {
      console.error('Ошибка сохранения:', error);
      showMessage('Ошибка сохранения трека', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    if (originalTrack) {
      setEditForm(JSON.parse(JSON.stringify(originalTrack)));
      showMessage('Изменения отменены', 'info');
    }
  };

  const handleDelete = async () => {
    if (!selectedTrack) return;
    
    if (window.confirm(`Удалить трек "${selectedTrack.title}"?`)) {
      setIsLoading(true);
      try {
        await axios.delete(`/api/tracks/${editForm.id}`);
        await loadTracks();
        setSelectedTrack(null);
        setEditForm({
          id: null,
          filename: '',
          title: '',
          artist: '',
          description: '',
          cover: '',
          created_date: '',
          is_public: 'yes',
          track_texts: []
        });
        setOriginalTrack(null);
        showMessage('Трек удалён', 'success');
      } catch (error) {
        console.error('Ошибка удаления:', error);
        showMessage('Ошибка удаления трека', 'error');
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleAddTrack = () => {
    const newTrack = {
      id: -Date.now(), // Временный отрицательный ID для нового трека
      filename: '',
      title: 'Новый трек',
      artist: 'Неизвестный исполнитель',
      description: '',
      cover: '',
      created_date: new Date().toISOString().split('T')[0],
      is_public: 'yes',
      track_texts: []
    };
    
    setSelectedTrack(newTrack);
    setEditForm(JSON.parse(JSON.stringify(newTrack)));
    setOriginalTrack(JSON.parse(JSON.stringify(newTrack)));
    showMessage('Создан новый трек. Загрузите MP3 файл и заполните поля.', 'info');
  };

  return (
    <div className="tracks-management">
      {message.text && (
        <div className={`message-toast ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="two-column-layout">
        {/* Левая колонка - список треков */}
        <div className="tracks-list-column">
          <div className="tracks-list-header">
            <h3>Все треки</h3>
            <span className="tracks-count">{tracks.length} треков</span>
          </div>
          
          <div className="tracks-list-scroll">
            {isLoading && tracks.length === 0 ? (
              <div className="loading-placeholder">Загрузка...</div>
            ) : (
              tracks.map(track => (
                <div 
                  key={track.id}
                  className={`track-list-item ${selectedTrack?.id === track.id ? 'active' : ''}`}
                  onClick={() => handleSelectTrack(track)}
                >
                  <div className="track-list-cover">
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
                  <div className="track-list-info">
                    <div className="track-list-title">{track.title}</div>
                    <div className="track-list-artist">{track.artist}</div>
                  </div>
                </div>
              ))
            )}
          </div>
          
          <button className="add-track-btn" onClick={handleAddTrack}>
            <Icon name="add" type="emoji" size={18} />
            Добавить трек
          </button>
        </div>

        {/* Правая колонка - редактирование */}
        <div className="track-edit-column">
          {selectedTrack ? (
            <div className="track-edit-form">
              <div className="form-header">
                <h3>Редактирование трека</h3>
                <button className="delete-track-btn" onClick={handleDelete}>
                  <Icon name="close" type="emoji" size={16} />
                  Удалить
                </button>
              </div>

              <div className="form-scroll">
                {/* Основная информация */}
                <div className="form-section">
                  <h4>Основная информация</h4>
                  
                  <div className="form-row">
                    <div className="form-group">
                      <label>Название трека *</label>
                      <input
                        type="text"
                        value={editForm.title}
                        onChange={(e) => handleFormChange('title', e.target.value)}
                        placeholder="Введите название"
                      />
                    </div>
                    
                    <div className="form-group">
                      <label>Исполнитель *</label>
                      <input
                        type="text"
                        value={editForm.artist}
                        onChange={(e) => handleFormChange('artist', e.target.value)}
                        placeholder="Введите исполнителя"
                      />
                    </div>
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label>MP3 файл</label>
                      <div className="file-input-group">
                        <input
                          type="text"
                          value={editForm.filename}
                          onChange={(e) => handleFormChange('filename', e.target.value)}
                          placeholder="track.mp3"
                          readOnly
                        />
                        <input
                          type="file"
                          ref={mp3InputRef}
                          accept=".mp3,.wav,.ogg,.m4a"
                          onChange={handleUploadMp3}
                          style={{ display: 'none' }}
                        />
                        <button 
                          type="button"
                          className="file-select-btn"
                          onClick={() => mp3InputRef.current?.click()}
                          disabled={uploadingFile}
                        >
                          <Icon name="upload" type="emoji" size={14} />
                          {uploadingFile ? 'Загрузка...' : 'Выбрать MP3'}
                        </button>
                      </div>
                      <small>MP3 файл будет сохранён в папке music_files/</small>
                    </div>
                    
                    <div className="form-group">
                      <label>Дата создания</label>
                      <input
                        type="date"
                        value={editForm.created_date || ''}
                        onChange={(e) => handleFormChange('created_date', e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="form-group full-width">
                    <label>Описание трека</label>
                    <textarea
                      value={editForm.description || ''}
                      onChange={(e) => handleFormChange('description', e.target.value)}
                      rows="3"
                      placeholder="Описание трека..."
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
                      </select>
                    </div>
                  </div>
                </div>

                {/* Тексты песен */}
                <div className="form-section">
                  <div className="section-header">
                    <h4>Тексты песен</h4>
                    <button className="add-text-btn" onClick={addTextFile}>
                      <Icon name="add" type="emoji" size={14} />
                      Добавить текст
                    </button>
                  </div>
                  
                  {editForm.track_texts.length === 0 ? (
                    <div className="empty-texts">
                      <Icon name="musicNote" type="emoji" size={24} />
                      <p>Нет добавленных текстов</p>
                    </div>
                  ) : (
                    editForm.track_texts.map((text, index) => (
                      <div key={text.id} className="text-file-item">
                        <div className="text-header">
                          <span className="text-title">Текст #{index + 1}</span>
                          <button 
                            className="remove-text-btn"
                            onClick={() => removeTextFile(index)}
                          >
                            <Icon name="close" type="emoji" size={12} />
                          </button>
                        </div>
                        <div className="form-row">
                          <div className="form-group">
                            <label>Название текста</label>
                            <input
                              type="text"
                              value={text.title || ''}
                              onChange={(e) => handleTextChange(index, 'title', e.target.value)}
                              placeholder="Оригинальный текст"
                            />
                          </div>
                          <div className="form-group">
                            <label>Язык</label>
                            <select
                              value={text.language || 'ru'}
                              onChange={(e) => handleTextChange(index, 'language', e.target.value)}
                            >
                              <option value="ru">Русский</option>
                              <option value="en">Английский</option>
                              <option value="kk">Казахский</option>
                              <option value="de">Немецкий</option>
                              <option value="fr">Французский</option>
                            </select>
                          </div>
                        </div>
                        <div className="form-group full-width">
                          <label>Файл текста (.txt)</label>
                          <div className="file-input-group">
                            <input
                              type="text"
                              value={text.filename || ''}
                              onChange={(e) => handleTextChange(index, 'filename', e.target.value)}
                              placeholder="1.1.txt"
                              readOnly
                            />
                            <input
                              type="file"
                              accept=".txt"
                              onChange={(e) => handleUploadText(e, index)}
                              style={{ display: 'none' }}
                              id={`text-upload-${index}`}
                            />
                            <button 
                              type="button"
                              className="file-select-btn"
                              onClick={() => document.getElementById(`text-upload-${index}`).click()}
                              disabled={uploadingFile}
                            >
                              <Icon name="upload" type="emoji" size={14} />
                              Выбрать .txt
                            </button>
                          </div>
                          <small>Текстовый файл будет сохранён в папке track_texts/</small>
                        </div>
                      </div>
                    ))
                  )}
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
            <div className="no-track-selected">
              <Icon name="musicNote" type="png" size={48} />
              <h3>Трек не выбран</h3>
              <p>Выберите трек из списка слева или создайте новый</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default TracksManager;