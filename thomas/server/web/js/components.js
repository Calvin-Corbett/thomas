/* ============================================================
   Thomas UI Components
   ============================================================
   Reusable DOM component factories. Each returns an HTMLElement
   that can be appended to the document.
   ============================================================ */

import { el, icon, escapeHtml } from './utils.js';

/**
 * Create a button element.
 * @param {object} opts
 * @param {string} [opts.label]
 * @param {string} [opts.iconName]
 * @param {string} [opts.variant] - 'primary' | 'danger' | 'ghost' | 'icon'
 * @param {string} [opts.size] - 'sm' | 'lg'
 * @param {string} [opts.tooltip]
 * @param {boolean} [opts.disabled]
 * @param {Function} [opts.onClick]
 * @returns {HTMLElement}
 */
export function createButton({ label, iconName, variant, size, tooltip, disabled, onClick } = {}) {
  const classes = ['btn'];
  if (variant) classes.push(`btn-${variant}`);
  if (size) classes.push(`btn-${size}`);
  if (tooltip) classes.push('tooltip');

  const btn = el('button', {
    className: classes.join(' '),
    type: 'button',
  });

  if (tooltip) btn.setAttribute('data-tooltip', tooltip);
  if (disabled) btn.disabled = true;

  if (iconName) btn.appendChild(icon(iconName));
  if (label) btn.appendChild(document.createTextNode(label));

  if (onClick) btn.addEventListener('click', onClick);

  return btn;
}

/**
 * Create a modal dialog.
 * @param {object} opts
 * @param {string} opts.title
 * @param {HTMLElement|string} opts.body
 * @param {HTMLElement[]} [opts.footer] - footer button elements
 * @param {Function} [opts.onClose]
 * @returns {{ backdrop: HTMLElement, modal: HTMLElement, close: Function }}
 */
export function createModal({ title, body, footer, onClose, wide } = {}) {
  const backdrop = el('div', { className: 'modal-backdrop' });
  const modal = el('div', { className: wide ? 'modal modal-wide' : 'modal' });

  // Header
  const header = el('div', { className: 'modal-header' },
    el('div', { className: 'modal-title' }, title || ''),
    createButton({ iconName: 'close', variant: 'icon', onClick: close }),
  );

  // Body
  const bodyEl = el('div', { className: 'modal-body' });
  if (typeof body === 'string') {
    bodyEl.innerHTML = body;
  } else if (body instanceof HTMLElement) {
    bodyEl.appendChild(body);
  }

  modal.appendChild(header);
  modal.appendChild(bodyEl);

  // Footer
  if (footer && footer.length > 0) {
    const footerEl = el('div', { className: 'modal-footer' });
    footer.forEach(btn => footerEl.appendChild(btn));
    modal.appendChild(footerEl);
  }

  backdrop.appendChild(modal);

  // Close on backdrop click
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) close();
  });

  // Close on Escape
  function onKeyDown(e) {
    if (e.key === 'Escape') close();
  }
  document.addEventListener('keydown', onKeyDown);

  function close() {
    backdrop.remove();
    document.removeEventListener('keydown', onKeyDown);
    if (onClose) onClose();
  }

  return { backdrop, modal, close };
}

/**
 * Create a tab system.
 * @param {object} opts
 * @param {{id: string, label: string}[]} opts.tabs
 * @param {string} [opts.activeId]
 * @param {(tabId: string) => void} opts.onSwitch
 * @returns {{ container: HTMLElement, setActive: (id: string) => void }}
 */
export function createTabs({ tabs, activeId, onSwitch } = {}) {
  const container = el('div', { className: 'tabs', role: 'tablist' });

  const buttons = {};

  for (const tab of tabs) {
    const btn = el('button', {
      className: `tab-btn ${tab.id === activeId ? 'active' : ''}`,
      role: 'tab',
      'aria-selected': tab.id === activeId ? 'true' : 'false',
    }, tab.label);

    btn.addEventListener('click', () => {
      setActive(tab.id);
      if (onSwitch) onSwitch(tab.id);
    });

    buttons[tab.id] = btn;
    container.appendChild(btn);
  }

  function setActive(id) {
    for (const [tabId, btn] of Object.entries(buttons)) {
      const isActive = tabId === id;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    }
  }

  return { container, setActive };
}

/**
 * Create a context menu.
 * @param {object} opts
 * @param {{label: string, icon?: string, danger?: boolean, onClick: Function}[]} opts.items
 * @param {number} opts.x
 * @param {number} opts.y
 * @returns {{ element: HTMLElement, close: Function }}
 */
export function createContextMenu({ items, x, y } = {}) {
  const menu = el('div', { className: 'context-menu' });

  for (const item of items) {
    if (item.separator) {
      menu.appendChild(el('div', { className: 'context-menu-separator' }));
      continue;
    }

    const classes = ['context-menu-item'];
    if (item.danger) classes.push('danger');

    const itemEl = el('button', { className: classes.join(' ') });
    if (item.icon) itemEl.appendChild(icon(item.icon));
    itemEl.appendChild(document.createTextNode(item.label));

    itemEl.addEventListener('click', () => {
      close();
      if (item.onClick) item.onClick();
    });

    menu.appendChild(itemEl);
  }

  // Position (keep on screen)
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  menu.style.left = `${Math.min(x, vw - 200)}px`;
  menu.style.top = `${Math.min(y, vh - items.length * 36 - 20)}px`;

  document.body.appendChild(menu);

  // Close on outside click
  function onDocClick(e) {
    if (!menu.contains(e.target)) close();
  }
  setTimeout(() => document.addEventListener('click', onDocClick), 0);

  function close() {
    menu.remove();
    document.removeEventListener('click', onDocClick);
  }

  return { element: menu, close };
}

/**
 * Create a chip element.
 * @param {object} opts
 * @param {string} opts.label
 * @param {string} [opts.variant] - 'accent' | 'danger' | 'success' | 'warning'
 * @param {Function} [opts.onRemove]
 * @returns {HTMLElement}
 */
export function createChip({ label, variant, onRemove } = {}) {
  const classes = ['chip'];
  if (variant) classes.push(`chip-${variant}`);

  const chip = el('span', { className: classes.join(' ') }, label);

  if (onRemove) {
    const removeBtn = el('span', { className: 'chip-remove', onClick: onRemove }, 'x');
    chip.appendChild(removeBtn);
  }

  return chip;
}

/**
 * Create an empty state display.
 * @param {object} opts
 * @param {string} [opts.icon] - emoji or text
 * @param {string} opts.title
 * @param {string} [opts.subtitle]
 * @returns {HTMLElement}
 */
export function createEmptyState({ icon: iconText, title, subtitle } = {}) {
  const container = el('div', { className: 'empty-state' });

  if (iconText) {
    container.appendChild(el('div', { className: 'empty-state-icon' }, iconText));
  }
  container.appendChild(el('div', { className: 'empty-state-title' }, title));
  if (subtitle) {
    container.appendChild(el('div', { className: 'empty-state-text' }, subtitle));
  }

  return container;
}

/**
 * Show a brief toast notification.
 * @param {string} message
 * @param {'info' | 'success' | 'error'} [type]
 */
export function showToast(message, type = 'info') {
  const toast = el('div', {
    className: `chip chip-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'accent'}`,
    style: {
      position: 'fixed',
      bottom: '24px',
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: '9999',
      padding: '8px 16px',
      fontSize: '13px',
      boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      animation: 'slideUp 200ms ease',
    },
  }, message);

  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 300ms';
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}
