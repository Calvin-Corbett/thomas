const state = {
  tasks: [],
  agenda: [],
  habits: [],
  goals: [],
};

const refs = {
  heroStats: document.getElementById('heroStats'),
  taskList: document.getElementById('taskList'),
  agendaList: document.getElementById('agendaList'),
  habitList: document.getElementById('habitList'),
  goalList: document.getElementById('goalList'),
  taskMeta: document.getElementById('taskMeta'),
  agendaMeta: document.getElementById('agendaMeta'),
  habitMeta: document.getElementById('habitMeta'),
  goalMeta: document.getElementById('goalMeta'),
  emptyTemplate: document.getElementById('emptyStateTemplate'),
  taskForm: document.getElementById('taskForm'),
  agendaForm: document.getElementById('agendaForm'),
  habitForm: document.getElementById('habitForm'),
  goalForm: document.getElementById('goalForm'),
};

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = {};
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || text || 'Request failed');
  }
  return payload;
}

function cloneEmptyState() {
  if (!(refs.emptyTemplate instanceof HTMLTemplateElement)) {
    const article = document.createElement('article');
    article.className = 'empty-state';
    article.innerHTML = '<strong>Nothing here yet.</strong><p>Add an item to start tracking it inside Thomas.</p>';
    return article;
  }
  return refs.emptyTemplate.content.firstElementChild.cloneNode(true);
}

function renderHeroStats() {
  if (!refs.heroStats) return;
  const completedTasks = state.tasks.filter((item) => item.status === 'done').length;
  const todayAgenda = state.agenda.filter((item) => item.status !== 'canceled').length;
  const habitCompletions = state.habits.reduce((count, habit) => count + (Array.isArray(habit.completion_log) ? habit.completion_log.length : 0), 0);
  const activeGoals = state.goals.filter((goal) => goal.status !== 'done').length;
  refs.heroStats.innerHTML = [
    { label: 'Completed Tasks', value: completedTasks },
    { label: 'Agenda Blocks', value: todayAgenda },
    { label: 'Habit Check-ins', value: habitCompletions },
    { label: 'Active Goals', value: activeGoals },
  ].map((stat) => `<article class="hero-stat"><span>${escapeHtml(stat.label)}</span><strong>${escapeHtml(stat.value)}</strong></article>`).join('');
}

function renderCollectionMeta() {
  if (refs.taskMeta) refs.taskMeta.textContent = `${state.tasks.length} items`;
  if (refs.agendaMeta) refs.agendaMeta.textContent = `${state.agenda.length} items`;
  if (refs.habitMeta) refs.habitMeta.textContent = `${state.habits.length} items`;
  if (refs.goalMeta) refs.goalMeta.textContent = `${state.goals.length} items`;
}

function renderTasks() {
  if (!refs.taskList) return;
  refs.taskList.innerHTML = '';
  if (!state.tasks.length) {
    refs.taskList.appendChild(cloneEmptyState());
    return;
  }
  state.tasks.forEach((task) => {
    const article = document.createElement('article');
    article.className = 'item-row';
    article.innerHTML = `
      <div class="item-row-top">
        <div>
          <h3 class="item-title">${escapeHtml(task.title)}</h3>
          <p class="item-meta">Priority ${escapeHtml(task.priority || 'medium')} ${task.target_date ? ` / Target ${escapeHtml(task.target_date)}` : ''}</p>
        </div>
        <div class="item-actions">
          <select data-kind="tasks" data-id="${escapeHtml(task.id)}" data-field="status">
            <option value="todo" ${task.status === 'todo' ? 'selected' : ''}>To Do</option>
            <option value="doing" ${task.status === 'doing' ? 'selected' : ''}>Doing</option>
            <option value="done" ${task.status === 'done' ? 'selected' : ''}>Done</option>
          </select>
          <button type="button" class="danger" data-delete-kind="tasks" data-id="${escapeHtml(task.id)}">Delete</button>
        </div>
      </div>
    `;
    refs.taskList.appendChild(article);
  });
}

