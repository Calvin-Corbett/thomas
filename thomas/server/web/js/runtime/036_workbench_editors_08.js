function moduleRenderMarketplaceSurface(container) {
    if (!container) return null;
    const staleEmbedded = container.querySelector('[data-module-embedded-surface]');
    if (staleEmbedded instanceof HTMLIFrameElement && typeof staleEmbedded.__moduleEmbeddedCleanup === 'function') {
        try {
            staleEmbedded.__moduleEmbeddedCleanup();
        } catch (_error) {}
    }
    const state = moduleEnsureRuntime();
    if (!state) return null;

    const marketplaceState = state.marketplace && typeof state.marketplace === 'object' ? state.marketplace : null;
    if (marketplaceState) {
        const pendingRefresh = moduleRefreshMarketplace();
        if (pendingRefresh && pendingRefresh !== marketplaceState.uiRenderPromise) {
            marketplaceState.uiRenderPromise = pendingRefresh;
            pendingRefresh.finally(() => {
                const runtime = moduleEnsureRuntime();
                const runtimeMarketplace = runtime?.marketplace && typeof runtime.marketplace === 'object' ? runtime.marketplace : null;
                if (runtimeMarketplace && runtimeMarketplace.uiRenderPromise === pendingRefresh) {
                    runtimeMarketplace.uiRenderPromise = null;
                }
                if (runtime?.activeMode === 'marketplace') {
                    moduleRender('marketplace', { touch: false });
                }
            });
        }
    }

    const apps = Array.isArray(marketplaceState?.apps) ? marketplaceState.apps : [];
    const categories = Array.isArray(marketplaceState?.categories) ? marketplaceState.categories : [];
    const loading = Boolean(marketplaceState?.loading);
    const error = safeString(marketplaceState?.error);
    const warning = safeString(marketplaceState?.warning || marketplaceState?.syncError);
    const degraded = Boolean(marketplaceState?.degraded);
    const searchText = safeString(marketplaceState?.search).trim();
    const activeFilter = safeString(marketplaceState?.filter).toLowerCase() || 'all';
    const generatedAt = safeString(marketplaceState?.generatedAt);
    const syncedAt = safeString(marketplaceState?.syncedAt || generatedAt);
    const sourceLabel = safeString(marketplaceState?.sourceLabel) || safeString(marketplaceState?.storeUrl) || 'thomas.dev';
    const configuredStoreUrl = normalizeMarketplaceStoreUrl(
        safeString(marketplaceState?.pendingStoreUrl || marketplaceState?.storeUrl || moduleReadPreferredMarketplaceStoreUrl())
    );
    const titleCase = (value) => safeString(value)
        .replace(/[_-]+/g, ' ')
        .split(' ')
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');

    const marketplaceEvidence = (app) => {
        const downloadUrl = safeString(app?.install?.release_download_endpoint || app?.install?.release_manifest_endpoint);
        const installed = Boolean(app?.installed);
        const signedInstall = Boolean(app?.installable && app?.compatibility?.eligible);
        const trustedDownload = Boolean(app?.download_available && downloadUrl);
        const reasons = [];
        if (installed) reasons.push('installed-runtime');
        if (signedInstall) reasons.push('backend-install-action');
        if (trustedDownload) reasons.push('trusted-download-action');
        return { verified: reasons.length > 0, reasons, downloadUrl };
    };
    const verifiedApps = apps.filter((app) => marketplaceEvidence(app).verified);
    const potentialApps = apps.filter((app) => !marketplaceEvidence(app).verified);
    const potentialMode = activeFilter === 'potential' || activeFilter.startsWith('potential:');
    const activeCategory = potentialMode
        ? activeFilter.replace(/^potential:?/, '')
        : (activeFilter === 'all' ? '' : activeFilter);
    const activePool = potentialMode ? potentialApps : verifiedApps;

    const filteredApps = activePool.filter((app) => {
        const filterId = safeString(app?.category_id).toLowerCase() || 'other';
        if (activeCategory && filterId !== activeCategory) return false;
        if (!searchText) return true;
        const blob = [
            safeString(app?.module_id),
            safeString(app?.display_name),
            safeString(app?.subtitle),
            safeString(app?.description),
            safeString(app?.category_label || app?.category),
            safeString(app?.target),
            safeString(app?.mode),
            safeString(app?.mode_id),
            safeString(app?.publisher_name || app?.publisher),
            ...(Array.isArray(app?.capabilities) ? app.capabilities : []),
        ].join(' ').toLowerCase();
        return blob.includes(searchText.toLowerCase());
    }).sort((left, right) => {
        const installableWeight = Number(Boolean(right?.installable)) - Number(Boolean(left?.installable));
        if (installableWeight) return installableWeight;
        const installedWeight = Number(Boolean(right?.installed)) - Number(Boolean(left?.installed));
        if (installedWeight) return installedWeight;
        return safeString(left?.display_name || left?.module_id).localeCompare(safeString(right?.display_name || right?.module_id));
    });

    const selectedId = safeString(marketplaceState?.selectedId);
    const selectedApp = filteredApps.find((app) => safeString(app?.module_id) === selectedId) || null;
    if (marketplaceState && selectedId && !selectedApp) {
        marketplaceState.selectedId = '';
    }

    const categoryFilters = [
        { id: 'all', label: 'Verified Store', count: verifiedApps.length },
        { id: 'potential', label: 'Potential', count: potentialApps.length },
    ].concat(categories.map((row) => {
        const id = safeString(row?.id).toLowerCase() || 'other';
        const count = activePool.filter((app) => (safeString(app?.category_id).toLowerCase() || 'other') === id).length;
        return {
            id: potentialMode ? `potential:${id}` : id,
            label: safeString(row?.label) || titleCase(row?.id) || 'Other',
            count,
        };
    }).filter((row) => row.count > 0));

    const buildStatus = (app) => {
        if (app?.update_available) return { label: 'Update available', tone: 'catalog' };
        if (app?.installed) {
            const suffix = app?.verified === false ? ' · unverified' : '';
            if (app?.enabled) return { label: `Installed${suffix}`, tone: 'ready' };
            return { label: `Disabled${suffix}`, tone: 'catalog' };
        }
        if (app?.installable) return { label: 'Ready to install', tone: 'ready' };
        if (app?.download_available) return { label: 'Downloadable', tone: 'ready' };
        return { label: 'Potential only', tone: 'catalog' };
    };

    const typeLabel = (app) => titleCase(app?.marketplace_type_label || app?.marketplace_type || app?.kind) || 'Plugin';

    const categoryIconMap = Object.freeze({
        alerts: 'ph-bell-ringing', analytics: 'ph-chart-line-up', compliance: 'ph-scales',
        fraud: 'ph-shield-warning', incident: 'ph-siren', operations: 'ph-desktop-tower',
        ops: 'ph-wrench', payments: 'ph-credit-card', qa: 'ph-check-circle',
        security: 'ph-shield-check', support: 'ph-lifebuoy', other: 'ph-cube',
    });
    const iconClass = (app) => {
        const value = safeString(app?.icon).trim();
        if (/^ph-[a-z0-9-]+$/i.test(value) && value !== 'ph-puzzle-piece') return value;
        const categoryId = safeString(app?.category_id).toLowerCase() || 'other';
        return categoryIconMap[categoryId] || 'ph-app-window';
    };
    const secondaryIconClass = (app) => {
        const label = `${safeString(app?.display_name)} ${safeString(app?.module_id)}`.toLowerCase();
        const keywordIcons = [
            ['discord', 'ph-discord-logo'], ['email', 'ph-envelope-simple'], ['audit', 'ph-magnifying-glass'],
            ['detect', 'ph-radar'], ['prevent', 'ph-shield'], ['triage', 'ph-funnel'],
            ['remediat', 'ph-first-aid'], ['escalat', 'ph-arrow-circle-up'],
        ];
        return keywordIcons.find(([keyword]) => label.includes(keyword))?.[1] || 'ph-sparkle';
    };

    const isWorkspaceModule = (app) => (
        safeString(app?.left_nav_behavior).toLowerCase() === 'workspace'
        || ['app', 'command_center'].includes(safeString(app?.marketplace_type).toLowerCase())
    );

    const installBehaviorLabel = (app) => {
        if (app?.installed) {
            if (app?.verified === false) return 'Community install';
            return app?.enabled && !isWorkspaceModule(app) ? 'Enabled' : 'Installed';
        }
        if (app?.installable) return 'Installable';
        if (app?.download_available) return 'Downloadable';
        return 'No verified install';
    };

    const buildPrimaryAction = (app) => {
        if (app?.installable && app?.update_available) {
            return { id: 'install', label: 'Update' };
        }
        if (app?.installed) {
            if (isWorkspaceModule(app)) {
                return { id: 'open', label: 'Open' };
            }
            return app?.enabled
                ? { id: 'disable', label: 'Disable' }
                : { id: 'enable', label: 'Enable' };
        }
        if (app?.installable) {
            return { id: 'install', label: 'Install' };
        }
        if (app?.download_available) {
            return { id: 'download', label: 'Download ZIP', actionUrl: safeString(app?.install?.release_download_endpoint) };
        }
        return null;
    };

    const buildSecondaryActions = (app) => {
        const downloadUrl = safeString(app?.install?.release_download_endpoint || app?.install?.release_manifest_endpoint);
        const actions = [];
        if (app?.installed) {
            actions.push({ id: 'uninstall', label: 'Uninstall' });
        }
        if (downloadUrl) {
            actions.push({ id: 'download', label: 'Download ZIP', actionUrl: downloadUrl });
        }
        actions.push({ id: 'copy', label: 'Copy ID' });
        return actions;
    };

    const renderActionButton = (app, action, { primary = false } = {}) => {
        if (!action) return '';
        if (action.id === 'copy') {
            return `
                <button
                    type="button"
                    class="marketplace-secondary-btn"
                    data-module-marketplace-copy-id="${escapeHtml(safeString(app?.module_id))}"
                    data-module-mode="marketplace">
                    ${escapeHtml(action.label)}
                </button>
            `;
        }
        const className = primary ? 'module-item-btn marketplace-cta' : 'marketplace-secondary-btn';
        return `
            <button
                type="button"
                class="${className}"
                data-module-mode="marketplace"
                data-module-section="queue"
                data-module-item-id="${escapeHtml(safeString(app?.module_id))}"
                data-module-action-id="${escapeHtml(action.id)}"
                data-module-action-label="${escapeHtml(action.label)}"
                data-module-action-url="${escapeHtml(safeString(action.actionUrl || ''))}">
                ${escapeHtml(action.label)}
            </button>
        `;
    };

    const filterMarkup = categoryFilters.map((filterRow) => {
        const isActive = activeFilter === filterRow.id;
        return `
            <button
                type="button"
                class="marketplace-filter-chip${isActive ? ' is-active' : ''}"
                data-module-marketplace-filter="${escapeHtml(filterRow.id)}"
                data-module-mode="marketplace">
                <span>${escapeHtml(filterRow.label)}</span>
                <strong>${escapeHtml(String(filterRow.count))}</strong>
            </button>
        `;
    }).join('');

    const renderSelectedStrip = (app) => {
        if (!app) return '';
        const primaryAction = buildPrimaryAction(app);
        const secondaryActions = buildSecondaryActions(app);
        const status = buildStatus(app);
        const facts = [
            { label: 'Category', value: safeString(app?.category_label || app?.category) || 'Other' },
            { label: 'Target', value: titleCase(app?.target) || 'Local' },
            { label: 'Mode', value: titleCase(app?.mode_id || app?.mode) || 'Plugin' },
            { label: 'Version', value: `v${safeString(app?.version) || '0.0.0'}` },
            { label: 'Publisher', value: safeString(app?.publisher_name || app?.publisher) || 'Thomas' },
            { label: 'Plugin ID', value: safeString(app?.module_id) },
        ];
        return `
            <section class="marketplace-selected-strip" role="region" aria-label="Selected Marketplace package details">
                <div class="marketplace-selected-main">
                    <div class="marketplace-selected-art" aria-hidden="true" data-ui-id="marketplace.detail.art" data-ui-instance-key="${escapeHtml(safeString(app?.module_id))}" data-ui-label="Selected package artwork" data-ui-component="package-art" data-ui-policy="move resize ai-edit" data-ui-constraints="contain=parent,minWidth=64,minHeight=64,maxWidth=220,maxHeight=220,collision=avoid"><i class="ph ${escapeHtml(iconClass(app))} marketplace-icon-primary"></i><i class="ph ${escapeHtml(secondaryIconClass(app))} marketplace-icon-secondary"></i></div>
                    <div class="marketplace-selected-copy">
                        <span class="marketplace-selected-kicker">${escapeHtml(typeLabel(app))} · ${escapeHtml(status.label)}</span>
                        <h3>${escapeHtml(safeString(app?.display_name) || safeString(app?.module_id))}</h3>
                        <p>${escapeHtml(safeString(app?.description) || safeString(app?.subtitle) || 'No description available.')}</p>
                    </div>
                    <div class="marketplace-selected-actions">
                        ${renderActionButton(app, primaryAction, { primary: true })}
                        ${secondaryActions.map((action) => renderActionButton(app, action)).join('')}
                        <button type="button" class="marketplace-secondary-btn" data-module-action-id="view-category-${escapeHtml(safeString(app?.category_id) || 'all')}" data-module-marketplace-filter="${escapeHtml(potentialMode ? `potential:${safeString(app?.category_id) || 'other'}` : (safeString(app?.category_id) || 'all'))}" data-module-mode="marketplace">View category</button>
                    </div>
                </div>
                <div class="marketplace-selected-grid">
                    ${facts.map((fact) => `
                        <div class="marketplace-selected-fact">
                            <span>${escapeHtml(fact.label)}</span>
                            <strong>${escapeHtml(fact.value)}</strong>
                        </div>
                    `).join('')}
                </div>
                <p class="marketplace-selected-capabilities"><strong>Capabilities</strong> ${escapeHtml((Array.isArray(app?.capabilities) ? app.capabilities : []).join(', ') || 'No declared capabilities')}</p>
                <p class="marketplace-selected-capabilities"><strong>Requires</strong> ${escapeHtml((Array.isArray(app?.requires) ? app.requires : []).join(', ') || 'No additional dependencies')}</p>
            </section>
        `;
    };

    const renderProductCard = (app, { featured = false } = {}) => {
        const status = buildStatus(app);
        const primaryAction = buildPrimaryAction(app);
        const isSelected = Boolean(selectedApp) && safeString(selectedApp?.module_id) === safeString(app?.module_id);
        return `
            <article class="marketplace-card marketplace-product-card${featured ? ' marketplace-feature' : ''}${isSelected ? ' is-selected' : ''}">
                <div class="marketplace-product-art" aria-hidden="true" data-ui-id="marketplace.package.art" data-ui-instance-key="${escapeHtml(safeString(app?.module_id))}" data-ui-label="${escapeHtml(safeString(app?.display_name) || safeString(app?.module_id))} artwork" data-ui-component="package-art" data-ui-group="marketplace.package-art" data-ui-policy="move resize ai-edit" data-ui-constraints="contain=parent,minWidth=72,minHeight=72,maxWidth=360,maxHeight=280,collision=avoid">
                    <i class="ph ${escapeHtml(iconClass(app))} marketplace-icon-primary"></i>
                    <i class="ph ${escapeHtml(secondaryIconClass(app))} marketplace-icon-secondary"></i>
                    <span>${escapeHtml(safeString(app?.category_label || app?.category) || 'Thomas')}</span>
                </div>
                <button type="button" class="marketplace-card-hit" data-module-action-id="details" data-module-marketplace-select="${escapeHtml(safeString(app?.module_id))}" data-module-mode="marketplace" aria-label="View details for ${escapeHtml(safeString(app?.display_name) || safeString(app?.module_id))}">
                    <span class="marketplace-card-locus">${escapeHtml(typeLabel(app))} · ${escapeHtml(installBehaviorLabel(app))}</span>
                    <strong class="marketplace-card-title">${escapeHtml(safeString(app?.display_name) || safeString(app?.module_id))}</strong>
                    <span class="marketplace-card-summary">${escapeHtml(safeString(app?.subtitle) || safeString(app?.description) || 'No description available.')}</span>
                    <span class="marketplace-card-meta">${escapeHtml(`v${safeString(app?.version) || '0.0.0'} · ${safeString(app?.publisher_name || app?.publisher) || 'Thomas'}`)}</span>
                </button>
                <div class="marketplace-card-actions">
                    ${renderActionButton(app, primaryAction, { primary: true })}
                    <span class="marketplace-card-status" data-marketplace-status="${escapeHtml(status.tone)}">${escapeHtml(status.label)}</span>
                </div>
            </article>
        `;
    };

    const browseMode = !searchText && (activeFilter === 'all' || activeFilter === 'potential');
    const rankApps = (catalog) => catalog.slice().sort((left, right) => {
        const score = (app) => (
            Number(Boolean(app?.installed)) * 100
            + Number(Boolean(app?.installable)) * 80
            + Number(safeString(app?.marketplace_type).toLowerCase() === 'command_center') * 60
            + Number(safeString(app?.category_id).toLowerCase() === 'operations') * 20
            + Number(Boolean(app?.update_available)) * 10
        );
        const difference = score(right) - score(left);
        return difference || safeString(left?.display_name).localeCompare(safeString(right?.display_name));
    });
    const featuredApp = browseMode ? rankApps(activePool)[0] : null;
    const secondaryFeature = browseMode ? rankApps(activePool).find((app) => (
        safeString(app?.module_id) !== safeString(featuredApp?.module_id)
        && safeString(app?.category_id) !== safeString(featuredApp?.category_id)
    )) : null;

    const shelfRows = categories.map((category) => {
        const id = safeString(category?.id).toLowerCase() || 'other';
        const label = safeString(category?.label) || titleCase(id) || 'Other';
        const shelfApps = activePool.filter((app) => (
            safeString(app?.category_id).toLowerCase() === id
            && safeString(app?.module_id) !== safeString(featuredApp?.module_id)
            && safeString(app?.module_id) !== safeString(secondaryFeature?.module_id)
        )).sort((left, right) => safeString(left?.display_name).localeCompare(safeString(right?.display_name))).slice(0, 8);
        if (!shelfApps.length) return '';
        return `
            <section class="marketplace-shelf" aria-labelledby="marketplace-shelf-${escapeHtml(id)}" data-ui-id="marketplace.shelf" data-ui-instance-key="${escapeHtml(id)}" data-ui-label="${escapeHtml(label)} Marketplace collection" data-ui-component="collection-shelf" data-ui-group="marketplace.shelves" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=260,maxHeight=620,collision=avoid">
                <div class="marketplace-shelf-head">
                    <div><span>Curated collection</span><h3 id="marketplace-shelf-${escapeHtml(id)}">${escapeHtml(label)}</h3></div>
                    <div class="marketplace-shelf-controls">
                        <button type="button" class="marketplace-carousel-btn" aria-label="Scroll ${escapeHtml(label)} backward" data-marketplace-carousel="-1" data-marketplace-carousel-target="${escapeHtml(id)}" data-module-action-id="carousel-back-${escapeHtml(id)}"><i class="ph ph-caret-left"></i></button>
                        <button type="button" class="marketplace-carousel-btn" aria-label="Scroll ${escapeHtml(label)} forward" data-marketplace-carousel="1" data-marketplace-carousel-target="${escapeHtml(id)}" data-module-action-id="carousel-forward-${escapeHtml(id)}"><i class="ph ph-caret-right"></i></button>
                        <button type="button" class="marketplace-secondary-btn" data-module-action-id="view-category-${escapeHtml(id)}" data-module-marketplace-filter="${escapeHtml(potentialMode ? `potential:${id}` : id)}" data-module-mode="marketplace">View all</button>
                    </div>
                </div>
                <div class="marketplace-shelf-rail" id="marketplace-rail-${escapeHtml(id)}" data-ui-id="marketplace.shelf.items" data-ui-instance-key="${escapeHtml(id)}" data-ui-label="${escapeHtml(label)} package rail" data-ui-component="repeating-card-group" data-ui-group="marketplace.shelf-items" data-ui-policy="move resize protected-items" data-ui-constraints="items-runtime-owned,reposition-deny,resize-deny,contain=parent,minWidth=260,minHeight=220,maxHeight=520,collision=avoid,preserve-handlers">${shelfApps.map((app) => renderProductCard(app)).join('')}</div>
            </section>
        `;
    }).filter(Boolean).slice(0, 4);

    const renderFeature = (app, secondary = false) => app ? `
        <section class="marketplace-feature-wrap${secondary ? ' marketplace-feature-wrap-secondary' : ''}" aria-label="${potentialMode ? 'Potential package spotlight' : 'Featured Thomas upgrade'}" data-ui-id="marketplace.feature" data-ui-instance-key="${secondary ? 'secondary' : 'primary'}" data-ui-label="Marketplace feature" data-ui-component="featured-collection" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=240,maxHeight=720,collision=avoid">
            <div class="marketplace-feature-copy" data-ui-id="marketplace.feature.intro" data-ui-instance-key="${secondary ? 'secondary' : 'primary'}" data-ui-label="Marketplace featured introduction" data-ui-component="editorial-copy" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=220,minHeight=140,maxWidth=760,maxHeight=520,collision=avoid"><span>${potentialMode ? 'Potential · local review only' : 'Verified for Thomas'}</span><h2>${potentialMode ? (secondary ? 'Local review pick' : 'Catalog evidence only') : (secondary ? 'From another category' : 'Featured upgrade')}</h2><p>${potentialMode ? 'This package is catalog evidence only. Thomas will not present an install action until its runtime, signed bundle, or installed state is proven.' : (secondary ? 'A second pick from a different category, drawn from the same verified pool.' : 'Every item shown here has an installed runtime or a backend-verified install or download path.')}</p></div>
            ${renderProductCard(app, { featured: true })}
        </section>
    ` : '';

    const resultLimit = activeFilter === 'all' ? 120 : 80;
    const visibleResults = filteredApps.slice(0, resultLimit);
    const resultsMarkup = `
        <section class="marketplace-results" aria-labelledby="marketplace-results-title" data-ui-id="marketplace.results" data-ui-label="Marketplace search results" data-ui-component="result-collection" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=320,maxHeight=2600,collision=avoid">
            <div class="marketplace-shelf-head">
                <div><span>${searchText ? 'Search results' : (potentialMode ? 'Potential · local review' : 'Verified collection')}</span><h3 id="marketplace-results-title">${escapeHtml(activeFilter === 'all' ? 'Verified Marketplace results' : (categoryFilters.find((row) => row.id === activeFilter)?.label || titleCase(activeCategory || activeFilter)))}</h3></div>
                <strong>${escapeHtml(String(filteredApps.length))} found</strong>
            </div>
            <div class="marketplace-results-grid">${visibleResults.map((app) => renderProductCard(app)).join('')}</div>
            ${filteredApps.length > visibleResults.length ? `<p class="marketplace-results-note">Showing the first ${escapeHtml(String(visibleResults.length))} results. Choose a category or refine the search to reach the complete catalog.</p>` : ''}
        </section>
    `;

    const installedCount = apps.filter((app) => app?.installed).length;
    const updateCount = apps.filter((app) => app?.update_available).length;
    const generatedLabel = generatedAt ? new Date(generatedAt).toLocaleString() : '';
    const syncedLabel = syncedAt ? new Date(syncedAt).toLocaleString() : '';
    const verifiedEmptyMarkup = !loading && !error && !potentialMode && !searchText ? `
        <section class="marketplace-store-empty" data-ui-id="marketplace.verified-empty" data-ui-label="Verified store status" data-ui-component="store-status" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=220,maxHeight=620,collision=avoid">
            <div><span>Verified Store</span><h2>No packages have proven operating evidence yet.</h2><p>Thomas is keeping the main store honest. Packages appear here only after an installed runtime, backend-approved install action, or trusted download action is present.</p></div>
            <div class="marketplace-store-empty-actions"><button type="button" class="marketplace-command-btn marketplace-command-btn-primary" data-module-action-id="review-potential" data-module-marketplace-filter="potential" data-module-mode="marketplace">Review ${escapeHtml(String(potentialApps.length))} potential packages</button><button type="button" class="marketplace-command-btn" data-module-action-id="install-file-empty" data-marketplace-import data-module-mode="marketplace">Install From File</button><button type="button" class="marketplace-command-btn" data-module-action-id="install-url-empty" data-marketplace-import-url data-module-mode="marketplace">Install from URL</button></div>
        </section>
    ` : '';
    const emptyMarkup = `
        <section class="marketplace-empty-state${error ? ' marketplace-empty-state-error' : ''}">
            <strong>${escapeHtml(loading ? 'Loading upgrades...' : (searchText ? `No results for \"${searchText}\".` : 'No packages match this view.'))}</strong>
            <p>${escapeHtml(error || (loading ? 'Thomas is syncing the marketplace catalog.' : 'Change the search or category filter to widen the results.'))}</p>
        </section>
    `;

    container.innerHTML = `
        <section class="marketplace-surface">
            <div class="marketplace-sticky-head">
                <div class="marketplace-command-bar">
                    <label class="marketplace-search-wrap" aria-label="Search marketplace">
                        <span class="marketplace-field-label">Search Marketplace</span>
                        <input
                            class="marketplace-search-input"
                            type="search"
                            value="${escapeHtml(searchText)}"
                            placeholder="Search upgrades, categories, publishers, capabilities, and support components"
                            data-module-marketplace-search
                            data-module-mode="marketplace">
                    </label>
                    <div class="marketplace-command-actions">
                        <button type="button" class="marketplace-command-btn" data-module-action-id="install-file-command" data-marketplace-import data-module-mode="marketplace">Install From File</button>
                        <button type="button" class="marketplace-command-btn" data-module-action-id="install-url-command" data-marketplace-import-url data-module-mode="marketplace">Install from URL</button>
                        ${searchText ? `<button type="button" class="marketplace-command-btn" data-module-marketplace-clear data-module-mode="marketplace">Clear</button>` : ''}
                        <button type="button" class="marketplace-command-btn marketplace-command-btn-primary" data-module-marketplace-refresh data-module-mode="marketplace">Sync Catalog</button>
                    </div>
                </div>
                <div class="marketplace-summary-row">
                    <p class="marketplace-summary-copy">
                        <strong>${escapeHtml(String(verifiedApps.length))}</strong> verified
                        <span>${escapeHtml(String(potentialApps.length))} potential</span>
                        <span>${escapeHtml(String(installedCount))} installed</span>
                        <span>${escapeHtml(String(updateCount))} updates</span>
                        <span>${escapeHtml(String(categories.length))} categories</span>
                        <span>${escapeHtml(String(filteredApps.length))} visible</span>
                        ${syncedLabel ? `<span>Last sync ${escapeHtml(syncedLabel)}</span>` : (generatedLabel ? `<span>Updated ${escapeHtml(generatedLabel)}</span>` : '')}
                    </p>
                </div>
                ${warning ? `
                    <div class="marketplace-summary-row">
                        <p class="marketplace-summary-copy">
                            <strong>${escapeHtml(degraded ? 'Using fallback catalog.' : 'Marketplace notice.')}</strong>
                            <span>${escapeHtml(warning)}</span>
                        </p>
                    </div>
                ` : ''}
                <div class="marketplace-filter-rail">
                    ${filterMarkup}
                </div>
            </div>
            <input class="hidden" type="file" accept=".zip,application/zip" data-module-action-id="install-file-input" data-marketplace-import-input>
            ${renderSelectedStrip(selectedApp)}
            <main class="marketplace-card-grid">
                ${filteredApps.length ? (browseMode ? `
                    ${renderFeature(featuredApp)}
                    ${shelfRows.slice(0, 2).join('')}
                    ${renderFeature(secondaryFeature, true)}
                    ${shelfRows.slice(2).join('')}
                ` : resultsMarkup) : (verifiedEmptyMarkup || emptyMarkup)}
            </main>
        </section>
    `;

    if (moduleWorkspace) {
        const moduleHeader = moduleWorkspace.querySelector('.module-header');
        const headerHeight = moduleHeader ? Math.ceil(moduleHeader.getBoundingClientRect().height) : 0;
        moduleWorkspace.style.setProperty('--marketplace-sticky-offset', `${Math.max(headerHeight, 0)}px`);
    }

    container.querySelectorAll('[data-marketplace-carousel]').forEach((button) => {
        button.addEventListener('click', () => {
            const targetId = safeString(button.dataset.marketplaceCarouselTarget);
            const rail = container.querySelector(`#marketplace-rail-${CSS.escape(targetId)}`);
            if (!rail) return;
            const direction = Number(button.dataset.marketplaceCarousel) || 1;
            const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
            rail.scrollBy({ left: direction * Math.max(rail.clientWidth * 0.85, 240), behavior: reduceMotion ? 'auto' : 'smooth' });
        });
    });

    return container.firstElementChild;
}
function moduleRenderMyStuffSurface(container) {
    const config = moduleGetSpecialSurfaceConfig('my_stuff');
    return moduleRenderEmbeddedSurface(container, config || {
        title: 'Project Board',
        src: '/static/my_stuff.html?v=20260624-forge-builds-1',
        surfaceMode: 'immersive',
    });
}

