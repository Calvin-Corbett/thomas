// Extracted from part-027b.js
// From brushes

                                    <strong>Stream embed blocked.</strong>
                                    <p>Target denies iframe embedding. Use Open Stream, or enable framing on the Unreal stream host.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="module-wb-gs-terminal">
                        <div class="module-wb-gs-terminal-head">Output Log</div>
                        <div class="module-wb-log-list" data-game-logs></div>
                    </div>
                </section>
            </div>
        </section>
        <aside class="module-wb-inspector-card module-wb-gs-right">
            <h4>Session Stats</h4>
            <div class="module-wb-metrics" data-game-metrics></div>
            <h4>Selection Details</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field module-wb-field-wide">Name<input type="text" data-game-actor-name placeholder="Select actor from outliner" /></label>
                <label class="module-wb-field">Class
                    <select data-game-actor-class>
                        <option value="platform">Platform</option>
                        <option value="hazard">Hazard</option>
                        <option value="spawn">Spawn</option>
                        <option value="goal">Goal</option>
                        <option value="npc">NPC</option>
                        <option value="pickup">Pickup</option>
                        <option value="trigger">Trigger</option>
                        <option value="light">Light</option>
                        <option value="camera">Camera</option>
                        <option value="marker">Marker</option>
                    </select>
                </label>
                <label class="module-wb-field">X<input type="number" step="0.1" data-game-actor-x value="0" /></label>
                <label class="module-wb-field">Y<input type="number" step="0.1" data-game-actor-y value="0" /></label>
                <label class="module-wb-field">Z<input type="number" step="0.1" data-game-actor-z value="0" /></label>
                <label class="module-wb-field">Rot X<input type="number" step="1" data-game-actor-rx value="0" /></label>
                <label class="module-wb-field">Rot Y<input type="number" step="1" data-game-actor-ry value="0" /></label>
                <label class="module-wb-field">Rot Z<input type="number" step="1" data-game-actor-rz value="0" /></label>
                <label class="module-wb-field">Scale X<input type="number" step="0.1" data-game-actor-sx value="1" /></label>
                <label class="module-wb-field">Scale Y<input type="number" step="0.1" data-game-actor-sy value="1" /></label>
                <label class="module-wb-field">Scale Z<input type="number" step="0.1" data-game-actor-sz value="1" /></label>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-game-action="apply_actor">Apply Actor</button>
                <button type="button" class="module-item-btn" data-game-action="delete_actor">Delete Actor</button>
            </div>
            <p class="module-wb-hint" data-game-actor-meta>Select an actor to edit transform and class.</p>
            <h4>Unreal Bridge Session</h4>
            <div class="module-wb-metrics" data-game-bridge-metrics></div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-game-action="bridge_ping">Ping</button>
                <button type="button" class="module-item-btn" data-game-action="bridge_pull">Pull State</button>
                <button type="button" class="module-item-btn" data-game-action="bridge_push_actor">Push Selected</button>
                <button type="button" class="module-item-btn" data-game-action="bridge_push_scene">Push Scene</button>
            </div>
            <p class="module-wb-hint" data-game-bridge-status>Bridge idle.</p>
            <h4>Details + Engine Bridge</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field module-wb-field-wide">Godot project path<input type="text" data-game-path="godot" value="${escapeHtml(wb.godotProjectPath)}" /></label>
                <label class="module-wb-field module-wb-field-wide">Unreal .uproject path<input type="text" data-game-path="unreal" value="${escapeHtml(wb.unrealProjectPath)}" /></label>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-game-action="godot_export">Godot Export</button>
                <button type="button" class="module-item-btn" data-game-action="unreal_export">Unreal Export</button>
                <button type="button" class="module-item-btn" data-game-action="godot_tscn">Godot TSCN</button>
                <button type="button" class="module-item-btn" data-game-action="unreal_csv">Unreal CSV</button>
                <button type="button" class="module-item-btn" data-game-action="godot_open">Copy Godot Open</button>
                <button type="button" class="module-item-btn" data-game-action="godot_build">Copy Godot Build</button>
                <button type="button" class="module-item-btn" data-game-action="unreal_open">Copy Unreal Open</button>
                <button type="button" class="module-item-btn" data-game-action="unreal_build">Copy Unreal Build</button>
            </div>
            <h4>Unreal Viewport Link</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field module-wb-field-wide">Pixel Streaming URL<input type="text" data-game-unreal-url value="${escapeHtml(wb.unrealViewportUrl)}" placeholder="http://127.0.0.1:8888" /></label>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-game-action="connect_unreal">Connect</button>
                <button type="button" class="module-item-btn" data-game-action="reload_unreal">Reload</button>
                <button type="button" class="module-item-btn" data-game-action="open_unreal">Open Popout</button>
            </div>
            <p class="module-wb-hint">If iframe embed is blocked by host policy, use Open Popout and keep Remote Control connected.</p>
            <details class="module-wb-collapsible">
                <summary>Unreal Remote Control (Advanced)</summary>
                <div class="module-wb-field-grid">
                    <label class="module-wb-field">Base URL<input type="text" data-game-rc-url value="${escapeHtml(wb.unrealRcUrl)}" placeholder="http://127.0.0.1:30010" /></label>
                    <label class="module-wb-field">Endpoint<input type="text" data-game-rc-endpoint value="${escapeHtml(wb.unrealRcEndpoint)}" placeholder="/remote/object/call" /></label>
                    <label class="module-wb-field module-wb-field-wide">Payload JSON<textarea rows="6" data-game-rc-payload>${escapeHtml(wb.unrealRcPayload)}</textarea></label>
                    <label class="module-wb-field module-wb-field-wide">Response<textarea rows="7" data-game-rc-response readonly>${escapeHtml(wb.unrealRcResponse)}</textarea></label>
                </div>
                <div class="module-wb-inspector-actions">
                    <button type="button" class="module-item-btn" data-game-action="rc_send">Send to Unreal</button>
                </div>
            </details>
        </aside>
        ${moduleWorkbenchRenderOssStack('game_studio')}
    `;
    container.appendChild(shell);

    const brushes = [
        { id: 0, label: 'Erase' },
        { id: 1, label: 'Platform' },
        { id: 2, label: 'Hazard' },
        { id: 3, label: 'Spawn' },
        { id: 4, label: 'Goal' },