function renderAgenda() {
  if (!refs.agendaList) return;
  refs.agendaList.innerHTML = '';
  if (!state.agenda.length) {
    refs.agendaList.appendChild(cloneEmptyState());
    return;
  }
  state.agenda.forEach((item) => {
    const article = document.createElement('article');
    article.className = 'item-row';
    article.innerHTML = `
      <div class="item-row-top">
        <div>
          <h3 class="item-title">${escapeHtml(item.title)}</h3>
          <p class="item-meta">${escapeHtml(item.date || 'No date')} ${item.start_time ? ` / ${escapeHtml(item.start_time)}-${escapeHtml(item.end_time || '')}` : ''}</p>
        </div>
        <div class="item-actions">
          <select data-kind="agenda" data-id="${escapeHtml(item.id)}" data-field="status">
            <option value="planned" ${item.status === 'planned' ? 'selected' : ''}>Planned</option>
            <option value="done" ${item.status === 'done' ? 'selected' : ''}>Done</option>
            <option value="canceled" ${item.status === 'canceled' ? 'selected' : ''}>Canceled</option>
          </select>
          <button type="button" class="danger" data-delete-kind="agenda" data-id="${escapeHtml(item.id)}">Delete</button>
        </div>
      </div>
    `;
    refs.agendaList.appendChild(article);
  });
}

function renderHabits() {
  if (!refs.habitList) return;
  refs.habitList.innerHTML = '';
  if (!state.habits.length) {
    refs.habitList.appendChild(cloneEmptyState());
    return;
  }
  state.habits.forEach((habit) => {
    const completions = Array.isArray(habit.completion_log) ? habit.completion_log.length : 0;
    const article = document.createElement('article');
    article.className = 'item-row';
    article.innerHTML = `
      <div class="item-row-top">
        <div>
          <h3 class="item-title">${escapeHtml(habit.title)}</h3>
          <p class="item-meta">${escapeHtml(habit.cadence || 'daily')} cadence / target ${escapeHtml(habit.target_count || 1)}</p>
        </div>
        <button type="button" class="danger" data-delete-kind="habits" data-id="${escapeHtml(habit.id)}">Delete</button>
      </div>
      <div class="habit-log">
        <span class="habit-streak">${escapeHtml(completions)} completions logged</span>
        <button type="button" data-complete-habit="${escapeHtml(habit.id)}">Log Today</button>
      </div>
    `;
    refs.habitList.appendChild(article);
  });
}

function renderGoals() {
  if (!refs.goalList) return;
  refs.goalList.innerHTML = '';
  if (!state.goals.length) {
    refs.goalList.appendChild(cloneEmptyState());
    return;
  }
  state.goals.forEach((goal) => {
    const article = document.createElement('article');
    article.className = 'item-row';
    article.innerHTML = `
      <div class="item-row-top">
        <div>
          <h3 class="item-title">${escapeHtml(goal.title)}</h3>
          <p class="item-meta">${escapeHtml(goal.horizon || 'month')} horizon / ${escapeHtml(goal.progress || 0)}% complete</p>
        </div>
        <div class="item-actions">
          <select data-kind="goals" data-id="${escapeHtml(goal.id)}" data-field="status">
            <option value="active" ${goal.status === 'active' ? 'selected' : ''}>Active</option>
            <option value="paused" ${goal.status === 'paused' ? 'selected' : ''}>Paused</option>
            <option value="done" ${goal.status === 'done' ? 'selected' : ''}>Done</option>
          </select>
          <button type="button" class="danger" data-delete-kind="goals" data-id="${escapeHtml(goal.id)}">Delete</button>
        </div>
      </div>
      <input type="range" min="0" max="100" value="${escapeHtml(goal.progress || 0)}" data-kind="goals" data-id="${escapeHtml(goal.id)}" data-field="progress">
      <textarea data-kind="goals" data-id="${escapeHtml(goal.id)}" data-field="notes" placeholder="Add context or a next milestone">${escapeHtml(goal.notes || '')}</textarea>
    `;
    refs.goalList.appendChild(article);
  });
}