const MODULE_CHANNEL_CATALOG = Object.freeze([
    {
        id: 'discord',
        title: 'Discord',
        icon: 'ph-discord-logo',
        eyebrow: 'Live bridge',
        summary: 'Text chat, wake-word voice, media controls, and delegated access already flow through Thomas.',
        capabilityLabel: 'Text, voice, media',
        accent: 'live',
    },
    {
        id: 'slack',
        title: 'Slack',
        icon: 'ph-slack-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for a first-class Thomas Slack bridge.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'telegram',
        title: 'Telegram',
        icon: 'ph-telegram-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for a first-class Thomas Telegram bridge.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'email',
        title: 'Email',
        icon: 'ph-envelope-simple',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for an indexed Thomas inbox bridge.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'sms',
        title: 'SMS / MMS',
        icon: 'ph-chat-circle-text',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for phone messaging and carrier-backed outreach.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'whatsapp',
        title: 'WhatsApp',
        icon: 'ph-whatsapp-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for a WhatsApp bridge with owner-scoped automation.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'signal',
        title: 'Signal',
        icon: 'ph-chat-teardrop-text',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for a privacy-first Signal bridge.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'imessage',
        title: 'iMessage',
        icon: 'ph-chat-centered-dots',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Apple messaging surfaces and local-device workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'teams',
        title: 'Microsoft Teams',
        icon: 'ph-users-three',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Teams chat, meetings, and workspace controls.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'google_chat',
        title: 'Google Chat',
        icon: 'ph-google-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Google Chat rooms, threads, and workspace context.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'matrix',
        title: 'Matrix',
        icon: 'ph-squares-four',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Matrix rooms and federated community access.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'mattermost',
        title: 'Mattermost',
        icon: 'ph-chats-circle',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for self-hosted team chat and ops workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'twitch_chat',
        title: 'Twitch Chat',
        icon: 'ph-twitch-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for stream chat moderation, clips, and live viewer context.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'youtube_live',
        title: 'YouTube Live',
        icon: 'ph-youtube-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for YouTube live chat and creator workflow actions.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'kick_chat',
        title: 'Kick Chat',
        icon: 'ph-broadcast',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Kick live chat and creator-side control flows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'twitter_dm',
        title: 'X / Twitter DM',
        icon: 'ph-x-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for DMs, mentions, and timeline-triggered workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'instagram_dm',
        title: 'Instagram DM',
        icon: 'ph-instagram-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for creator messaging and social inbox routing.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'facebook_messenger',
        title: 'Messenger',
        icon: 'ph-messenger-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Facebook Messenger and page-side outreach.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'reddit',
        title: 'Reddit',
        icon: 'ph-reddit-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for modmail, replies, and community intelligence.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'github',
        title: 'GitHub',
        icon: 'ph-github-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for issues, PR threads, and repository-side conversation loops.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'xbox',
        title: 'Xbox Live',
        icon: 'ph-game-controller',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Xbox chat and gaming-party workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'playstation',
        title: 'PlayStation',
        icon: 'ph-game-controller',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for PlayStation messaging and party presence.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'steam',
        title: 'Steam Chat',
        icon: 'ph-steam-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Steam chat, lobbies, and PC gaming surfaces.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'web_widget',
        title: 'Web Widget',
        icon: 'ph-browser',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for an embeddable Thomas website chat surface.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'forum',
        title: 'Forums',
        icon: 'ph-rows',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for threaded forum communities and long-form discussions.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'bluesky',
        title: 'Bluesky',
        icon: 'ph-cloud',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Bluesky posts, replies, and direct-message workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'threads',
        title: 'Threads',
        icon: 'ph-at',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Threads conversation loops and creator replies.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'linkedin',
        title: 'LinkedIn',
        icon: 'ph-linkedin-logo',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for professional inbox, post replies, and outreach flows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'line',
        title: 'LINE',
        icon: 'ph-chat-circle-dots',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for LINE messaging and Asia-focused channel automation.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'wechat',
        title: 'WeChat',
        icon: 'ph-chats-circle',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for WeChat messaging, communities, and service workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'viber',
        title: 'Viber',
        icon: 'ph-phone-call',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Viber messaging and voice-adjacent customer touchpoints.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'zoom_chat',
        title: 'Zoom Team Chat',
        icon: 'ph-video-camera',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Zoom team chat, meeting context, and live follow-up.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'meet_chat',
        title: 'Google Meet Chat',
        icon: 'ph-video-camera',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for Meet chat, call notes, and voice-session follow-through.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'zendesk',
        title: 'Zendesk',
        icon: 'ph-headset',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for support-ticket conversations and inbox escalation loops.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'intercom',
        title: 'Intercom',
        icon: 'ph-chat-centered-text',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for product chat, support triage, and customer messaging.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
    {
        id: 'irc',
        title: 'IRC',
        icon: 'ph-hash',
        eyebrow: 'Reserved',
        summary: 'Channel slot reserved for classic IRC channels and community relay workflows.',
        capabilityLabel: 'Catalog slot',
        accent: 'catalog',
    },
]);

function moduleChannelsState() {
    const state = moduleEnsureRuntime();
    if (!state) return null;
    if (!state.channels || typeof state.channels !== 'object') {
        state.channels = {
            loading: false,
            error: '',
            status: null,
            sessions: [],
            hits: [],
            selectedSessionId: '',
            selectedChannelId: '',
            detailOpen: false,
            sessionDetail: null,
            search: '',
            voiceProbeRunning: false,
            voiceProbeResult: null,
            lastLoadedAt: 0,
            requestPromise: null,
        };
    }
    return state.channels;
}

function loadStoredChannelsCatalogOrder() {
    try {
        if (!window?.localStorage || isUiEditorPreviewShell()) return [];
        const raw = window.localStorage.getItem(UI_CHANNELS_CATALOG_ORDER_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed.map((value) => safeString(value).toLowerCase()).filter(Boolean) : [];
    } catch {
        return [];
    }
}

function saveStoredChannelsCatalogOrder(orderRaw) {
    const order = Array.isArray(orderRaw) ? orderRaw.map((value) => safeString(value).toLowerCase()).filter(Boolean) : [];
    try {
        if (!window?.localStorage || isUiEditorPreviewShell()) return;
        window.localStorage.setItem(UI_CHANNELS_CATALOG_ORDER_STORAGE_KEY, JSON.stringify(order));
    } catch {
        // Ignore storage failures.
    }
}

function moduleChannelsCatalogOrder(entriesRaw) {
    const entries = Array.isArray(entriesRaw) ? entriesRaw : [];
    const validIds = new Set(entries.map((entry) => safeString(entry?.id).toLowerCase()).filter(Boolean));
    const stored = loadStoredChannelsCatalogOrder().filter((id) => validIds.has(id));
    const appended = entries
        .map((entry) => safeString(entry?.id).toLowerCase())
        .filter((id) => id && !stored.includes(id));
    const ordered = stored.concat(appended);
    const promoteAfter = (id, anchor) => {
        const itemIndex = ordered.indexOf(id);
        const anchorIndex = ordered.indexOf(anchor);
        if (itemIndex < 0 || anchorIndex < 0 || itemIndex === anchorIndex + 1) return;
        ordered.splice(itemIndex, 1);
        ordered.splice(ordered.indexOf(anchor) + 1, 0, id);
    };
    promoteAfter('paper_trading', 'mission');
    return ordered;
}

function modulePersistChannelsCatalogOrderFromDom() {
    if (!(moduleQueueList instanceof HTMLElement)) return;
    const grid = moduleQueueList.querySelector('[data-channel-grid]');
    if (!(grid instanceof HTMLElement)) return;
    const order = Array.from(grid.querySelectorAll('[data-channel-card-id]'))
        .map((node) => safeString(node.getAttribute('data-channel-card-id')).toLowerCase())
        .filter(Boolean);
    saveStoredChannelsCatalogOrder(order);
}

async function moduleLoadChannelsSession(sessionIdRaw, { silent = false } = {}) {
    const state = moduleChannelsState();
    const sessionId = safeString(sessionIdRaw);
    if (!state || !sessionId) return null;
    try {
        const payload = await moduleFetchJsonSafe(`/api/channels/discord/history/${encodeURIComponent(sessionId)}?limit=12`);
        state.sessionDetail = payload && typeof payload === 'object' ? payload : null;
        state.selectedSessionId = sessionId;
        if (safeString(sidebarNavMode) === 'channels') {
            moduleRender('channels', { touch: false });
        }
        return state.sessionDetail;
    } catch (error) {
        if (!silent) {
            state.error = safeString(error?.message) || 'Could not load Discord session context.';
            if (safeString(sidebarNavMode) === 'channels') {
                moduleRender('channels', { touch: false });
            }
        }
        return null;
    }
}

function moduleChannelsHistoryUrl(state) {
    const query = safeString(state?.search).trim();
    if (!query) return '/api/channels/discord/history?limit=12';
    return `/api/channels/discord/history?q=${encodeURIComponent(query)}&limit=12`;
}

async function moduleRefreshChannels({ force = false } = {}) {
    const state = moduleChannelsState();
    if (!state) return null;
    const ageMs = Date.now() - Number(state.lastLoadedAt || 0);
    if (!force && state.requestPromise) return state.requestPromise;
    if (!force && state.status && ageMs < MODULE_CHANNELS_REFRESH_TTL_MS) return state.status;
    state.loading = true;
    state.error = '';
    const nextRequest = Promise.all([
        moduleFetchJsonSafe('/api/channels/discord'),
        moduleFetchJsonSafe(moduleChannelsHistoryUrl(state)),
    ]).then(async ([statusPayload, historyPayload]) => {
        state.status = statusPayload?.discord || null;
        state.sessions = Array.isArray(historyPayload?.sessions) ? historyPayload.sessions : [];
        state.hits = Array.isArray(historyPayload?.hits) ? historyPayload.hits : [];
        state.lastLoadedAt = Date.now();
        const preferredSessionId = safeString(state.selectedSessionId)
            || safeString(state.sessions?.[0]?.session_id)
            || safeString(state.hits?.[0]?.session_id);
        if (preferredSessionId) {
            if (!state.sessionDetail || safeString(state.sessionDetail?.session?.session_id) !== preferredSessionId) {
                await moduleLoadChannelsSession(preferredSessionId, { silent: true });
            }
        } else {
            state.sessionDetail = null;
        }
        return state.status;
    }).catch((error) => {
        state.error = safeString(error?.message) || 'Failed to load Discord channel state.';
        return null;
    }).finally(() => {
        state.loading = false;
        state.requestPromise = null;
        if (safeString(sidebarNavMode) === 'channels') {
            moduleRender('channels', { touch: false });
        }
    });
    state.requestPromise = nextRequest;
    return nextRequest;
}

function moduleRenderChannelsSurface(container) {
    if (!container) return null;
    const state = moduleChannelsState();
    if (!state) return null;
    const ageMs = Date.now() - Number(state.lastLoadedAt || 0);
    if ((!state.status || ageMs >= MODULE_CHANNELS_REFRESH_TTL_MS) && !state.loading) {
        void moduleRefreshChannels();
    }
    return moduleRenderChannelsSurfaceNext(container, state);

    const statusPayload = state.status && typeof state.status === 'object' ? state.status : {};
    const bridge = statusPayload.bridge && typeof statusPayload.bridge === 'object' ? statusPayload.bridge : {};
    const config = statusPayload.config && typeof statusPayload.config === 'object' ? statusPayload.config : {};
    const runtime = statusPayload.runtime && typeof statusPayload.runtime === 'object' ? statusPayload.runtime : {};
    const conversations = statusPayload.conversations && typeof statusPayload.conversations === 'object' ? statusPayload.conversations : {};
    const sessions = Array.isArray(state.sessions) ? state.sessions : [];
    const hits = Array.isArray(state.hits) ? state.hits : [];
    const selectedSession = state.sessionDetail && typeof state.sessionDetail === 'object' ? state.sessionDetail : null;
    const selectedTurns = Array.isArray(selectedSession?.turns) ? selectedSession.turns : [];
    const selectedMeta = selectedSession?.session && typeof selectedSession.session === 'object' ? selectedSession.session : {};
    const searchText = safeString(state.search);
    const running = Boolean(bridge.running);
    const configured = Boolean(bridge.configured);
    const enabled = Boolean(bridge.enabled);
    const statusLabel = safeString(bridge.status) || (running ? 'running' : configured ? 'stopped' : 'unconfigured');
    const statusTone = running ? 'ready' : configured ? 'catalog' : 'warn';
    const lastUpdatedLabel = Number(state.lastLoadedAt || 0) > 0
        ? missionRelativeTime(new Date(Number(state.lastLoadedAt)).toISOString())
        : 'never';
    const sessionMarkup = sessions.length ? sessions.map((row) => {
        const sessionId = safeString(row?.session_id);
        const isSelected = sessionId && sessionId === safeString(selectedMeta?.session_id || state.selectedSessionId);
        const preview = safeString(row?.preview) || 'No preview yet.';
        const scopeKey = safeString(row?.scope_key) || 'unknown scope';
        const updatedAt = safeString(row?.updated_at);
        return `
            <button
                type="button"
                class="module-item-btn${isSelected ? ' active' : ''}"
                data-channels-session-id="${escapeHtml(sessionId)}"
                style="display:flex;flex-direction:column;align-items:flex-start;gap:4px;width:100%;text-align:left;">
                <strong>${escapeHtml(sessionId || 'session')}</strong>
                <span>${escapeHtml(`${scopeKey} | ${updatedAt ? missionRelativeTime(updatedAt) : 'unknown time'}`)}</span>
                <span>${escapeHtml(preview.slice(0, 140))}</span>
            </button>
        `;
    }).join('') : '<div class="module-empty">No indexed Discord sessions yet.</div>';
    const hitMarkup = searchText && hits.length ? `
        <div style="display:grid;gap:10px;margin-top:14px;">
            ${hits.slice(0, 6).map((hit) => `
                <button
                    type="button"
                    class="module-item-btn"
                    data-channels-session-id="${escapeHtml(safeString(hit?.session_id))}"
                    style="display:flex;flex-direction:column;align-items:flex-start;gap:4px;width:100%;text-align:left;">
                    <strong>${escapeHtml(safeString(hit?.created_at) || safeString(hit?.session_id) || 'match')}</strong>
                    <span>${escapeHtml(safeString(hit?.excerpt) || 'No excerpt available.')}</span>
                </button>
            `).join('')}
        </div>
    ` : '';
    const turnMarkup = selectedTurns.length ? selectedTurns.map((turn) => `
        <article class="module-item-card" style="gap:10px;">
            <div class="module-item-top">
                <h4 class="module-item-title">${escapeHtml(safeString(turn?.display_name) || 'Discord user')}</h4>
                <span class="module-item-badge">${escapeHtml(safeString(turn?.created_at) || '')}</span>
            </div>
            <p class="module-item-meta">${escapeHtml(safeString(turn?.user_text) || '(no user text)')}</p>
            <p class="module-item-meta">${escapeHtml(safeString(turn?.assistant_text) || '(no Thomas reply)')}</p>
        </article>
    `).join('') : '<div class="module-empty">Select a Discord session to inspect recent context.</div>';

    container.innerHTML = `
        <section class="module-channels-shell" style="display:grid;gap:18px;">
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">
                <article class="module-item-card" style="gap:14px;">
                    <div class="module-item-top">
                        <h4 class="module-item-title">Discord Bridge</h4>
                        <span class="marketplace-card-status" data-marketplace-status="${escapeHtml(statusTone)}">${escapeHtml(statusLabel)}</span>
                    </div>
                    <p class="module-item-meta">Lifecycle is Thomas-owned here. Enable the channel separately from starting the bridge process.</p>
                    <p class="module-item-meta">Enabled: ${enabled ? 'On' : 'Off'} | Configured: ${configured ? 'Yes' : 'No'} | Refreshed ${escapeHtml(lastUpdatedLabel)}</p>
                    <div class="module-item-actions">
                        <button type="button" class="module-item-btn" data-channels-action="toggle_enabled">${enabled ? 'Turn Off Channel' : 'Turn On Channel'}</button>
                        <button type="button" class="module-item-btn" data-channels-action="start">Start</button>
                        <button type="button" class="module-item-btn" data-channels-action="stop">Stop</button>
                        <button type="button" class="module-item-btn" data-channels-action="restart">Restart</button>
                        <button type="button" class="module-item-btn" data-channels-action="refresh">Refresh</button>
                    </div>
                    ${safeString(bridge?.last_error) ? `<p class="module-item-meta">${escapeHtml(safeString(bridge.last_error).slice(0, 320))}</p>` : ''}
                </article>
                <article class="module-item-card" style="gap:14px;">
                    <div class="module-item-top">
                        <h4 class="module-item-title">Connect + Configure</h4>
                        <span class="module-item-badge">Bridge .env</span>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
                        <label style="display:grid;gap:6px;">
                            <span>Discord Bot Token</span>
                            <input type="password" class="form-control" data-channels-config-field="bot_token" placeholder="${escapeHtml(safeString(config?.bot_token_masked) || 'Enter new bot token')}" autocomplete="new-password" />
                        </label>
                        <label style="display:grid;gap:6px;">
                            <span>Owner User IDs</span>
                            <input type="text" class="form-control" data-channels-config-field="owner_user_ids" value="${escapeHtml((Array.isArray(config?.owner_user_ids) ? config.owner_user_ids.join(', ') : ''))}" />
                        </label>
                        <label style="display:grid;gap:6px;">
                            <span>Allowed Guild IDs</span>
                            <input type="text" class="form-control" data-channels-config-field="allowed_guild_ids" value="${escapeHtml((Array.isArray(config?.allowed_guild_ids) ? config.allowed_guild_ids.join(', ') : ''))}" />
                        </label>
                        <label style="display:grid;gap:6px;">
                            <span>Auto Channel IDs</span>
                            <input type="text" class="form-control" data-channels-config-field="auto_channel_ids" value="${escapeHtml((Array.isArray(config?.auto_channel_ids) ? config.auto_channel_ids.join(', ') : ''))}" />
                        </label>
                        <label style="display:grid;gap:6px;">
                            <span>Thomas Base URL</span>
                            <input type="text" class="form-control" data-channels-config-field="thomas_base_url" value="${escapeHtml(safeString(config?.thomas_base_url) || 'http://127.0.0.1:8899')}" />
                        </label>
                        <label style="display:grid;gap:6px;">
                            <span>Session Prefix</span>
                            <input type="text" class="form-control" data-channels-config-field="session_prefix" value="${escapeHtml(safeString(config?.session_prefix) || 'thomas-discord')}" />
                        </label>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:14px;">
                        <label style="display:inline-flex;align-items:center;gap:8px;">
                            <input type="checkbox" data-channels-config-field="owner_only_mode" ${config?.owner_only_mode ? 'checked' : ''} />
                            <span>Owner-only mode</span>
                        </label>
                        <label style="display:inline-flex;align-items:center;gap:8px;">
                            <input type="checkbox" data-channels-config-field="require_mention" ${config?.require_mention !== false ? 'checked' : ''} />
                            <span>Require mention</span>
                        </label>
                    </div>
                    <div class="module-item-actions">
                        <button type="button" class="module-item-btn" data-channels-action="save_config">Save Config</button>
                    </div>
                </article>
                <article class="module-item-card" style="gap:14px;">
                    <div class="module-item-top">
                        <h4 class="module-item-title">Conversation Context</h4>
                        <span class="module-item-badge">${escapeHtml(String(conversations?.indexed_turns || 0))} turns</span>
                    </div>
                    <p class="module-item-meta">Bridge sessions tracked: ${escapeHtml(String(conversations?.tracked_bridge_sessions || 0))}</p>
                    <p class="module-item-meta">Indexed sessions: ${escapeHtml(String(conversations?.indexed_sessions || 0))}</p>
                    <p class="module-item-meta">Wake word: ${runtime?.voice_require_wake_word ? 'required' : 'not required'} | Mention mode: ${runtime?.require_mention ? 'mentions only' : 'reply to everyone'}</p>
                    <p class="module-item-meta">Voice profile: ${escapeHtml(safeString(runtime?.voice_profile) || 'unknown')} | Media volume: ${escapeHtml(String(runtime?.voice_media_volume || 0))}% | Delegated grants: ${escapeHtml(String(runtime?.access_grants_count || 0))}</p>
                </article>
            </div>
            <div style="display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:16px;align-items:start;">
                <article class="module-item-card" style="gap:14px;">
                    <div class="module-item-top">
                        <h4 class="module-item-title">Searchable History</h4>
                        <span class="module-item-badge">${state.loading ? 'Refreshing' : 'Ready'}</span>
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                        <input type="search" class="form-control" data-channels-search value="${escapeHtml(searchText)}" placeholder="Search Discord history" style="flex:1 1 220px;" />
                        <button type="button" class="module-item-btn" data-channels-action="search">Search</button>
                        <button type="button" class="module-item-btn" data-channels-action="clear_search">Clear</button>
                    </div>
                    <div style="display:grid;gap:10px;">
                        ${sessionMarkup}
                    </div>
                    ${hitMarkup}
                </article>
                <article class="module-item-card" style="gap:14px;">
                    <div class="module-item-top">
                        <h4 class="module-item-title">Session Context</h4>
                        <span class="module-item-badge">${escapeHtml(safeString(selectedMeta?.session_id) || 'none')}</span>
                    </div>
                    <p class="module-item-meta">${escapeHtml(safeString(selectedMeta?.scope_key) || 'Select a session to inspect metadata and recent turns.')}</p>
                    <div style="display:grid;gap:12px;">
                        ${turnMarkup}
                    </div>
                </article>
            </div>
            ${safeString(state.error) ? `<div class="module-empty">${escapeHtml(state.error)}</div>` : ''}
        </section>
    `;
    return container.firstElementChild;
}

function moduleBuildChannelsSurfaceModel(state) {
    const statusPayload = state?.status && typeof state.status === 'object' ? state.status : {};
    const bridge = statusPayload.bridge && typeof statusPayload.bridge === 'object' ? statusPayload.bridge : {};
    const config = statusPayload.config && typeof statusPayload.config === 'object' ? statusPayload.config : {};
    const runtime = statusPayload.runtime && typeof statusPayload.runtime === 'object' ? statusPayload.runtime : {};
    const conversations = statusPayload.conversations && typeof statusPayload.conversations === 'object' ? statusPayload.conversations : {};
    const sessions = Array.isArray(state?.sessions) ? state.sessions : [];
    const hits = Array.isArray(state?.hits) ? state.hits : [];
    const selectedSession = state?.sessionDetail && typeof state.sessionDetail === 'object' ? state.sessionDetail : null;
    const selectedTurns = Array.isArray(selectedSession?.turns) ? selectedSession.turns : [];
    const selectedMeta = selectedSession?.session && typeof selectedSession.session === 'object' ? selectedSession.session : {};
    const running = Boolean(bridge.running);
    const configured = Boolean(bridge.configured);
    const enabled = Boolean(bridge.enabled);
    const statusLabel = running ? 'Live' : configured ? 'Configured' : 'Not configured';
    const statusTone = running ? 'ready' : configured ? 'ok' : 'catalog';
    const lastUpdatedLabel = Number(state?.lastLoadedAt || 0) > 0
        ? missionRelativeTime(new Date(Number(state.lastLoadedAt)).toISOString())
        : 'never';
    const orderedIds = moduleChannelsCatalogOrder(MODULE_CHANNEL_CATALOG);
    const catalogById = new Map(MODULE_CHANNEL_CATALOG.map((entry) => [entry.id, entry]));
    const catalog = orderedIds.map((id) => catalogById.get(id)).filter(Boolean);
    const selectedChannelId = catalog.some((entry) => entry.id === safeString(state?.selectedChannelId).toLowerCase())
        ? safeString(state?.selectedChannelId).toLowerCase()
        : (catalog[0]?.id || 'discord');
    const selectedChannel = catalog.find((entry) => entry.id === selectedChannelId) || catalog[0] || MODULE_CHANNEL_CATALOG[0];
    const requestKindsText = Array.isArray(selectedMeta?.request_kinds) && selectedMeta.request_kinds.length
        ? selectedMeta.request_kinds.join(', ')
        : 'message';
    const secretStorage = config?.secret_storage && typeof config.secret_storage === 'object' ? config.secret_storage : {};
    const secretStorageLabel = safeString(secretStorage?.encryption) === 'dpapi'
        ? 'Windows current-user encryption'
        : (safeString(secretStorage?.encryption) || 'local secure storage');
    return {
        bridge,
        config,
        runtime,
        conversations,
        sessions,
        hits,
        selectedMeta,
        selectedTurns,
        searchText: safeString(state?.search),
        running,
        configured,
        enabled,
        statusLabel,
        statusTone,
        lastUpdatedLabel,
        catalog,
        selectedChannel,
        selectedChannelId,
        requestKindsText,
        secretStorageLabel,
        configuredCount: configured ? 1 : 0,
        liveCount: running ? 1 : 0,
        indexedTurnCount: Number(conversations?.indexed_turns || 0),
    };
}

function moduleChannelsUiInstanceKey(...parts) {
    const values = parts.map((value) => safeString(value).trim()).filter(Boolean);
    return values.length ? values.map((value) => encodeURIComponent(value)).join('--') : 'unknown';
}

function moduleChannelsProtectedAttrs(sectionRaw, keyRaw, labelRaw, policyRaw = 'controls') {
    const section = moduleChannelsUiInstanceKey(sectionRaw);
    const key = moduleChannelsUiInstanceKey(keyRaw);
    return `data-ui-id="channels.${section}.${key}" data-ui-instance-key="${escapeHtml(key)}" data-ui-label="${escapeHtml(safeString(labelRaw) || 'Protected channel control')}" data-ui-component="protected-control" data-ui-policy="protected ${escapeHtml(safeString(policyRaw) || 'controls')}" data-ui-constraints="preserve-runtime-ids,preserve-handlers"`;
}

function moduleChannelsSessionMarkup(model, state) {
    if (!model.sessions.length) return '<div class="module-empty">No indexed Discord sessions yet.</div>';
    return model.sessions.map((row) => {
        const sessionId = safeString(row?.session_id);
        const isSelected = sessionId && sessionId === safeString(model.selectedMeta?.session_id || state?.selectedSessionId);
        const preview = safeString(row?.preview) || 'No preview yet.';
        const scopeKey = safeString(row?.scope_key) || 'unknown scope';
        const updatedAt = safeString(row?.updated_at);
        const displayName = safeString(row?.display_name) || 'Discord scope';
        const turnCount = Number(row?.turn_count || 0);
        const instanceKey = moduleChannelsUiInstanceKey(sessionId);
        return `
            <button
                type="button"
                class="module-channels-session-btn${isSelected ? ' is-selected' : ''}"
                data-channels-session-id="${escapeHtml(sessionId)}"
                data-ui-id="channels.history.session.${escapeHtml(instanceKey)}"
                data-ui-instance-key="${escapeHtml(instanceKey)}"
                data-ui-label="${escapeHtml(`${displayName} Discord session`)}"
                data-ui-component="repeating-record"
                data-ui-policy="protected controls live-record"
                data-ui-constraints="preserve-runtime-ids,preserve-handlers">
                <div class="module-channels-session-top">
                    <strong>${escapeHtml(displayName)}</strong>
                    <span>${escapeHtml(updatedAt ? missionRelativeTime(updatedAt) : 'unknown time')}</span>
                </div>
                <div class="module-channels-session-tags">
                    <span>${escapeHtml(scopeKey)}</span>
                    <span>${escapeHtml(`${turnCount} turn${turnCount === 1 ? '' : 's'}`)}</span>
                </div>
                <p>${escapeHtml(preview.slice(0, 160))}</p>
            </button>
        `;
    }).join('');
}

function moduleChannelsHitMarkup(model) {
    if (!model.searchText) return '';
    return `
        <div class="module-channels-search-results">
            <div class="module-channels-section-header compact">
                <div>
                    <span class="module-channels-section-kicker">Search results</span>
                    <h4>Matched turns</h4>
                </div>
                <span>${escapeHtml(String(model.hits.length))} hits</span>
            </div>
            <div class="module-channels-hit-list">
            ${model.hits.length ? model.hits.slice(0, 8).map((hit) => {
                const hitKey = moduleChannelsUiInstanceKey(hit?.turn_id, hit?.session_id, hit?.created_at);
                return `
                <button
                    type="button"
                    class="module-channels-hit-card"
                    data-channels-session-id="${escapeHtml(safeString(hit?.session_id))}"
                    data-ui-id="channels.history.hit.${escapeHtml(hitKey)}"
                    data-ui-instance-key="${escapeHtml(hitKey)}"
                    data-ui-label="Discord history match"
                    data-ui-component="repeating-record"
                    data-ui-policy="protected controls live-record"
                    data-ui-constraints="preserve-runtime-ids,preserve-handlers">
                    <div class="module-channels-session-top">
                        <strong>${escapeHtml(safeString(hit?.display_name) || safeString(hit?.session_id) || 'Match')}</strong>
                        <span>${escapeHtml(safeString(hit?.created_at) ? missionRelativeTime(safeString(hit.created_at)) : 'recent')}</span>
                    </div>
                    <div class="module-channels-session-tags">
                        <span>${escapeHtml(safeString(hit?.scope_key) || safeString(hit?.session_id) || 'Discord')}</span>
                        <span>${escapeHtml(safeString(hit?.request_kind) || 'message')}</span>
                    </div>
                    <p>${escapeHtml(safeString(hit?.excerpt) || 'No excerpt available.')}</p>
                </button>
            `;
            }).join('') : '<div class="module-empty">No Discord history matches this query yet.</div>'}
            </div>
        </div>
    `;
}

function moduleChannelsSessionSummaryMarkup(model) {
    if (!safeString(model.selectedMeta?.session_id) && !model.selectedTurns.length) {
        return `
            <div class="module-empty">
                Choose a session on the left to inspect the indexed Discord transcript, metadata, and retrieval anchor Thomas will use for future context.
            </div>
        `;
    }
    const turnCount = Number(model.selectedMeta?.turn_count || model.selectedTurns.length || 0);
    return `
        <div class="module-channels-context-grid" data-ui-id="channels.history.session-summary" data-ui-label="Selected session summary" data-ui-component="panel-group" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=260,minHeight=120,maxHeight=480,collision=avoid">
            <article class="module-channels-context-card" data-ui-id="channels.history.scope-key" data-ui-label="Session scope key" data-ui-policy="move resize-deny contain=parent">
                <span>Scope key</span>
                <strong>${escapeHtml(safeString(model.selectedMeta?.scope_key) || 'not selected')}</strong>
                <em>Thomas retrieval anchor</em>
            </article>
            <article class="module-channels-context-card" data-ui-id="channels.history.guild-channel" data-ui-label="Session guild and channel" data-ui-policy="move resize-deny contain=parent">
                <span>Guild / channel</span>
                <strong>${escapeHtml(safeString(model.selectedMeta?.guild_id) || 'dm')}</strong>
                <em>${escapeHtml(safeString(model.selectedMeta?.channel_id) || 'unknown channel')}</em>
            </article>
            <article class="module-channels-context-card" data-ui-id="channels.history.request-kinds" data-ui-label="Session request kinds" data-ui-policy="move resize-deny contain=parent">
                <span>Request kinds</span>
                <strong>${escapeHtml(model.requestKindsText)}</strong>
                <em>${escapeHtml(`${turnCount} indexed turn${turnCount === 1 ? '' : 's'}`)}</em>
            </article>
            <article class="module-channels-context-card" data-ui-id="channels.history.updated" data-ui-label="Session update time" data-ui-policy="move resize-deny contain=parent">
                <span>Updated</span>
                <strong>${escapeHtml(safeString(model.selectedMeta?.updated_at) ? missionRelativeTime(safeString(model.selectedMeta.updated_at)) : 'unknown')}</strong>
                <em>${escapeHtml(safeString(model.selectedMeta?.session_id) || 'no session selected')}</em>
            </article>
        </div>
    `;
}

function moduleChannelsTurnMarkup(model) {
    if (!model.selectedTurns.length) return '<div class="module-empty">Select a Discord session to inspect recent context.</div>';
    return model.selectedTurns.map((turn) => {
        const turnKey = moduleChannelsUiInstanceKey(turn?.turn_id, model.selectedMeta?.session_id, turn?.created_at);
        return `
        <article class="module-channels-transcript-turn" data-ui-id="channels.history.turn.${escapeHtml(turnKey)}" data-ui-instance-key="${escapeHtml(turnKey)}" data-ui-label="Discord transcript turn" data-ui-component="repeating-record" data-ui-policy="protected live-record" data-ui-constraints="preserve-runtime-ids,preserve-handlers">
            <div class="module-channels-transcript-head">
                <strong>${escapeHtml(safeString(turn?.display_name) || 'Discord user')}</strong>
                <span>${escapeHtml(safeString(turn?.created_at) ? missionRelativeTime(safeString(turn.created_at)) : '')}</span>
            </div>
            <div class="module-channels-transcript-block" data-turn-role="user">
                <span>User said</span>
                <p>${escapeHtml(safeString(turn?.user_text) || '(no user text)')}</p>
            </div>
            <div class="module-channels-transcript-block" data-turn-role="assistant">
                <span>Thomas replied</span>
                <p>${escapeHtml(safeString(turn?.assistant_text) || '(no Thomas reply)')}</p>
            </div>
        </article>
    `;
    }).join('');
}

function moduleChannelsHelpButton(label, description) {
    const helpText = safeString(description);
    if (!helpText) return '';
    const aria = safeString(label) ? `${label}: ${helpText}` : helpText;
    const helpKey = moduleChannelsUiInstanceKey(label || helpText.slice(0, 40));
    return `
        <button
            type="button"
            class="module-channels-help"
            title="${escapeHtml(helpText)}"
            aria-label="${escapeHtml(aria)}"
            data-ui-id="channels.help.${escapeHtml(helpKey)}"
            data-ui-instance-key="${escapeHtml(helpKey)}"
            data-ui-label="${escapeHtml(safeString(label) || 'Channel help')}"
            data-ui-component="help-control"
            data-ui-policy="protected controls">
            <span aria-hidden="true">i</span>
        </button>
    `;
}

function moduleBuildChannelsConfigurePrompt(channel) {
    const title = safeString(channel?.title) || 'channel';
    return [
        `Help me plan a first-class ${title} channel for Thomas.`,
        'Focus on owner-scoped safety, searchable history, lifecycle controls, guided setup, and the minimum human steps required to finish the connection.',
        'List the exact credentials, permissions, APIs, and UI controls Thomas should own on the Thomas side.',
    ].join(' ');
}

