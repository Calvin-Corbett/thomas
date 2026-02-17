/* ============================================================
   Thomas IndexedDB Persistence
   ============================================================
   Thin wrapper over IndexedDB for storing chats and settings.
   All operations are async. Gracefully degrades if IDB is
   unavailable (e.g., private browsing in some browsers).
   ============================================================ */

const DB_NAME = 'thomas-ui';
const DB_VERSION = 1;

let _db = null;

/**
 * Open (or create) the IndexedDB database.
 * @returns {Promise<IDBDatabase>}
 */
function openDB() {
  if (_db) return Promise.resolve(_db);

  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = (e) => {
      const db = e.target.result;

      // Chats store
      if (!db.objectStoreNames.contains('chats')) {
        const store = db.createObjectStore('chats', { keyPath: 'id' });
        store.createIndex('updatedAt', 'updatedAt', { unique: false });
        store.createIndex('pinned', 'pinned', { unique: false });
      }

      // Settings store (key-value)
      if (!db.objectStoreNames.contains('settings')) {
        db.createObjectStore('settings', { keyPath: 'key' });
      }
    };

    req.onsuccess = (e) => {
      _db = e.target.result;
      resolve(_db);
    };

    req.onerror = () => {
      console.warn('[db] Failed to open IndexedDB:', req.error);
      reject(req.error);
    };
  });
}

/**
 * Save a chat object to IndexedDB.
 * @param {object} chat
 */
export async function saveChat(chat) {
  try {
    const db = await openDB();
    const tx = db.transaction('chats', 'readwrite');
    // Store as plain object (Map -> Array conversion for messages is automatic since messages is already an array)
    tx.objectStore('chats').put({
      id: chat.id,
      title: chat.title,
      messages: chat.messages,
      createdAt: chat.createdAt,
      updatedAt: chat.updatedAt,
      pinned: chat.pinned || false,
      sessionId: chat.sessionId || null,
    });
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) {
    console.warn('[db] saveChat failed:', e);
  }
}

/**
 * Load all chats from IndexedDB.
 * @returns {Promise<object[]>}
 */
export async function loadChats() {
  try {
    const db = await openDB();
    const tx = db.transaction('chats', 'readonly');
    const store = tx.objectStore('chats');
    const req = store.getAll();

    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  } catch (e) {
    console.warn('[db] loadChats failed:', e);
    return [];
  }
}

/**
 * Delete a chat from IndexedDB.
 * @param {string} id
 */
export async function deleteChatDB(id) {
  try {
    const db = await openDB();
    const tx = db.transaction('chats', 'readwrite');
    tx.objectStore('chats').delete(id);
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) {
    console.warn('[db] deleteChat failed:', e);
  }
}

/**
 * Load settings from IndexedDB.
 * @returns {Promise<object>}
 */
export async function loadSettings() {
  try {
    const db = await openDB();
    const tx = db.transaction('settings', 'readonly');
    const store = tx.objectStore('settings');
    const req = store.getAll();

    return new Promise((resolve, reject) => {
      req.onsuccess = () => {
        const settings = {};
        for (const row of req.result || []) {
          settings[row.key] = row.value;
        }
        resolve(settings);
      };
      req.onerror = () => reject(req.error);
    });
  } catch (e) {
    console.warn('[db] loadSettings failed:', e);
    return {};
  }
}

/**
 * Save a setting key-value pair to IndexedDB.
 * @param {string} key
 * @param {*} value
 */
export async function saveSetting(key, value) {
  try {
    const db = await openDB();
    const tx = db.transaction('settings', 'readwrite');
    tx.objectStore('settings').put({ key, value });
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) {
    console.warn('[db] saveSetting failed:', e);
  }
}

/**
 * Save all settings at once.
 * @param {object} settings
 */
export async function saveSettings(settings) {
  try {
    const db = await openDB();
    const tx = db.transaction('settings', 'readwrite');
    const store = tx.objectStore('settings');
    for (const [key, value] of Object.entries(settings)) {
      store.put({ key, value });
    }
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) {
    console.warn('[db] saveSettings failed:', e);
  }
}

/**
 * Clear all data (for reset/debug).
 */
export async function clearAll() {
  try {
    const db = await openDB();
    const tx = db.transaction(['chats', 'settings'], 'readwrite');
    tx.objectStore('chats').clear();
    tx.objectStore('settings').clear();
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) {
    console.warn('[db] clearAll failed:', e);
  }
}
