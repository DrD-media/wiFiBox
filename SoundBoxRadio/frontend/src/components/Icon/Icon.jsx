import React, { useState } from 'react';

const ICONS = {
  play: '▶️', pause: '⏸️', prev: '⏮️', next: '⏭️',
  loopTrack: '🔁', loopTrackOn: '🔂',
  loopList: '▶️', loopListOn: '🔁',
  volumeOff: '🔇', volumeOn: '🔊', volumeLow: '🔉', volumeMin: '🔈', volumeOnMax: '🔊+',  // или создайте SVG
  download: '📥', refresh: '🔄',
  heart: '🤍', heartFilled: '❤️',
  feature1: '⚡', feature2: '⚙️', feature3: '🔧',
  themeLight: '☀️', themeDark: '🌙', account: '👤',
  musicNote: '🎵',
  search: '🔍',
  listUp: '⬆️',
  listDown: '⬇️',
  arrowUp: '⬆️',
  arrowDown: '⬇️',
  close: '❌',
  equalizer: '🎚️',
  info: 'ℹ️',
  warning: '⚠️',
  lightbulb: '❔',
  sparks: '✨',
  back: '↩️',
  hourglass_not_done: '⏳',
  add: '➕',

  // НОВЫЕ ИКОНКИ ДЛЯ РАДИО
  mic: '🎤',
  users: '👥',
  stop: '⏹️',
  list: '📋',
  radio: '📻',
  live: '🔴',
  offline: '⭕'
};

const Icon = ({ 
  name, 
  type = 'svg', 
  size = 24, 
  color, 
  className = '',
  svgFilter = 'brightness(0) invert(1)', // Фильтр только для SVG
  pngFilter = 'none', // Без фильтра для PNG
  ...props 
}) => {
  const [errorCount, setErrorCount] = useState(0);
  const [prevProps, setPrevProps] = useState({ name, type });
  
  const fallback = ICONS[name] || '?';
  
  // Сбрасываем счетчик ошибок при изменении пропсов
  if (name !== prevProps.name || type !== prevProps.type) {
    setErrorCount(0);
    setPrevProps({ name, type });
  }
  
  // Определяем что показывать на основе счетчика ошибок
  const getDisplayType = () => {
    if (type === 'emoji') return 'emoji';
    
    if (errorCount === 0) {
      return type === 'png' ? 'png' : 'svg';
    } else if (errorCount === 1 && type !== 'png') {
      return 'png'; // После ошибки SVG пробуем PNG
    } else {
      return 'emoji'; // После ошибки PNG показываем эмодзи
    }
  };
  
  const displayType = getDisplayType();
  
  const handleImageError = () => {
    console.warn(`Ошибка загрузки ${displayType.toUpperCase()}: ${name}`);
    setErrorCount(prev => prev + 1);
  };
  
  // Если показываем эмодзи
  if (displayType === 'emoji') {
    return (
      <span 
        className={`icon-emoji ${className}`}
        style={{ 
          fontSize: `${size}px`,
          display: 'inline-block',
          verticalAlign: 'middle',
          lineHeight: 1,
          ...(color && { color })
        }}
        {...props}
      >
        {fallback}
      </span>
    );
  }
  
  const src = displayType === 'svg' 
    ? `/icons/svg/${name}.svg`
    : `/icons/png/${name}.png`;
  
  // Разные стили для SVG и PNG
  const imageStyles = {
    width: `${size}px`,
    height: `${size}px`,
    display: 'inline-block',
    verticalAlign: 'middle',
    ...(color && { color })
  };
  
  // Применяем фильтр только для SVG
  if (displayType === 'svg') {
    imageStyles.filter = svgFilter;
  } else if (displayType === 'png') {
    imageStyles.filter = pngFilter;
  }
  
  return (
    <img
      src={src}
      alt={name}
      className={`icon icon-${displayType} ${className}`}
      style={imageStyles}
      onError={handleImageError}
      {...props}
    />
  );
};

export default Icon;