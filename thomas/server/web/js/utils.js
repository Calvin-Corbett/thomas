/* ============================================================
   Thomas Utilities
   ============================================================
   Shared helper functions used across modules.
   ============================================================ */

/**
 * Escape HTML special characters.
 * @param {string} s
 * @returns {string}
 */
export function escapeHtml(s) {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

/**
 * Format a timestamp as relative time (e.g. "2m ago", "3h ago", "yesterday").
 * @param {number} ts - Unix timestamp in milliseconds
 * @returns {string}
 */
export function formatRelativeTime(ts) {
  const diff = Date.now() - ts;
  const seconds = Math.floor(diff / 1000);

  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;

  const date = new Date(ts);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Debounce a function.
 * @param {Function} fn
 * @param {number} ms
 * @returns {Function}
 */
export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/**
 * Truncate text to a max length, adding ellipsis.
 * @param {string} text
 * @param {number} maxLen
 * @returns {string}
 */
export function truncate(text, maxLen = 50) {
  if (!text || text.length <= maxLen) return text || '';
  return text.slice(0, maxLen).trimEnd() + '...';
}

/**
 * Detect if user is on macOS.
 * @returns {boolean}
 */
export function isMac() {
  return /Mac|iPod|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}

/**
 * Get the display string for a modifier key.
 * @param {string} key - e.g. 'Ctrl', 'Cmd'
 * @returns {string} - e.g. 'Cmd' on Mac, 'Ctrl' on others
 */
export function modKey() {
  return isMac() ? 'Cmd' : 'Ctrl';
}

/**
 * Create an HTML element with attributes and children.
 * @param {string} tag
 * @param {object} [attrs]
 * @param  {...(string|Node)} children
 * @returns {HTMLElement}
 */
export function el(tag, attrs = {}, ...children) {
  const elem = document.createElement(tag);

  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'className') {
      elem.className = value;
    } else if (key === 'style' && typeof value === 'object') {
      Object.assign(elem.style, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      elem.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') {
      for (const [dk, dv] of Object.entries(value)) {
        elem.dataset[dk] = dv;
      }
    } else if (key === 'innerHTML') {
      elem.innerHTML = value;
    } else {
      elem.setAttribute(key, value);
    }
  }

  for (const child of children) {
    if (typeof child === 'string') {
      elem.appendChild(document.createTextNode(child));
    } else if (child instanceof Node) {
      elem.appendChild(child);
    }
  }

  return elem;
}

/**
 * Simple SVG icon helper (inline SVG strings for common icons).
 * Returns an SVG element string.
 */
export const icons = {
  plus: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="3" x2="8" y2="13"/><line x1="3" y1="8" x2="13" y2="8"/></svg>',
  search: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4"/><line x1="10" y1="10" x2="14" y2="14"/></svg>',
  send: '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M2.5 2.1l11.4 5.5c.5.2.5.6 0 .8L2.5 13.9c-.5.2-.9-.1-.8-.6L3 8.5h5.5v-1H3L1.7 2.7c-.1-.5.3-.8.8-.6z"/></svg>',
  stop: '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="3" width="10" height="10" rx="2"/></svg>',
  menu: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="3" y1="5" x2="15" y2="5"/><line x1="3" y1="9" x2="15" y2="9"/><line x1="3" y1="13" x2="15" y2="13"/></svg>',
  close: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>',
  settings: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="2"/><path d="M13.3 10.2l-.8-.5a4.6 4.6 0 000-3.4l.8-.5a.5.5 0 00.2-.6l-.5-1a.5.5 0 00-.6-.2l-.9.3a4.5 4.5 0 00-2.9-1.7V1.5a.5.5 0 00-.5-.5h-1a.5.5 0 00-.5.5v1a4.5 4.5 0 00-2.9 1.7l-.9-.3a.5.5 0 00-.6.2l-.5 1a.5.5 0 00.2.6l.8.5a4.6 4.6 0 000 3.4l-.8.5a.5.5 0 00-.2.6l.5 1a.5.5 0 00.6.2l.9-.3a4.5 4.5 0 002.9 1.7v1a.5.5 0 00.5.5h1a.5.5 0 00.5-.5v-1a4.5 4.5 0 002.9-1.7l.9.3a.5.5 0 00.6-.2l.5-1a.5.5 0 00-.2-.6z"/></svg>',
  models: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 5l5.5-3 5.5 3-5.5 3-5.5-3z"/><path d="M2.5 8l5.5 3 5.5-3"/><path d="M2.5 11l5.5 3 5.5-3"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="5" width="9" height="9" rx="1.5"/><path d="M3 11V3a1.5 1.5 0 011.5-1.5H11"/></svg>',
  check: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3,8 7,12 13,4"/></svg>',
  edit: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M11.5 1.5l3 3L5 14H2v-3z"/></svg>',
  retry: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 8a6 6 0 0111.3-2.8M14 8a6 6 0 01-11.3 2.8"/><polyline points="2,3 2,6 5,6"/><polyline points="14,13 14,10 11,10"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="3,4 13,4"/><path d="M5 4V2.5A.5.5 0 015.5 2h5a.5.5 0 01.5.5V4"/><path d="M4 4l.7 9.5a1 1 0 001 .5h4.6a1 1 0 001-.5L12 4"/></svg>',
  pin: '<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M10.97 1.97a.75.75 0 011.06 1.06l-1.5 1.5 1.5 3.5-2 2L8 8l-4.5 4.5-1-1L7 7 5 5l-2 2-3.5-1.5 1.5-1.5 3.5 1.5z"/></svg>',
  dots: '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="3" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13" r="1.5"/></svg>',
  inspector: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1" y="1" width="14" height="14" rx="2"/><line x1="10" y1="1" x2="10" y2="15"/></svg>',
  mic: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5.5" y="1" width="5" height="8" rx="2.5"/><path d="M3 7.5a5 5 0 0010 0"/><line x1="8" y1="12.5" x2="8" y2="15"/></svg>',
  attach: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13.5 7.5l-5.8 5.8a3.5 3.5 0 01-5-5l6.5-6.5a2 2 0 013 3L5.5 11.5a.5.5 0 01-.7-.7L11 4.5"/></svg>',
  image: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="2.5" width="13" height="11" rx="2"/><circle cx="5" cy="6" r="1.5"/><polyline points="14.5,13.5 10,8 6,12 4,10 1.5,13.5"/></svg>',
  sun: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="3"/><line x1="8" y1="1" x2="8" y2="3"/><line x1="8" y1="13" x2="8" y2="15"/><line x1="1" y1="8" x2="3" y2="8"/><line x1="13" y1="8" x2="15" y2="8"/></svg>',
  moon: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13.5 8.5a5.5 5.5 0 01-6-6 5.5 5.5 0 106 6z"/></svg>',
  command: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4.5 6V4.5a2 2 0 114 0V6m-4 0h4m-4 0H4a2 2 0 100 4h.5m4-4H12a2 2 0 110 4h-.5M8.5 10v1.5a2 2 0 11-4 0V10m4 0h-4m4 0H12a2 2 0 100-4h-.5M4.5 6H4a2 2 0 110 4h.5"/></svg>',
  chevronDown: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,6 8,10 12,6"/></svg>',
  help: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.5"/><path d="M6 6a2 2 0 013.5 1.5c0 1.5-2 1.5-2 3"/><circle cx="8" cy="12.5" r="0.5" fill="currentColor"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="8" y1="2" x2="8" y2="10"/><polyline points="4,7 8,11 12,7"/><line x1="2" y1="14" x2="14" y2="14"/></svg>',
  bookmark: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 2.5h8a1 1 0 011 1V14l-5-3-5 3V3.5a1 1 0 011-1z"/></svg>',
  quote: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6.5 4H4a2 2 0 00-2 2v3a3 3 0 003 3h1V9H5V7h1.5V4zM14 4h-2.5a2 2 0 00-2 2v3a3 3 0 003 3h1V9h-1V7H14V4z"/></svg>',
  info: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.5"/><line x1="8" y1="7" x2="8" y2="11"/><circle cx="8" cy="5" r="0.75" fill="currentColor" stroke="none"/></svg>',
  fork: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 3.5a2 2 0 11-4 0 2 2 0 014 0zM15 3.5a2 2 0 11-4 0 2 2 0 014 0zM9 12.5a2 2 0 11-4 0 2 2 0 014 0z"/><path d="M3 5.3v1.2c0 1.6 1.3 2.9 2.9 2.9h4.2c1.6 0 2.9 1.3 2.9 2.9v1.2"/><path d="M13 5.3v1.2c0 1.6-1.3 2.9-2.9 2.9"/></svg>',
  speaker: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 6h2l3-3v10l-3-3H3z"/><path d="M11 6.5a2.5 2.5 0 010 3"/><path d="M12.8 5a5 5 0 010 6"/></svg>',
};

/**
 * Create an icon element from the icons map.
 * @param {string} name
 * @param {string} [className]
 * @returns {HTMLElement}
 */
export function icon(name, className = '') {
  const span = document.createElement('span');
  span.className = `icon ${className}`.trim();
  span.innerHTML = icons[name] || '';
  span.setAttribute('aria-hidden', 'true');
  return span;
}

/**
 * Apply the correct theme to the document.
 * @param {'light' | 'dark' | 'system'} theme
 */
export function applyTheme(theme) {
  let resolved = theme;
  if (theme === 'system') {
    resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.setAttribute('data-theme', resolved);
}

/**
 * Format milliseconds as a human-readable duration.
 * @param {number} ms
 * @returns {string}
 */
export function formatDuration(ms) {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

/**
 * Format a number with commas.
 * @param {number} n
 * @returns {string}
 */
export function formatNumber(n) {
  return n.toLocaleString();
}
