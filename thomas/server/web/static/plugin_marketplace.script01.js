(function () {
    const state = {
        plugins: [],
        categories: [],
        generatedAt: '',
        loading: false,
        error: '',
        filter: 'all',
        search: ''
    };

    const elements = {
        marketFilters: document.getElementById('marketFilters'),
        statusText: document.getElementById('statusText'),
        sourcePill: document.getElementById('sourcePill'),
        catalog: document.getElementById('catalog'),
        refreshButton: document.getElementById('refreshButton'),
        searchInput: document.getElementById('marketSearchInput')
    };

    function safeString(value) {
        return typeof value === 'string' ? value : (value == null ? '' : String(value));
    }

    function escapeHtml(value) {
        return safeString(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function titleCase(value) {
        return safeString(value)
            .replace(/[_-]+/g, ' ')
            .split(' ')
            .filter(Boolean)
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ');
    }

    function normalizeList(raw) {
        return (Array.isArray(raw) ? raw : [])
            .map((item) => safeString(item).trim())
            .filter(Boolean)
            .filter((item, index, list) => list.indexOf(item) === index);
    }

    function buildRows() {
        const search = safeString(state.search).trim().toLowerCase();
        const rows = [];
        const seen = new Set();

        (Array.isArray(state.plugins) ? state.plugins : []).forEach((plugin) => {
            const id = safeString(plugin && plugin.id);
            if (!id || seen.has(id)) return;

            const category = safeString(plugin && plugin.category).toLowerCase() || 'other';
            if (state.filter !== 'all' && category !== state.filter) return;

            if (search) {
                const blob = [
                    id,
                    plugin && plugin.name,
                    plugin && plugin.description,
                    plugin && plugin.category,
                    plugin && plugin.target,
                    plugin && plugin.mode,
                    ...(Array.isArray(plugin && plugin.capabilities) ? plugin.capabilities : [])
                ].filter(Boolean).join(' ').toLowerCase();
                if (!blob.includes(search)) return;
            }

            rows.push({
                id: id,
                title: safeString(plugin && plugin.name) || id,
                description: safeString(plugin && plugin.description) || 'No description available yet.',
                category: category,
                categoryLabel: safeString(plugin && plugin.category_label) || titleCase(category),
                version: safeString(plugin && plugin.version) || '0.0.0',
                target: safeString(plugin && plugin.target),
                mode: safeString(plugin && plugin.mode),
                entrypoint: safeString(plugin && plugin.entrypoint),
                downloadUrl: safeString(plugin && plugin.download_url),
                downloadAvailable: Boolean((plugin && plugin.download_available) || safeString(plugin && plugin.download_url)),
                capabilities: normalizeList(plugin && plugin.capabilities),
                meta: [
                    'v' + (safeString(plugin && plugin.version) || '0.0.0'),
                    safeString(plugin && plugin.target) ? ('target ' + safeString(plugin && plugin.target)) : '',
                    safeString(plugin && plugin.mode) ? ('mode ' + safeString(plugin && plugin.mode)) : '',
                    safeString(plugin && plugin.entrypoint) ? ('entry ' + safeString(plugin && plugin.entrypoint)) : ''
                ].filter(Boolean).join(' | ')
            });
            seen.add(id);
        });

        rows.sort((left, right) => {
            return Number(Boolean(right.downloadAvailable)) - Number(Boolean(left.downloadAvailable))
                || safeString(left.category).localeCompare(safeString(right.category))
                || safeString(left.title).localeCompare(safeString(right.title));
        });
        return rows;
    }

    function renderFilters() {
        const filters = [{ id: 'all', label: 'All', count: state.plugins.length }].concat(
            (Array.isArray(state.categories) ? state.categories : []).map((row) => ({
                id: safeString(row && row.id).toLowerCase(),
                label: safeString(row && row.label) || titleCase(safeString(row && row.id)),
                count: Number(row && row.count) || 0
            }))
        );

        elements.marketFilters.innerHTML = filters.map((filter) => {
            const active = state.filter === filter.id ? ' is-active' : '';
            return '<button class="market-filter' + active + '" type="button" data-filter="' + filter.id + '">'
                + escapeHtml(filter.label) + ' (' + escapeHtml(filter.count) + ')</button>';
        }).join('');
    }

    function renderEmptyState(message) {
        const copy = message || 'No upgrades match this view.';
        elements.catalog.innerHTML = ''
            + '<section class="market-empty">'
            + '  <div class="market-empty-title">No upgrades match this view.</div>'
            + '  <div class="market-empty-copy">' + escapeHtml(copy) + '</div>'
            + '  <div class="market-empty-points">'
            + '    <div class="market-empty-point"><strong>Source:</strong> This page reads the real marketplace catalog through <code>/api/marketplace/plugins</code>.</div>'
            + '    <div class="market-empty-point"><strong>Why it is empty:</strong> Your current search or category filter did not match any upgrade rows.</div>'
            + '    <div class="market-empty-point"><strong>What to do:</strong> Clear the search, switch categories, or refresh the catalog.</div>'
            + '  </div>'
            + '</section>';
    }

    function chipsForRow(row) {
        return [row.categoryLabel].concat(row.capabilities || []).filter(Boolean).slice(0, 7);
    }

    async function copyText(value, button) {
        const text = safeString(value);
        if (!text) return;
        const original = button ? button.textContent : '';
        try {
            await navigator.clipboard.writeText(text);
            if (button) button.textContent = 'Copied';
        } catch (error) {
            if (button) button.textContent = 'Copy failed';
        } finally {
            if (button) {
                window.setTimeout(function () {
                    button.textContent = original;
                }, 1200);
            }
        }
    }

    function renderCatalog(rows) {
        if (state.loading) {
            elements.catalog.innerHTML = '<div class="market-loading">Loading Thomas upgrades...</div>';
            return;
        }
        if (state.error) {
            renderEmptyState(state.error);
            const section = elements.catalog.querySelector('.market-empty');
            if (section) section.classList.add('market-error');
            return;
        }
        if (!rows.length) {
            const message = state.search
                ? 'No upgrade matches "' + state.search + '".'
                : 'The Thomas marketplace catalog did not return any upgrades.';
            renderEmptyState(message);
            return;
        }

        elements.catalog.innerHTML = rows.map((row) => {
            const chips = chipsForRow(row);
            const chipMarkup = chips.length
                ? '<div class="market-chip-row">' + chips.map((chip) => '<span class="market-chip">' + escapeHtml(chip) + '</span>').join('') + '</div>'
                : '';
            const downloadMarkup = row.downloadUrl
                ? '<a class="market-action-btn primary" href="' + escapeHtml(row.downloadUrl) + '" download>Download ZIP</a>'
                : '<button class="market-action-btn primary" type="button" disabled>Catalog only</button>';
            return ''
                + '<article class="market-card">'
                + '  <div class="market-card-top">'
                + '    <div class="market-card-copy">'
                + '      <div class="market-card-title-row">'
                + '        <div class="market-card-title">' + escapeHtml(row.title) + '</div>'
                + '        <span class="market-card-badge">' + escapeHtml(row.categoryLabel) + '</span>'
                + (row.downloadAvailable ? '        <span class="market-card-badge is-enabled">Downloadable</span>' : '')
                + '      </div>'
                + '      <div class="market-card-description">' + escapeHtml(row.description) + '</div>'
                + '      <div class="market-card-meta">' + escapeHtml(row.meta || 'No upgrade metadata yet.') + '</div>'
                + '    </div>'
                + '  </div>'
                + '  <div class="market-card-grid">'
                + '    <div>' + chipMarkup + '</div>'
                + '    <div class="market-card-actions">'
                +          downloadMarkup
                + '      <button class="market-action-btn" type="button" data-copy-plugin-id="' + escapeHtml(row.id) + '">Copy ID</button>'
                + '    </div>'
                + '  </div>'
                + '</article>';
        }).join('');
    }

    function render() {
        const rows = buildRows();
        renderFilters();
        renderCatalog(rows);
        elements.sourcePill.textContent = 'Source: marketplace catalog';
        elements.statusText.textContent = state.loading
            ? 'Loading Thomas upgrades...'
            : ('Showing ' + String(rows.length) + ' of ' + String(state.plugins.length) + ' upgrades'
                + (state.generatedAt ? (' | catalog generated ' + new Date(state.generatedAt).toLocaleString()) : ''));
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options || {});
        if (!response.ok) {
            throw new Error('Request failed: ' + response.status + ' ' + response.statusText);
        }
        return response.json();
    }

    async function refresh() {
        state.loading = true;
        state.error = '';
        render();
        try {
            const payload = await fetchJson('/api/marketplace/plugins?limit=600');
            state.plugins = Array.isArray(payload.plugins) ? payload.plugins : [];
            state.categories = Array.isArray(payload.categories) ? payload.categories : [];
            state.generatedAt = safeString(payload.generated_at || '');
        } catch (error) {
            state.error = safeString(error && error.message) || 'Unable to load the plugin catalog.';
            state.plugins = [];
            state.categories = [];
        } finally {
            state.loading = false;
            render();
        }
    }

    function bindEvents() {
        elements.refreshButton.addEventListener('click', function () {
            void refresh();
        });

        elements.searchInput.addEventListener('input', function (event) {
            state.search = safeString(event.target && event.target.value);
            render();
        });

        elements.marketFilters.addEventListener('click', function (event) {
            const button = event.target instanceof Element ? event.target.closest('[data-filter]') : null;
            if (!button) return;
            state.filter = safeString(button.getAttribute('data-filter')) || 'all';
            render();
        });

        elements.catalog.addEventListener('click', function (event) {
            const button = event.target instanceof Element ? event.target.closest('[data-copy-plugin-id]') : null;
            if (!button) return;
            void copyText(button.getAttribute('data-copy-plugin-id'), button);
        });
    }

    bindEvents();
    render();
    void refresh();
})();
