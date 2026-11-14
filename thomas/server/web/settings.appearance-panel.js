document.write(`        <!-- Appearance Settings -->
        <div id="appearance" class="settings-panel" data-ui-id="settings.panel.appearance" data-ui-policy="layout" data-ui-constraints="preserve-control-ids preserve-save-actions">
          <div class="panel-title">Appearance</div>
          <div class="panel-description">Customize the visual interface.</div>

          <div class="settings-group" data-ui-id="settings.appearance.interface" data-ui-policy="layout" data-ui-constraints="preserve-controls">
            <div class="group-title">Interface</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Font Size</div>
                <div class="setting-description">Base interface font size</div>
              </div>
              <div class="setting-control">
                <select id="fontSize" class="dropdown-select">
                  <option value="small">Small</option>
                  <option value="normal" selected>Normal</option>
                  <option value="large">Large</option>
                  <option value="xlarge">Extra Large</option>
                </select>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Sidebar Position</div>
                <div class="setting-description">Where to display navigation sidebar</div>
              </div>
              <div class="setting-control">
                <select id="sidebarPosition" class="dropdown-select">
                  <option value="left" selected>Left</option>
                  <option value="right">Right</option>
                </select>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Compact Mode</div>
                <div class="setting-description">Reduce spacing and sizes for more density</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="compactMode" data-setting="compactMode" aria-label="Toggle compact mode" role="switch" aria-checked="false"></button>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.appearance.messages" data-ui-policy="layout" data-ui-constraints="preserve-controls">
            <div class="group-title">Chat & Messages</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Chat Bubble Style</div>
                <div class="setting-description">Visual style for conversation bubbles</div>
              </div>
              <div class="setting-control">
                <select id="bubbleStyle" class="dropdown-select">
                  <option value="rounded" selected>Rounded</option>
                  <option value="square">Square</option>
                  <option value="minimal">Minimal</option>
                </select>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Monospace Code</div>
                <div class="setting-description">Use monospace font for code blocks</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch on" id="monospaceCode" data-setting="monospaceCode" aria-label="Toggle monospace code" role="switch" aria-checked="true"></button>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.appearance.notifications" data-ui-policy="layout" data-ui-constraints="preserve-controls">
            <div class="group-title">Notifications</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Desktop Notifications</div>
                <div class="setting-description">Show system notifications for agent events</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch on" id="desktopNotifications" data-setting="desktopNotifications" aria-label="Toggle desktop notifications" role="switch" aria-checked="true"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Sound Alerts</div>
                <div class="setting-description">Play sound on important events</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="soundAlerts" data-setting="soundAlerts" aria-label="Toggle sound alerts" role="switch" aria-checked="false"></button>
              </div>
            </div>
          </div>

          <div class="button-group">
            <button class="btn btn-primary" onclick="saveSection('appearance')">
              <i class="ph ph-check"></i>
              Save Changes
            </button>
            <button class="btn btn-secondary" onclick="resetSection('appearance')" data-ui-id="settings.action.reset.appearance" data-ui-policy="protected" data-ui-constraints="no-move no-edit no-delete">
              <i class="ph ph-arrow-counterclockwise"></i>
              Reset
            </button>
          </div>
        </div>

`);
