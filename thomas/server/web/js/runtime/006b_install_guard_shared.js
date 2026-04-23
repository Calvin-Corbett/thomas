function normalizeInstallGuardProfile(profileRaw) {
    const raw = safeString(profileRaw).toLowerCase().replace(/-/g, '_');
    if (!raw || raw === 'default' || raw === 'standard') return 'balanced';
    if (raw === 'builder' || raw === 'hands_on') return 'hands_on';
    if (raw === 'locked' || raw === 'review_only' || raw === 'check_only') return 'review_only';
    return new Set(['balanced', 'hands_on', 'review_only']).has(raw) ? raw : 'balanced';
}

function getInstallGuardOptions() {
    const options = Array.isArray(easySetupState?.securityProfiles) ? easySetupState.securityProfiles : [];
    if (options.length) return options;
    return [
        {
            id: 'balanced',
            title: 'Balanced',
            summary: 'Pinned installs, no silent mutation, and explicit approval before Thomas installs tools or applies updates.',
            tradeoff: 'Best default for most users who want safety without extra friction.',
        },
        {
            id: 'hands_on',
            title: 'Hands-On',
            summary: 'Same install guardrails as Balanced, but tuned for active product work with the assistant.',
            tradeoff: 'Best when you want Thomas to help you modify the product after explicit approval.',
        },
        {
            id: 'review_only',
            title: 'Review Only',
            summary: 'Thomas can inspect and explain, but it will not install tools or apply updates.',
            tradeoff: 'Best for sensitive machines where environment changes should stay manual.',
        },
    ];
}

function getInstallGuardOption(profileRaw) {
    const normalized = normalizeInstallGuardProfile(profileRaw);
    const options = getInstallGuardOptions();
    return options.find((item) => normalizeInstallGuardProfile(item?.id) === normalized) || options[0] || {
        id: 'balanced',
        title: 'Balanced',
        summary: '',
        tradeoff: '',
    };
}

function formatInstallGuardCapabilities(capabilities) {
    const caps = capabilities || {};
    const installs = Boolean(caps.tool_install_allowed) ? 'tool installs allowed after approval' : 'tool installs blocked';
    const updates = Boolean(caps.update_apply_allowed) ? 'update apply allowed after approval' : 'update apply blocked';
    return `${installs}; ${updates}.`;
}

function renderEasySetupSecurityProfiles() {
    if (!easySetupSecurityProfileGrid) return;
    const options = getInstallGuardOptions();
    const active = normalizeInstallGuardProfile(easySetupState.securityProfile);
    easySetupSecurityProfileGrid.innerHTML = '';
    options.forEach((option) => {
        const normalized = normalizeInstallGuardProfile(option?.id);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'easy-setup-path-card easy-setup-security-card';
        button.dataset.securityProfile = normalized;
        button.setAttribute('aria-pressed', normalized === active ? 'true' : 'false');
        button.classList.toggle('selected', normalized === active);
        button.innerHTML = `
            <strong>${escapeHtml(option?.title || normalized)}</strong>
            <span>${escapeHtml(option?.summary || '')}</span>
            <small>${escapeHtml(option?.tradeoff || '')}</small>
        `;
        easySetupSecurityProfileGrid.appendChild(button);
    });

    if (easySetupSecurityProfileHint) {
        const selected = getInstallGuardOption(active);
        const capabilities = easySetupState.bootstrap?.security_capabilities || null;
        easySetupSecurityProfileHint.textContent = `${safeString(selected?.summary)} ${formatInstallGuardCapabilities(capabilities)}`.trim();
    }
}

async function persistInstallGuardProfile(profileRaw) {
    const normalized = normalizeInstallGuardProfile(profileRaw);
    const res = await fetchJsonSafe('/api/setup/security-profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: normalized }),
    });
    if (!res.ok) {
        throw new Error(res.text || `Install Guard update failed (${res.status})`);
    }
    const data = res.data || {};
    easySetupState.securityProfile = normalizeInstallGuardProfile(data.security_profile || normalized);
    easySetupState.securityProfiles = Array.isArray(data.security_profiles) ? data.security_profiles : getInstallGuardOptions();
    setupBootstrapSnapshot = {
        ...(setupBootstrapSnapshot || {}),
        ...(easySetupState.bootstrap || {}),
        security_profile: easySetupState.securityProfile,
        security_capabilities: data.security_capabilities || easySetupState.bootstrap?.security_capabilities || {},
        security_profiles: easySetupState.securityProfiles,
    };
    easySetupState.bootstrap = setupBootstrapSnapshot;
    renderEasySetupSecurityProfiles();
    return data;
}

function syncSettingsInstallGuardUi(bootstrap = setupBootstrapSnapshot) {
    const option = getInstallGuardOption(bootstrap?.security_profile || settingSecurityProfile?.value || 'balanced');
    const capabilities = bootstrap?.security_capabilities || null;
    if (settingSecurityProfile) {
        settingSecurityProfile.value = normalizeInstallGuardProfile(option?.id);
    }
    if (settingSecurityProfileSummary) {
        settingSecurityProfileSummary.textContent = safeString(option?.summary)
            || 'Controls whether Thomas can install tools or apply updates after you approve them.';
    }
    if (settingSecurityProfileCapabilities) {
        let detail = formatInstallGuardCapabilities(capabilities);
        const blocked = capabilities?.blocked_actions || {};
        const blockMessages = [safeString(blocked.tool_install), safeString(blocked.update_apply)].filter(Boolean);
        if (blockMessages.length) {
            detail += ` ${blockMessages.join(' ')}`;
        }
        settingSecurityProfileCapabilities.textContent = detail;
    }
    if (settingSecurityProfileWhy) {
        settingSecurityProfileWhy.textContent = safeString(option?.tradeoff)
            || 'This writes to thomas.toml so the launcher, setup scripts, and updater all use the same mode.';
    }
}
