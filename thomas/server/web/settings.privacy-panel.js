document.write(`        <!-- Privacy & Security Settings -->
        <div id="privacy" class="settings-panel" data-ui-id="settings.panel.privacy" data-ui-policy="layout" data-ui-constraints="preserve-control-ids preserve-security-boundaries">
          <div class="panel-title">Privacy & Security</div>
          <div class="panel-description">Manage data privacy, security, and access controls.</div>

          <div class="settings-group" data-ui-id="settings.privacy.data" data-ui-policy="layout" data-ui-constraints="preserve-controls preserve-security-copy">
            <div class="group-title">Data Privacy</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Data Retention</div>
                <div class="setting-description">How long to keep conversation history</div>
              </div>
              <div class="setting-control">
                <select id="dataRetention" class="dropdown-select">
                  <option value="7d">7 days</option>
                  <option value="30d">30 days</option>
                  <option value="90d">90 days</option>
                  <option value="1y">1 year</option>
                  <option value="forever">Forever</option>
                </select>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Auto-delete sensitive data</div>
                <div class="setting-description">Remove passwords, keys, and PII after retention period</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="autoDeleteSensitive" data-setting="autoDeleteSensitive" aria-label="Toggle auto-delete sensitive data" role="switch" aria-checked="true"></button>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.privacy.security" data-ui-policy="protected" data-ui-constraints="no-move no-edit no-delete preserve-breakglass-endpoint">
            <div class="group-title">Security</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Session Encryption</div>
                <div class="setting-description">Encrypt all session data in transit and at rest</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch on" id="sessionEncryption" data-setting="sessionEncryption" aria-label="Toggle session encryption" role="switch" aria-checked="true"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Rate Limiting</div>
                <div class="setting-description">Maximum requests per minute</div>
              </div>
              <div class="setting-control">
                <input type="number" id="rateLimit" class="number-input" min="10" step="10" value="100" />
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.privacy.domains" data-ui-policy="layout" data-ui-constraints="preserve-controls preserve-validation">
            <div class="group-title">Domain Whitelist</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Allowed Domains</div>
                <div class="setting-description">Domains this agent can access (one per line)</div>
              </div>
              <div class="setting-control">
                <textarea id="allowedDomains" style="width: 100%; min-height: 120px; padding: 8px 12px; background-color: #262d3c; border: 1px solid #3a3f4e; border-radius: 6px; color: #e8eaed; font-size: 13px; font-family: 'Menlo', monospace; resize: vertical;" placeholder="example.com&#10;api.service.com&#10;*.company.com" aria-label="Allowed domains list"></textarea>
              </div>
            </div>
          </div>

          <div class="button-group">
            <button class="btn btn-primary" onclick="saveSection('privacy')">
              <i class="ph ph-check"></i>
              Save Changes
            </button>
            <button class="btn btn-secondary" onclick="resetSection('privacy')" data-ui-id="settings.action.reset.privacy" data-ui-policy="protected" data-ui-constraints="no-move no-edit no-delete">
              <i class="ph ph-arrow-counterclockwise"></i>
              Reset
            </button>
          </div>
        </div>

`);
