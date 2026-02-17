/* ============================================================
   Swarm UI Bridge
   ============================================================
   - Creates/owns the SwarmBoard instance.
   - Exposes helpers to route swarm NDJSON events to the board.
   ============================================================ */

import { getState, setState } from './store.js';

let _board = null;
let _container = null;
let _lastRunId = null;

function ensureSwarmBoard() {
  if (!_container) return null;
  if (_board && _board.root === _container) return _board;
  if (!window.SwarmBoard) return null;
  _container.innerHTML = '';
  _board = new window.SwarmBoard(_container);
  return _board;
}

export function setSwarmContainer(container) {
  _container = container;
  ensureSwarmBoard();
}

export function isSwarmEvent(evt) {
  if (!evt || !evt.type) return false;
  if (evt.type.startsWith('swarm_')) return true;
  if (evt.type === 'task_update') return true;
  if (evt.type === 'agent_text') return true;
  if (evt.type === 'agent_tool_start') return true;
  if (evt.type === 'agent_tool_result') return true;
  return false;
}

export function ingestSwarmEvent(evt) {
  if (!isSwarmEvent(evt)) return;
  const board = ensureSwarmBoard();
  if (!board) return;
  try { board.ingest(evt); } catch { /* ignore */ }
  if (evt.run_id) _lastRunId = evt.run_id;
}

export function openSwarmInspector() {
  const app = document.getElementById('app');
  if (app) app.classList.add('inspector-open');
  setState('settings', { showInspector: true });
  setState('ui', { inspectorTab: 'swarm' });
}

export function getLastSwarmRunId() {
  return _lastRunId;
}

export function ensureSwarmTabVisible() {
  const tab = getState().ui.inspectorTab;
  if (tab !== 'swarm') openSwarmInspector();
}