function renderAll() {
  renderHeroStats();
  renderCollectionMeta();
  renderTasks();
  renderAgenda();
  renderHabits();
  renderGoals();
}

async function bootstrap() {
  const payload = await requestJson('/api/plugins/life-manager/bootstrap');
  Object.assign(state, payload.state || {});
  renderAll();
}

async function createItem(kind, data) {
  const payload = await requestJson(`/api/plugins/life-manager/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  state[kind] = [payload.item, ...state[kind]];
  renderAll();
}

async function updateItem(kind, id, patch) {
  const payload = await requestJson(`/api/plugins/life-manager/${kind}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  state[kind] = state[kind].map((item) => (item.id === id ? payload.item : item));
  renderAll();
}

async function deleteItem(kind, id) {
  await requestJson(`/api/plugins/life-manager/${kind}/${encodeURIComponent(id)}`, { method: 'DELETE' });
  state[kind] = state[kind].filter((item) => item.id !== id);
  renderAll();
}

function bindForms() {
  refs.taskForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(refs.taskForm);
    await createItem('tasks', {
      title: form.get('title'),
      priority: form.get('priority'),
      target_date: form.get('target_date'),
      status: 'todo',
    });
    refs.taskForm.reset();
  });

  refs.agendaForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(refs.agendaForm);
    await createItem('agenda', {
      title: form.get('title'),
      date: form.get('date'),
      start_time: form.get('start_time'),
      end_time: form.get('end_time'),
      status: 'planned',
    });
    refs.agendaForm.reset();
  });

  refs.habitForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(refs.habitForm);
    await createItem('habits', {
      title: form.get('title'),
      cadence: form.get('cadence'),
      target_count: Number(form.get('target_count') || 1),
      completion_log: [],
    });
    refs.habitForm.reset();
  });

  refs.goalForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(refs.goalForm);
    await createItem('goals', {
      title: form.get('title'),
      horizon: form.get('horizon'),
      progress: Number(form.get('progress') || 0),
      notes: '',
      status: 'active',
    });
    refs.goalForm.reset();
  });
}

function bindLists() {
  document.body.addEventListener('change', async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement || target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
      return;
    }
    const kind = target.dataset.kind;
    const id = target.dataset.id;
    const field = target.dataset.field;
    if (!kind || !id || !field) return;
    const value = target instanceof HTMLInputElement && target.type === 'range' ? Number(target.value) : target.value;
    await updateItem(kind, id, { [field]: value });
  });

  document.body.addEventListener('click', async (event) => {
    const target = event.target instanceof Element ? event.target.closest('[data-delete-kind], [data-complete-habit]') : null;
    if (!target) return;
    const deleteKind = target.getAttribute('data-delete-kind');
    const id = target.getAttribute('data-id');
    if (deleteKind && id) {
      await deleteItem(deleteKind, id);
      return;
    }
    const habitId = target.getAttribute('data-complete-habit');
    if (habitId) {
      const habit = state.habits.find((item) => item.id === habitId);
      if (!habit) return;
      const nextLog = Array.isArray(habit.completion_log) ? [...habit.completion_log] : [];
      const stamp = new Date().toISOString().slice(0, 10);
      if (!nextLog.includes(stamp)) nextLog.push(stamp);
      await updateItem('habits', habitId, { completion_log: nextLog });
    }
  });
}

async function main() {
  bindForms();
  bindLists();
  await bootstrap();
}

main().catch((error) => {
  console.error(error);
  if (refs.taskList) {
    refs.taskList.innerHTML = `<article class="empty-state"><strong>Life Manager failed to load.</strong><p>${escapeHtml(error?.message || 'Unknown error')}</p></article>`;
  }
});
