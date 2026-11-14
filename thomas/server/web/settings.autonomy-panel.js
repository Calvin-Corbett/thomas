document.write(`<!-- Autonomy Settings -->
        <div id="autonomy" class="settings-panel" data-ui-id="settings.panel.autonomy" data-ui-policy="layout" data-ui-constraints="preserve-control-ids preserve-approval-boundaries">
          <div class="panel-title">Autonomy</div>
          <div class="panel-description">Control agent decision-making and automatic actions.</div>

          <div class="settings-group" data-ui-id="settings.autonomy.level" data-ui-policy="layout" data-ui-constraints="preserve-controls">
            <div class="group-title">Autonomy Level</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Agent Autonomy</div>
                <div class="setting-description">Decision-making capability level</div>
              </div>
              <div class="setting-control">
                <select id="autonomyLevel" class="dropdown-select">
                  <option value="L1">L1 - Manual Only (requires approval for all actions)</option>
                  <option value="L2">L2 - Semi-Autonomous (approval for important actions)</option>
                  <option value="L3">L3 - Mostly Autonomous (approval for risky actions only)</option>
                  <option value="L4">L4 - Full Autonomy (self-governing within constraints)</option>
                </select>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.autonomy.thresholds" data-ui-policy="layout" data-ui-constraints="preserve-controls preserve-safety-copy">
            <div class="group-title">Auto-Approval Thresholds</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Cost Limit</div>
                <div class="setting-description">Max API cost per action without approval</div>
              </div>
              <div class="setting-control">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span>$</span>
                  <input type="number" id="costLimit" class="number-input" min="0" step="0.10" value="1.00" />
                </div>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Time Commitment</div>
                <div class="setting-description">Max hours per task without approval</div>
              </div>
              <div class="setting-control">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <input type="number" id="timeCommitment" class="number-input" min="0.25" step="0.25" value="4" />
                  <span>hours</span>
                </div>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Auto-approve with notification</div>
                <div class="setting-description">Execute action and notify instead of requesting approval</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="autoApproveNotify" data-setting="autoApproveNotify" aria-label="Toggle auto-approve with notification" role="switch" aria-checked="false"></button>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.autonomy.behavior" data-ui-policy="layout" data-ui-constraints="preserve-controls">
            <div class="group-title">Behavior</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Idle Timeout</div>
                <div class="setting-description">Minutes before pausing autonomous actions</div>
              </div>
              <div class="setting-control">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <input type="number" id="idleTimeout" class="number-input" min="5" step="5" value="30" />
                  <span>min</span>
                </div>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Take initiative on errors</div>
                <div class="setting-description">Automatically retry or recover from failures</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="initiativeOnErrors" data-setting="initiativeOnErrors" aria-label="Toggle initiative on errors" role="switch" aria-checked="true"></button>
              </div>
            </div>
          </div>

          <div class="settings-group" data-ui-id="settings.autonomy.tools" data-ui-policy="layout" data-ui-constraints="preserve-controls preserve-safety-copy">
            <div class="group-title">Tool Permissions</div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Shell / Terminal Access</div>
                <div class="setting-description">Allow Thomas to run shell commands (install packages, run scripts, etc.)</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowShell" data-setting="allowShell" aria-label="Toggle shell access" role="switch" aria-checked="false"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Browser / Web Browsing</div>
                <div class="setting-description">Allow Thomas to open pages, click, type, and take screenshots in a browser</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowBrowser" data-setting="allowBrowser" aria-label="Toggle browser access" role="switch" aria-checked="false"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Git Operations</div>
                <div class="setting-description">Allow Thomas to commit, push, pull, and manage repositories</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowGit" data-setting="allowGit" aria-label="Toggle git access" role="switch" aria-checked="false"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">File System Access</div>
                <div class="setting-description">Allow Thomas to read, write, edit, and delete files</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch on" id="allowFilesystem" data-setting="allowFilesystem" aria-label="Toggle filesystem access" role="switch" aria-checked="true"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Web Search</div>
                <div class="setting-description">Allow Thomas to search the web for information</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch on" id="allowWebSearch" data-setting="allowWebSearch" aria-label="Toggle web search" role="switch" aria-checked="true"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Email & Calendar</div>
                <div class="setting-description">Allow Thomas to read and send emails, manage calendar events</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowEmail" data-setting="allowEmail" aria-label="Toggle email access" role="switch" aria-checked="false"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">Database Access</div>
                <div class="setting-description">Allow Thomas to query and modify databases</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowDatabase" data-setting="allowDatabase" aria-label="Toggle database access" role="switch" aria-checked="false"></button>
              </div>
            </div>
            <div class="setting-item">
              <div class="setting-label">
                <div class="setting-name">SSH / Remote Access</div>
                <div class="setting-description">Allow Thomas to connect to remote servers via SSH</div>
              </div>
              <div class="setting-control">
                <button class="toggle-switch" id="allowSSH" data-setting="allowSSH" aria-label="Toggle SSH access" role="switch" aria-checked="false"></button>
              </div>
            </div>
          </div>

          <div class="button-group">
            <button class="btn btn-primary" onclick="saveSection('autonomy')">
              <i class="ph ph-check"></i>
              Save Changes
            </button>
            <button class="btn btn-secondary" onclick="resetSection('autonomy')" data-ui-id="settings.action.reset.autonomy" data-ui-policy="protected" data-ui-constraints="no-move no-edit no-delete">
              <i class="ph ph-arrow-counterclockwise"></i>
              Reset
            </button>
          </div>
        </div>

`);
