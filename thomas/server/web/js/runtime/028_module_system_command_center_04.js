function moduleRenderWorkbench(modeRaw, snapshot, signals, definition, { force = false } = {}) {
    if (!moduleWorkbench) return;
    const mode = MODULE_NAV_MODE_SET.has(modeRaw) ? modeRaw : 'dashboard';
    const runtime = moduleEnsureRuntime();
    if (!runtime) return;
    if (!MODULE_WORKBENCH_MODES.has(mode)) {
        if (runtime.workbenchMode && runtime.workbenchMode !== mode) {
            moduleWorkbenchTeardown(runtime.workbenchMode);
        }
        moduleWorkbench.classList.add('hidden');
        moduleWorkbench.dataset.mode = '';
        moduleWorkbench.innerHTML = '';
        runtime.workbenchMode = '';
        return;
    }

    const wb = moduleWorkbenchState(mode);
    if (!wb) {
        moduleWorkbench.classList.add('hidden');
        return;
    }

    const modeChanged = runtime.workbenchMode !== mode;
    moduleWorkbench.classList.remove('hidden');
    moduleWorkbench.dataset.mode = mode;

    if (!force && !modeChanged && wb.mounted) {
        return;
    }

    if (modeChanged && runtime.workbenchMode) {
        moduleWorkbenchTeardown(runtime.workbenchMode);
    }

    moduleWorkbench.innerHTML = '';
    moduleWorkbenchOperatorPreamble(moduleWorkbench, mode);
    if (mode === 'lab_3d') {
        moduleRenderWorkbenchLab3d(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'automations') {
        moduleRenderWorkbenchAutomations(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'app_builder') {
        moduleRenderWorkbenchAppBuilder(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'studio') {
        moduleRenderWorkbenchStudio(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'dev_studio') {
        moduleRenderWorkbenchDevStudio(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'game_studio') {
        moduleRenderWorkbenchGameStudio(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'research_lab') {
        moduleRenderWorkbenchResearch(moduleWorkbench, wb, { signals, snapshot, definition });
    } else if (mode === 'vibe_code') {
        moduleRenderWorkbenchVibeCode(moduleWorkbench, wb, { signals, snapshot, definition });
    } else {
        moduleWorkbench.classList.add('hidden');
    }

    wb.mounted = true;
    runtime.workbenchMode = mode;
}

function moduleRenderWorkbenchVibeCode(container, wb, _context = {}) {
    if (!(container instanceof HTMLElement)) return;
    const mount = document.createElement('section');
    mount.className = 'module-wb-vibe-shell';
    container.appendChild(mount);
    vibeCodeEnsurePanel(mount);
    vibeCodeRender();
    wb.mounted = true;
}

function moduleWorkbenchClamp(value, min, max) {
    const number = Number(value);
    if (!Number.isFinite(number)) return min;
    if (number < min) return min;
    if (number > max) return max;
    return number;
}

function moduleWorkbenchTimeStamp() {
    return new Date().toISOString().slice(11, 19);
}

function moduleLab3dDefaultColor(type) {
    if (type === 'circle') return '#79d2b8';
    if (type === 'line') return '#ffd59a';
    return '#83c6ff';
}

function moduleLab3dShapeById(wb, shapeId) {
    if (!wb || !Array.isArray(wb.shapes)) return null;
    return wb.shapes.find((shape) => safeString(shape?.id) === safeString(shapeId)) || null;
}

function moduleLab3dMetrics(shapeRaw) {
    const shape = shapeRaw && typeof shapeRaw === 'object' ? shapeRaw : {};
    const type = safeString(shape.type);
    if (type === 'line') {
        const dx = (Number(shape.x2) || 0) - (Number(shape.x) || 0);
        const dy = (Number(shape.y2) || 0) - (Number(shape.y) || 0);
        const length = Math.sqrt((dx * dx) + (dy * dy));
        return { area: 0, perimeter: length, volume: 0 };
    }
    const depth = Math.max(0, Number(shape.depth) || 0);
    if (type === 'circle') {
        const radius = Math.max(1, Math.max(Number(shape.w) || 0, Number(shape.h) || 0) / 2);
        const area = Math.PI * radius * radius;
        const perimeter = 2 * Math.PI * radius;
        return { area, perimeter, volume: area * depth };
    }
    const width = Math.max(0, Number(shape.w) || 0);
    const height = Math.max(0, Number(shape.h) || 0);
    const area = width * height;
    const perimeter = (width * 2) + (height * 2);
    return { area, perimeter, volume: area * depth };
}

function moduleLab3dHitShape(shapeRaw, pointRaw) {
    const shape = shapeRaw && typeof shapeRaw === 'object' ? shapeRaw : {};
    const point = pointRaw && typeof pointRaw === 'object' ? pointRaw : { x: 0, y: 0 };
    const type = safeString(shape.type);
    if (type === 'line') {
        const x1 = Number(shape.x) || 0;
        const y1 = Number(shape.y) || 0;
        const x2 = Number(shape.x2) || x1;
        const y2 = Number(shape.y2) || y1;
        const px = Number(point.x) || 0;
        const py = Number(point.y) || 0;
        const abx = x2 - x1;
        const aby = y2 - y1;
        const denom = (abx * abx) + (aby * aby);
        if (denom <= 0.001) return Math.hypot(px - x1, py - y1) < 8;
        const t = moduleWorkbenchClamp((((px - x1) * abx) + ((py - y1) * aby)) / denom, 0, 1);
        const cx = x1 + (abx * t);
        const cy = y1 + (aby * t);
        return Math.hypot(px - cx, py - cy) < 8;
    }
    const x = Number(shape.x) || 0;
    const y = Number(shape.y) || 0;
    const w = Number(shape.w) || 0;
    const h = Number(shape.h) || 0;
    if (type === 'circle') {
        const cx = x + (w / 2);
        const cy = y + (h / 2);
        const r = Math.max(1, Math.max(w, h) / 2);
        const dx = (Number(point.x) || 0) - cx;
        const dy = (Number(point.y) || 0) - cy;
        return ((dx * dx) + (dy * dy)) <= (r * r);
    }
    return (Number(point.x) || 0) >= x
        && (Number(point.x) || 0) <= (x + w)
        && (Number(point.y) || 0) >= y
        && (Number(point.y) || 0) <= (y + h);
}

// 
//   WORKBENCH EDITORS                                                      
//   Lab 3D, Automations, App Builder, Studio, Dev Studio, Game Studio,     
//   Research Lab  rich interactive editors for each workbench mode         
// 

function moduleRenderWorkbenchLab3dOss(container, wb) {
    if (!container || !wb) return false;
    if (wb.ossError) return false;
    if (!wb.ossReady || !wb.ossThree) {
        moduleWorkbenchRenderEngineLoading(
            container,
            '3D Lab CAD Engine',
            'Three.js viewport with transform controls and scene export.',
            'Loading Three.js modules...',
            'Falling back to local sketch mode if loading fails.',
        );
        if (!wb.ossLoading) {
            wb.ossLoading = true;
            void moduleWorkbenchLoadThreeBundle().then((bundle) => {
                wb.ossThree = bundle;
                wb.ossReady = true;
                wb.ossLoading = false;
                wb.ossError = '';
                moduleWorkbenchRefreshMode('lab_3d');
            }).catch((error) => {
                wb.ossLoading = false;
                wb.ossReady = false;
                wb.ossError = safeString(error?.message) || 'Failed to load 3D engine.';
                notifyUser('3D engine failed to load, using fallback canvas.', { tone: 'warn', durationMs: 2400, debugKind: 'lab3d' });
                moduleWorkbenchRefreshMode('lab_3d');
            });
        }
        return true;
    }

    const { THREE, OrbitControls, TransformControls, GLTFExporter, STLExporter } = wb.ossThree;
    if (!THREE || !OrbitControls || !TransformControls) return false;
    if (!Array.isArray(wb.objects)) wb.objects = [];
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.units = safeString(wb.units) || 'mm';
    wb.transformMode = safeString(wb.transformMode) || 'translate';
    wb.transformSpace = safeString(wb.transformSpace) === 'local' ? 'local' : 'world';
    wb.transformSnap = Boolean(wb.transformSnap);
    wb.showGrid = wb.showGrid !== false;
    wb.wireframe = Boolean(wb.wireframe);
    wb.selectedId = safeString(wb.selectedId);
    wb.selectedProjectId = safeString(wb.selectedProjectId);

    if (!wb.objects.length) {
        wb.objects.push({
            id: `mesh-${wb.nextId++}`,
            name: 'Base Cube',
            type: 'box',
            color: '#7fbfff',
            position: { x: 0, y: 0.5, z: 0 },
            rotation: { x: 0, y: 0, z: 0 },
            scale: { x: 1, y: 1, z: 1 },
        });
    }

    moduleWorkbenchHeader(container, '3D Lab CAD Engine', 'Thomas runs 3D scene jobs while you monitor geometry, transforms, and export state.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-lab3d-oss';
    shell.innerHTML = `
        <div class="module-wb-toolbar">
            <div class="module-wb-tool-group">
                <button type="button" class="module-wb-tool-btn" data-lab3d-add="box"><i class="ph ph-cube"></i><span>Cube</span></button>
                <button type="button" class="module-wb-tool-btn" data-lab3d-add="sphere"><i class="ph ph-circle"></i><span>Sphere</span></button>
                <button type="button" class="module-wb-tool-btn" data-lab3d-add="cylinder"><i class="ph ph-cylinder"></i><span>Cylinder</span></button>
            </div>
            <div class="module-wb-tool-group">
                <button type="button" class="module-wb-tool-btn${wb.transformMode === 'translate' ? ' active' : ''}" data-lab3d-transform="translate">Move</button>
                <button type="button" class="module-wb-tool-btn${wb.transformMode === 'rotate' ? ' active' : ''}" data-lab3d-transform="rotate">Rotate</button>
                <button type="button" class="module-wb-tool-btn${wb.transformMode === 'scale' ? ' active' : ''}" data-lab3d-transform="scale">Scale</button>
            </div>
            <div class="module-wb-toolbar-actions">
                <button type="button" class="module-item-btn" data-lab3d-action="snap">${wb.transformSnap ? 'Snap On' : 'Snap Off'}</button>
                <button type="button" class="module-item-btn" data-lab3d-action="space">${wb.transformSpace === 'local' ? 'Local' : 'World'}</button>
                <button type="button" class="module-item-btn" data-lab3d-action="wireframe">${wb.wireframe ? 'Wireframe' : 'Shaded'}</button>
                <button type="button" class="module-item-btn" data-lab3d-action="grid">${wb.showGrid ? 'Grid On' : 'Grid Off'}</button>
                <button type="button" class="module-item-btn" data-lab3d-action="import_json">Import JSON</button>
                <button type="button" class="module-item-btn" data-lab3d-action="delete">Delete</button>
                <button type="button" class="module-item-btn" data-lab3d-action="export">Export JSON</button>
                <button type="button" class="module-item-btn" data-lab3d-action="export_gltf">Export GLTF</button>
                <button type="button" class="module-item-btn" data-lab3d-action="export_stl">Export STL</button>
            </div>
        </div>
        ${moduleWorkbenchRenderProjectControls('lab_3d', 'Model Projects')}
        <div class="module-wb-main-grid module-wb-main-grid-lab3d">
            <section class="module-wb-stage-card">
                <div class="module-wb-stage-head"><span class="module-wb-stage-title">Viewport</span><span class="module-wb-stage-meta" data-lab3d-status></span></div>
                <div class="module-wb-3d-stage" data-lab3d-stage></div>
                <p class="module-wb-hint">Click meshes to select. Drag gizmo handles for precision transforms.</p>
            </section>
            <aside class="module-wb-inspector-card" data-lab3d-inspector></aside>
        </div>
        ${moduleWorkbenchRenderOssStack('lab_3d')}
        <input type="file" class="hidden" data-lab3d-import-json accept=".json,application/json" />
    `;
    container.appendChild(shell);

    const stage = shell.querySelector('[data-lab3d-stage]');
    const inspector = shell.querySelector('[data-lab3d-inspector]');
    const status = shell.querySelector('[data-lab3d-status]');
    const importInput = shell.querySelector('[data-lab3d-import-json]');
    if (!(stage instanceof HTMLElement) || !(inspector instanceof HTMLElement) || !(status instanceof HTMLElement)) {
        return false;
    }

    if (wb.ossEngine?.dispose) {
        try {
            wb.ossEngine.dispose();
        } catch (_error) {}
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f1928);
    const camera = new THREE.PerspectiveCamera(52, 1, 0.1, 200);
    camera.position.set(4.2, 3.4, 6.1);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    stage.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1.5;
    controls.maxDistance = 50;

    const transform = new TransformControls(camera, renderer.domElement);
    transform.setMode(wb.transformMode);
    transform.setSpace(wb.transformSpace);
    transform.size = 0.78;
    if (wb.transformSnap) {
        transform.setTranslationSnap(0.25);
        transform.setRotationSnap(Math.PI / 12);
        transform.setScaleSnap(0.1);
    } else {
        transform.setTranslationSnap(null);
        transform.setRotationSnap(null);
        transform.setScaleSnap(null);
    }
    transform.addEventListener('dragging-changed', (event) => {
        controls.enabled = !Boolean(event?.value);
    });
    if (typeof transform.getHelper === 'function') {
        scene.add(transform.getHelper());
    } else {
        scene.add(transform);
    }

    scene.add(new THREE.AmbientLight(0xffffff, 0.42));
    const keyLight = new THREE.DirectionalLight(0xd8ecff, 0.92);
    keyLight.position.set(4, 8, 5);
    keyLight.castShadow = true;
    scene.add(keyLight);
    const gridHelper = new THREE.GridHelper(24, 24, 0x2d5d8f, 0x1a334e);
    gridHelper.visible = wb.showGrid;
    scene.add(gridHelper);
    scene.add(new THREE.AxesHelper(1.25));

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const meshes = new Map();

    const cleanColor = (value, fallback = '#7fbfff') => (/^#[0-9a-f]{6}$/i.test(safeString(value)) ? safeString(value) : fallback);
    const ensureVector3 = (raw, fallback) => ({
        x: Number.isFinite(Number(raw?.x)) ? Number(raw.x) : fallback.x,
        y: Number.isFinite(Number(raw?.y)) ? Number(raw.y) : fallback.y,
        z: Number.isFinite(Number(raw?.z)) ? Number(raw.z) : fallback.z,
    });
    const geometryFor = (typeRaw) => {
        const type = safeString(typeRaw);
        if (type === 'sphere') return new THREE.SphereGeometry(0.55, 28, 20);
        if (type === 'cylinder') return new THREE.CylinderGeometry(0.42, 0.42, 1.15, 28);
        return new THREE.BoxGeometry(1, 1, 1);
    };
    const materialFor = (colorRaw) => new THREE.MeshStandardMaterial({
        color: cleanColor(colorRaw, '#7fbfff'),
        metalness: 0.2,
        roughness: 0.52,
        wireframe: wb.wireframe,
    });
    const toMesh = (spec) => {
        const mesh = new THREE.Mesh(geometryFor(spec.type), materialFor(spec.color));
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.userData.workbenchId = safeString(spec.id);
        const p = ensureVector3(spec.position, { x: 0, y: 0.5, z: 0 });
        const r = ensureVector3(spec.rotation, { x: 0, y: 0, z: 0 });
        const s = ensureVector3(spec.scale, { x: 1, y: 1, z: 1 });
        mesh.position.set(p.x, p.y, p.z);
        mesh.rotation.set(r.x, r.y, r.z);
        mesh.scale.set(Math.max(0.1, s.x), Math.max(0.1, s.y), Math.max(0.1, s.z));
        return mesh;
    };
    const updateSpecFromMesh = (spec, mesh) => {
        spec.position = { x: Number(mesh.position.x.toFixed(3)), y: Number(mesh.position.y.toFixed(3)), z: Number(mesh.position.z.toFixed(3)) };
        spec.rotation = { x: Number(mesh.rotation.x.toFixed(3)), y: Number(mesh.rotation.y.toFixed(3)), z: Number(mesh.rotation.z.toFixed(3)) };
        spec.scale = { x: Number(mesh.scale.x.toFixed(3)), y: Number(mesh.scale.y.toFixed(3)), z: Number(mesh.scale.z.toFixed(3)) };
        if (mesh.material?.color) {
            spec.color = `#${mesh.material.color.getHexString()}`;
        }
    };
    const specById = (id) => wb.objects.find((row) => safeString(row?.id) === safeString(id)) || null;
    const selectedSpec = () => specById(wb.selectedId);
    const selectedMesh = () => meshes.get(safeString(wb.selectedId)) || null;
    const setSelection = (idRaw) => {
        wb.selectedId = safeString(idRaw);
        const mesh = selectedMesh();
        if (mesh) {
            transform.attach(mesh);
        } else {
            transform.detach();
        }
    };
    const rebuildScene = () => {
        meshes.forEach((mesh) => {
            scene.remove(mesh);
            mesh.geometry?.dispose?.();
            if (Array.isArray(mesh.material)) {
                mesh.material.forEach((material) => material?.dispose?.());
            } else {
                mesh.material?.dispose?.();
            }
        });
        meshes.clear();
        wb.objects.forEach((spec) => {
            const mesh = toMesh(spec);
            meshes.set(safeString(spec.id), mesh);
            scene.add(mesh);
        });
        applyMaterialVisuals();
        if (!meshes.has(wb.selectedId) && wb.objects.length) {
            wb.selectedId = safeString(wb.objects[0].id);
        }
        setSelection(wb.selectedId);
    };
    const totalVolume = () => wb.objects.reduce((acc, spec) => {
        const scale = ensureVector3(spec.scale, { x: 1, y: 1, z: 1 });
        let base = 1;
        if (safeString(spec.type) === 'sphere') base = (4 / 3) * Math.PI * 0.55 * 0.55 * 0.55;
        if (safeString(spec.type) === 'cylinder') base = Math.PI * 0.42 * 0.42 * 1.15;
        return acc + (base * Math.max(0.1, scale.x) * Math.max(0.1, scale.y) * Math.max(0.1, scale.z));
    }, 0);
    const renderInspector = () => {
        const spec = selectedSpec();
        if (!spec) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a mesh to edit transforms.</p><div class="module-wb-metrics"><div><span>Bodies</span><strong>${wb.objects.length}</strong></div><div><span>Volume</span><strong>${totalVolume().toFixed(2)} ${escapeHtml(wb.units)}^3</strong></div><div><span>Mode</span><strong>${escapeHtml(wb.transformMode)}</strong></div></div>`;
            return;
        }
        const p = ensureVector3(spec.position, { x: 0, y: 0.5, z: 0 });
        const s = ensureVector3(spec.scale, { x: 1, y: 1, z: 1 });
        inspector.innerHTML = `
            <h4>${escapeHtml(safeString(spec.name) || 'Mesh')}</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field">Name<input type="text" data-lab3d-prop="name" value="${escapeHtml(safeString(spec.name))}" /></label>
                <label class="module-wb-field">Color<input type="color" data-lab3d-prop="color" value="${escapeHtml(cleanColor(spec.color))}" /></label>
                <label class="module-wb-field">X<input type="number" step="0.1" data-lab3d-prop="x" value="${p.x}" /></label>
                <label class="module-wb-field">Y<input type="number" step="0.1" data-lab3d-prop="y" value="${p.y}" /></label>
                <label class="module-wb-field">Z<input type="number" step="0.1" data-lab3d-prop="z" value="${p.z}" /></label>
                <label class="module-wb-field">Scale<input type="number" step="0.1" min="0.1" data-lab3d-prop="scale" value="${s.x}" /></label>
            </div>
            <p class="module-wb-mini-note">Type: ${escapeHtml(safeString(spec.type) || 'box')} | ID: ${escapeHtml(safeString(spec.id))}</p>
        `;
    };
    const renderStatus = () => {
        const selected = selectedSpec() ? safeString(selectedSpec().name) : 'no selection';
        status.textContent = `${wb.objects.length} meshes | ${wb.transformMode}/${wb.transformSpace}${wb.transformSnap ? ' snap' : ''} | ${selected}`;
        const snapBtn = shell.querySelector('[data-lab3d-action="snap"]');
        const spaceBtn = shell.querySelector('[data-lab3d-action="space"]');
        const wireBtn = shell.querySelector('[data-lab3d-action="wireframe"]');
        const gridBtn = shell.querySelector('[data-lab3d-action="grid"]');
        if (snapBtn) snapBtn.textContent = wb.transformSnap ? 'Snap On' : 'Snap Off';
        if (spaceBtn) spaceBtn.textContent = wb.transformSpace === 'local' ? 'Local' : 'World';
        if (wireBtn) wireBtn.textContent = wb.wireframe ? 'Wireframe' : 'Shaded';
        if (gridBtn) gridBtn.textContent = wb.showGrid ? 'Grid On' : 'Grid Off';
    };
    const renderProjectSelect = () => {
        const select = shell.querySelector('select[data-wb-project-select="lab_3d"]');
        if (!(select instanceof HTMLSelectElement)) return;
        const rows = moduleWorkbenchProjectList('lab_3d');
        const current = safeString(wb.selectedProjectId);
        select.innerHTML = `<option value="">Select project</option>${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}`;
        select.value = rows.some((row) => safeString(row.id) === current) ? current : '';
    };
    const syncAllSpecs = () => {
        wb.objects.forEach((spec) => {
            const mesh = meshes.get(safeString(spec.id));
            if (mesh) updateSpecFromMesh(spec, mesh);
        });
    };
    const applyMaterialVisuals = () => {
        meshes.forEach((mesh) => {
            if (Array.isArray(mesh.material)) {
                mesh.material.forEach((material) => {
                    if (material && 'wireframe' in material) material.wireframe = wb.wireframe;
                });
            } else if (mesh.material && 'wireframe' in mesh.material) {
                mesh.material.wireframe = wb.wireframe;
            }
        });
    };
    const parseImportedObjects = (payloadRaw) => {
        const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {};
        const rows = Array.isArray(payload.objects) ? payload.objects : [];
        return rows
            .map((row, index) => {
                const type = safeString(row?.type);
                if (!['box', 'sphere', 'cylinder'].includes(type)) return null;
                return {
                    id: `mesh-${wb.nextId + index}`,
                    name: safeString(row?.name) || `${type[0]?.toUpperCase() || 'M'}${type.slice(1)} ${wb.nextId + index}`,
                    type,
                    color: cleanColor(row?.color),
                    position: ensureVector3(row?.position, { x: 0, y: 0.5, z: 0 }),
                    rotation: ensureVector3(row?.rotation, { x: 0, y: 0, z: 0 }),
                    scale: ensureVector3(row?.scale, { x: 1, y: 1, z: 1 }),
                };
            })
            .filter(Boolean);
    };
    const addMesh = (typeRaw) => {
        const type = safeString(typeRaw) || 'box';
        const spec = {
            id: `mesh-${wb.nextId++}`,
            name: `${type[0]?.toUpperCase() || 'M'}${type.slice(1)} ${wb.nextId - 1}`,
            type,
            color: cleanColor(type === 'sphere' ? '#7fe2ca' : (type === 'cylinder' ? '#ffcf84' : '#7fbfff')),
            position: { x: 0, y: 0.7, z: 0 },
            rotation: { x: 0, y: 0, z: 0 },
            scale: { x: 1, y: 1, z: 1 },
        };
        wb.objects.push(spec);
        rebuildScene();
        setSelection(spec.id);
        renderInspector();
        renderStatus();
    };
    const resize = () => {
        const width = Math.max(320, stage.clientWidth || 320);
        const height = Math.max(220, stage.clientHeight || 220);
        renderer.setSize(width, height);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
    };

    rebuildScene();
    resize();
    renderInspector();
    renderStatus();
    renderProjectSelect();

    const onPointerDown = (event) => {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(Array.from(meshes.values()), false);
        if (!hits.length) {
            setSelection('');
            renderInspector();
            renderStatus();
            return;
        }
        const id = safeString(hits[0]?.object?.userData?.workbenchId);
        setSelection(id);
        renderInspector();
        renderStatus();
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    transform.addEventListener('objectChange', () => {
        const spec = selectedSpec();
        const mesh = selectedMesh();
        if (!spec || !mesh) return;
        updateSpecFromMesh(spec, mesh);
        renderInspector();
        renderStatus();
    });

    const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    if (resizeObserver) resizeObserver.observe(stage);
    const onWindowResize = () => resize();
    window.addEventListener('resize', onWindowResize);

    let rafId = 0;
    const frame = () => {
        rafId = window.requestAnimationFrame(frame);
        controls.update();
        renderer.render(scene, camera);
    };
    frame();

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const projectActionEl = event.target instanceof Element
            ? event.target.closest('[data-wb-project-action][data-wb-project-mode="lab_3d"]')
            : null;
        if (projectActionEl) {
            const action = safeString(projectActionEl.dataset.wbProjectAction).toLowerCase();
            const select = shell.querySelector('select[data-wb-project-select="lab_3d"]');
            const input = shell.querySelector('input[data-wb-project-name="lab_3d"]');
            const selectedId = safeString(select instanceof HTMLSelectElement ? select.value : wb.selectedProjectId);
            if (action === 'save') {
                syncAllSpecs();
                wb.selectedProjectId = moduleWorkbenchProjectSave('lab_3d', {
                    units: wb.units,
                    objects: wb.objects,
                    transformMode: wb.transformMode,
                    transformSpace: wb.transformSpace,
                    transformSnap: wb.transformSnap,
                    showGrid: wb.showGrid,
                    wireframe: wb.wireframe,
                }, safeString(input instanceof HTMLInputElement ? input.value : ''));
                if (input instanceof HTMLInputElement) input.value = '';
                renderProjectSelect();
                notifyUser('Model project saved.', { tone: 'success', durationMs: 1600, debugKind: 'lab3d' });
                return;
            }
            if (action === 'load') {
                if (!selectedId) return;
                const project = moduleWorkbenchProjectGet('lab_3d', selectedId);
                if (!project?.payload) return;
                const payload = project.payload;
                const nextObjects = parseImportedObjects(payload);
                if (!nextObjects.length) return;
                wb.objects = nextObjects;
                wb.units = safeString(payload.units) || wb.units;
                wb.transformMode = safeString(payload.transformMode) || wb.transformMode;
                wb.transformSpace = safeString(payload.transformSpace) === 'local' ? 'local' : 'world';
                wb.transformSnap = Boolean(payload.transformSnap);
                wb.showGrid = payload.showGrid !== false;
                wb.wireframe = Boolean(payload.wireframe);
                wb.selectedProjectId = selectedId;
                transform.setMode(wb.transformMode);
                transform.setSpace(wb.transformSpace);
                if (wb.transformSnap) {
                    transform.setTranslationSnap(0.25);
                    transform.setRotationSnap(Math.PI / 12);
                    transform.setScaleSnap(0.1);
                } else {
                    transform.setTranslationSnap(null);
                    transform.setRotationSnap(null);
                    transform.setScaleSnap(null);
                }
                gridHelper.visible = wb.showGrid;
                rebuildScene();
                renderInspector();
                renderStatus();
                renderProjectSelect();
                notifyUser(`Loaded model project: ${safeString(project.name)}.`, { tone: 'success', durationMs: 1700, debugKind: 'lab3d' });
                return;
            }
            if (action === 'delete') {
                if (!selectedId) return;
                if (moduleWorkbenchProjectDelete('lab_3d', selectedId)) {
                    wb.selectedProjectId = '';
                    renderProjectSelect();
                    notifyUser('Deleted model project.', { tone: 'warn', durationMs: 1600, debugKind: 'lab3d' });
                }
                return;
            }
        }
        const target = event.target instanceof Element ? event.target.closest('[data-lab3d-add], [data-lab3d-transform], [data-lab3d-action]') : null;
        if (!target) return;
        const addType = safeString(target.dataset.lab3dAdd);
        const transformMode = safeString(target.dataset.lab3dTransform);
        const action = safeString(target.dataset.lab3dAction).toLowerCase();
        if (addType) {
            addMesh(addType);
            return;
        }
        if (transformMode) {
            wb.transformMode = transformMode;
            transform.setMode(transformMode);
            shell.querySelectorAll('[data-lab3d-transform]').forEach((button) => button.classList.toggle('active', safeString(button.dataset.lab3dTransform) === transformMode));
            renderStatus();
            return;
        }
        if (action === 'snap') {
            wb.transformSnap = !wb.transformSnap;
            if (wb.transformSnap) {
                transform.setTranslationSnap(0.25);
                transform.setRotationSnap(Math.PI / 12);
                transform.setScaleSnap(0.1);
            } else {
                transform.setTranslationSnap(null);
                transform.setRotationSnap(null);
                transform.setScaleSnap(null);
            }
            renderStatus();
            return;
        }
        if (action === 'space') {
            wb.transformSpace = wb.transformSpace === 'local' ? 'world' : 'local';
            transform.setSpace(wb.transformSpace);
            renderStatus();
            return;
        }
        if (action === 'wireframe') {
            wb.wireframe = !wb.wireframe;
            applyMaterialVisuals();
            renderStatus();
            return;
        }
        if (action === 'grid') {
            wb.showGrid = !wb.showGrid;
            gridHelper.visible = wb.showGrid;
            renderStatus();
            return;
        }
        if (action === 'import_json') {
            if (importInput instanceof HTMLInputElement) {
                importInput.click();
            }
            return;
        }
        if (action === 'delete' && wb.selectedId) {
            wb.objects = wb.objects.filter((spec) => safeString(spec.id) !== safeString(wb.selectedId));
            wb.selectedId = wb.objects[0] ? safeString(wb.objects[0].id) : '';
            rebuildScene();
            renderInspector();
            renderStatus();
        }
        if (action === 'export') {
            syncAllSpecs();
            moduleWorkbenchCopyJson({ units: wb.units, objects: wb.objects }, '3D Lab Scene JSON');
        }
        if (action === 'export_gltf') {
            syncAllSpecs();
            const exporter = new GLTFExporter();
            const exportScene = new THREE.Scene();
            wb.objects.forEach((spec) => {
                const mesh = meshes.get(safeString(spec.id));
                if (mesh) exportScene.add(mesh.clone(true));
            });
            exporter.parse(
                exportScene,
                (result) => {
                    if (typeof result === 'string') {
                        moduleWorkbenchCopyText(result, '3D Lab GLTF');
                    } else {
                        moduleWorkbenchCopyJson(result, '3D Lab GLTF');
                    }
                },
                (error) => {
                    notifyUser(`GLTF export failed: ${safeString(error?.message) || 'unknown error'}`, { tone: 'warn', durationMs: 2200, debugKind: 'lab3d' });
                },
                { binary: false },
            );
        }
        if (action === 'export_stl' && STLExporter) {
            syncAllSpecs();
            const exporter = new STLExporter();
            const exportScene = new THREE.Scene();
            wb.objects.forEach((spec) => {
                const mesh = meshes.get(safeString(spec.id));
                if (mesh) exportScene.add(mesh.clone(true));
            });
            try {
                const stl = exporter.parse(exportScene, { binary: false });
                const stlText = typeof stl === 'string' ? stl : '';
                if (stlText) {
                    moduleWorkbenchDownloadText('lab3d-scene.stl', stlText, 'model/stl');
                    notifyUser('STL downloaded.', { tone: 'success', durationMs: 1600, debugKind: 'lab3d' });
                } else {
                    notifyUser('STL export produced no text payload.', { tone: 'warn', durationMs: 1900, debugKind: 'lab3d' });
                }
            } catch (error) {
                notifyUser(`STL export failed: ${safeString(error?.message) || 'unknown error'}`, { tone: 'warn', durationMs: 2200, debugKind: 'lab3d' });
            }
        }
    });

    if (importInput instanceof HTMLInputElement) {
        importInput.addEventListener('change', async () => {
            const file = importInput.files?.[0];
            if (!file) return;
            try {
                const raw = await file.text();
                const parsed = JSON.parse(raw);
                const nextObjects = parseImportedObjects(parsed);
                if (!nextObjects.length) {
                    notifyUser('No valid meshes found in imported JSON.', { tone: 'warn', durationMs: 2200, debugKind: 'lab3d' });
                    importInput.value = '';
                    return;
                }
                wb.objects = nextObjects;
                wb.nextId = nextObjects.length + 1;
                wb.selectedId = safeString(nextObjects[0]?.id);
                rebuildScene();
                renderInspector();
                renderStatus();
                notifyUser(`Imported ${nextObjects.length} mesh definitions.`, { tone: 'success', durationMs: 1700, debugKind: 'lab3d' });
            } catch (error) {
                notifyUser(`Import failed: ${safeString(error?.message) || 'invalid JSON'}`, { tone: 'warn', durationMs: 2200, debugKind: 'lab3d' });
            } finally {
                importInput.value = '';
            }
        });
    }
    const projectSelect = shell.querySelector('select[data-wb-project-select="lab_3d"]');
    if (projectSelect instanceof HTMLSelectElement) {
        projectSelect.addEventListener('change', () => {
            wb.selectedProjectId = safeString(projectSelect.value);
        });
    }

    inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        const spec = selectedSpec();
        const mesh = selectedMesh();
        if (!spec || !mesh) return;
        const prop = safeString(target.dataset.lab3dProp);
        if (!prop) return;
        if (prop === 'name') spec.name = safeString(target.value).slice(0, 80);
        if (prop === 'color') spec.color = cleanColor(target.value, spec.color);
        if (prop === 'x' || prop === 'y' || prop === 'z') {
            const next = Number(target.value);
            if (Number.isFinite(next)) {
                spec.position = ensureVector3(spec.position, { x: 0, y: 0.5, z: 0 });
                spec.position[prop] = next;
            }
        }
        if (prop === 'scale') {
            const next = moduleWorkbenchClamp(Number(target.value) || 1, 0.1, 12);
            spec.scale = { x: next, y: next, z: next };
        }
        mesh.position.set(spec.position?.x || 0, spec.position?.y || 0, spec.position?.z || 0);
        mesh.scale.set(spec.scale?.x || 1, spec.scale?.y || 1, spec.scale?.z || 1);
        if (mesh.material?.color) mesh.material.color.set(spec.color || '#7fbfff');
        renderInspector();
        renderStatus();
    });

    wb.ossEngine = {
        dispose: () => {
            window.cancelAnimationFrame(rafId);
            renderer.domElement.removeEventListener('pointerdown', onPointerDown);
            window.removeEventListener('resize', onWindowResize);
            resizeObserver?.disconnect?.();
            transform.detach();
            transform.dispose?.();
            controls.dispose?.();
            meshes.forEach((mesh) => {
                mesh.geometry?.dispose?.();
                if (Array.isArray(mesh.material)) {
                    mesh.material.forEach((material) => material?.dispose?.());
                } else {
                    mesh.material?.dispose?.();
                }
            });
            renderer.dispose?.();
            if (stage.contains(renderer.domElement)) stage.removeChild(renderer.domElement);
        },
    };
    return true;
}

function moduleRenderWorkbenchLab3d(container, wb) {
    if (moduleRenderWorkbenchLab3dOss(container, wb)) return;
    if (!container || !wb) return;
    if (!Array.isArray(wb.shapes)) wb.shapes = [];
    wb.tool = safeString(wb.tool) || 'rect';
    wb.grid = moduleWorkbenchClamp(Number(wb.grid) || 24, 8, 64);
    wb.snap = wb.snap !== false;
    wb.units = safeString(wb.units) || 'mm';
    wb.canvasWidth = moduleWorkbenchClamp(Number(wb.canvasWidth) || 860, 500, 1400);
    wb.canvasHeight = moduleWorkbenchClamp(Number(wb.canvasHeight) || 420, 260, 760);

    moduleWorkbenchHeader(container, '3D Lab Workbench', 'Dispatch fabrication-ready modeling tasks to Thomas and review generated CAD outputs.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-lab3d';
    shell.innerHTML = `
        <div class="module-wb-toolbar">
            <div class="module-wb-tool-group" data-lab-tools></div>
            <div class="module-wb-toolbar-actions">
                <label class="module-wb-inline-field">Grid <input type="number" data-lab-grid min="8" max="64" step="2" value="${escapeHtml(String(wb.grid))}" /></label>
                <button type="button" class="module-item-btn" data-lab-action="snap">${wb.snap ? 'Snap On' : 'Snap Off'}</button>
                <button type="button" class="module-item-btn" data-lab-action="clear">Clear</button>
                <button type="button" class="module-item-btn" data-lab-action="export">Export</button>
            </div>
        </div>
        <div class="module-wb-main-grid module-wb-main-grid-lab3d">
            <section class="module-wb-stage-card">
                <div class="module-wb-stage-head"><span class="module-wb-stage-title">CAD Surface</span><span class="module-wb-stage-meta" data-lab-status></span></div>
                <canvas class="module-wb-canvas-lab3d" data-lab-canvas width="${escapeHtml(String(wb.canvasWidth))}" height="${escapeHtml(String(wb.canvasHeight))}"></canvas>
                <p class="module-wb-hint">Use Select to move. Other tools draw shapes.</p>
            </section>
            <aside class="module-wb-inspector-card" data-lab-inspector></aside>
        </div>
    `;
    container.appendChild(shell);

    const tools = [
        { id: 'select', icon: 'ph-cursor-click', label: 'Select' },
        { id: 'rect', icon: 'ph-rectangle', label: 'Rect' },
        { id: 'circle', icon: 'ph-circle', label: 'Circle' },
        { id: 'line', icon: 'ph-line-segment', label: 'Line' },
    ];
    const toolsEl = shell.querySelector('[data-lab-tools]');
    const canvas = shell.querySelector('[data-lab-canvas]');
    const inspector = shell.querySelector('[data-lab-inspector]');
    const status = shell.querySelector('[data-lab-status]');
    const gridInput = shell.querySelector('[data-lab-grid]');
    const ctx = canvas instanceof HTMLCanvasElement ? canvas.getContext('2d') : null;

    const selectedShape = () => moduleLab3dShapeById(wb, wb.selectedId);
    const point = (event) => {
        const raw = moduleWorkbenchPointFromEvent(canvas, event);
        const grid = Math.max(4, Number(wb.grid) || 24);
        const x = wb.snap ? Math.round(raw.x / grid) * grid : raw.x;
        const y = wb.snap ? Math.round(raw.y / grid) * grid : raw.y;
        return { x: moduleWorkbenchClamp(x, 0, canvas.width), y: moduleWorkbenchClamp(y, 0, canvas.height) };
    };
    const drawShape = (shape, selected = false, ghost = false) => {
        if (!ctx || !shape) return;
        const type = safeString(shape.type);
        const color = /^#[0-9a-f]{6}$/i.test(safeString(shape.color)) ? safeString(shape.color) : moduleLab3dDefaultColor(type);
        ctx.save();
        ctx.strokeStyle = selected ? '#f7fbff' : color;
        ctx.fillStyle = color;
        ctx.globalAlpha = ghost ? 0.34 : 0.78;
        ctx.lineWidth = selected ? 2.2 : 1.3;
        if (type === 'line') {
            ctx.beginPath();
            ctx.moveTo(Number(shape.x) || 0, Number(shape.y) || 0);
            ctx.lineTo(Number(shape.x2) || 0, Number(shape.y2) || 0);
            ctx.stroke();
        } else if (type === 'circle') {
            const cx = (Number(shape.x) || 0) + ((Number(shape.w) || 0) / 2);
            const cy = (Number(shape.y) || 0) + ((Number(shape.h) || 0) / 2);
            const r = Math.max(3, Math.max(Number(shape.w) || 0, Number(shape.h) || 0) / 2);
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        } else {
            ctx.beginPath();
            ctx.rect(Number(shape.x) || 0, Number(shape.y) || 0, Math.max(1, Number(shape.w) || 0), Math.max(1, Number(shape.h) || 0));
            ctx.fill();
            ctx.stroke();
        }
        ctx.restore();
    };
    const renderInspector = () => {
        if (!inspector) return;
        const shape = selectedShape();
        if (!shape) {
            const totals = wb.shapes.reduce((acc, item) => {
                const m = moduleLab3dMetrics(item);
                acc.area += m.area;
                acc.volume += m.volume;
                return acc;
            }, { area: 0, volume: 0 });
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a shape to edit details.</p><div class="module-wb-metrics"><div><span>Bodies</span><strong>${wb.shapes.length}</strong></div><div><span>Area</span><strong>${totals.area.toFixed(1)} ${escapeHtml(wb.units)}^2</strong></div><div><span>Volume</span><strong>${totals.volume.toFixed(1)} ${escapeHtml(wb.units)}^3</strong></div></div>`;
            return;
        }
        const m = moduleLab3dMetrics(shape);
        inspector.innerHTML = `<h4>${escapeHtml(safeString(shape.label) || 'Shape')}</h4><div class="module-wb-field-grid"><label class="module-wb-field">Label<input type="text" data-shape-prop="label" value="${escapeHtml(safeString(shape.label))}" /></label><label class="module-wb-field">Color<input type="color" data-shape-prop="color" value="${escapeHtml(/^#[0-9a-f]{6}$/i.test(safeString(shape.color)) ? safeString(shape.color) : moduleLab3dDefaultColor(shape.type))}" /></label><label class="module-wb-field">X<input type="number" data-shape-prop="x" value="${Math.round(Number(shape.x) || 0)}" /></label><label class="module-wb-field">Y<input type="number" data-shape-prop="y" value="${Math.round(Number(shape.y) || 0)}" /></label>${safeString(shape.type) === 'line' ? `<label class="module-wb-field">End X<input type="number" data-shape-prop="x2" value="${Math.round(Number(shape.x2) || 0)}" /></label><label class="module-wb-field">End Y<input type="number" data-shape-prop="y2" value="${Math.round(Number(shape.y2) || 0)}" /></label>` : `<label class="module-wb-field">Width<input type="number" data-shape-prop="w" value="${Math.round(Number(shape.w) || 0)}" /></label><label class="module-wb-field">Height<input type="number" data-shape-prop="h" value="${Math.round(Number(shape.h) || 0)}" /></label>`}<label class="module-wb-field">Depth<input type="number" min="0" max="200" data-shape-prop="depth" value="${Math.round(Number(shape.depth) || 0)}" /></label></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-shape-action="duplicate">Duplicate</button><button type="button" class="module-item-btn" data-shape-action="delete">Delete</button></div><div class="module-wb-metrics"><div><span>Area</span><strong>${m.area.toFixed(1)}</strong></div><div><span>Perimeter</span><strong>${m.perimeter.toFixed(1)}</strong></div><div><span>Volume</span><strong>${m.volume.toFixed(1)}</strong></div></div>`;
    };
    const render = () => {
        if (!ctx || !(canvas instanceof HTMLCanvasElement)) return;
        toolsEl.innerHTML = tools.map((tool) => `<button type="button" class="module-wb-tool-btn${safeString(wb.tool) === tool.id ? ' active' : ''}" data-lab-tool="${tool.id}"><i class="ph ${tool.icon}"></i><span>${tool.label}</span></button>`).join('');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = 'rgba(164, 198, 244, 0.12)';
        for (let x = 0; x <= canvas.width; x += Number(wb.grid) || 24) { ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, canvas.height); ctx.stroke(); }
        for (let y = 0; y <= canvas.height; y += Number(wb.grid) || 24) { ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(canvas.width, y + 0.5); ctx.stroke(); }
        wb.shapes.forEach((shape) => drawShape(shape, safeString(shape.id) === safeString(wb.selectedId)));
        if (wb.draft) drawShape(wb.draft, false, true);
        renderInspector();
        status.textContent = `${wb.shapes.length} shapes | ${wb.snap ? `snap ${wb.grid}px` : 'free'}${selectedShape() ? ` | selected ${safeString(selectedShape().label)}` : ''}`;
    };

    shell.addEventListener('click', (event) => {
        const target = event.target instanceof Element ? event.target.closest('[data-lab-tool], [data-lab-action], [data-shape-action]') : null;
        if (!target) return;
        const tool = safeString(target.dataset.labTool);
        const action = safeString(target.dataset.labAction || target.dataset.shapeAction).toLowerCase();
        if (tool) wb.tool = tool;
        if (action === 'snap') wb.snap = !wb.snap;
        if (action === 'clear') { wb.shapes = []; wb.selectedId = ''; wb.draft = null; wb.dragStart = null; }
        if (action === 'export') moduleWorkbenchCopyJson({ units: wb.units, grid: wb.grid, shapes: wb.shapes }, '3D Lab CAD JSON');
        if (action === 'duplicate' && selectedShape()) { const copy = { ...selectedShape(), id: `shape-${wb.nextId++}`, label: `${safeString(selectedShape().label)} Copy`, x: (Number(selectedShape().x) || 0) + 18, y: (Number(selectedShape().y) || 0) + 18 }; if (safeString(copy.type) === 'line') { copy.x2 = (Number(copy.x2) || 0) + 18; copy.y2 = (Number(copy.y2) || 0) + 18; } wb.shapes.push(copy); wb.selectedId = copy.id; }
        if (action === 'delete' && selectedShape()) { wb.shapes = wb.shapes.filter((shape) => safeString(shape.id) !== safeString(wb.selectedId)); wb.selectedId = ''; }
        render();
    });
    if (gridInput) gridInput.addEventListener('input', () => { wb.grid = moduleWorkbenchClamp(Number(gridInput.value) || 24, 8, 64); render(); });
    if (inspector) inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        const shape = selectedShape();
        if (!shape) return;
        const prop = safeString(target.dataset.shapeProp);
        if (!prop) return;
        if (prop === 'label') shape.label = safeString(target.value).slice(0, 60);
        else if (prop === 'color' && /^#[0-9a-f]{6}$/i.test(safeString(target.value))) shape.color = safeString(target.value);
        else shape[prop] = Number.isFinite(Number(target.value)) ? Number(target.value) : shape[prop];
        render();
    });
    if (canvas instanceof HTMLCanvasElement) {
        canvas.addEventListener('pointerdown', (event) => {
            const p = point(event);
            if (safeString(wb.tool) === 'select') {
                const hit = [...wb.shapes].reverse().find((shape) => moduleLab3dHitShape(shape, p)) || null;
                wb.selectedId = safeString(hit?.id);
                wb.dragStart = hit ? { x: p.x, y: p.y, origin: { ...hit } } : null;
                render();
                return;
            }
            wb.drawing = true;
            wb.draft = {
                id: 'draft',
                type: wb.tool,
                label: 'Draft',
                color: moduleLab3dDefaultColor(wb.tool),
                depth: 12,
                startX: p.x,
                startY: p.y,
                x: p.x,
                y: p.y,
                w: 0,
                h: 0,
                x2: p.x,
                y2: p.y,
            };
            wb.selectedId = '';
            render();
        });
        canvas.addEventListener('pointermove', (event) => {
            const p = point(event);
            if (wb.drawing && wb.draft) {
                if (safeString(wb.draft.type) === 'line') {
                    wb.draft.x2 = p.x;
                    wb.draft.y2 = p.y;
                } else {
                    const sx = Number(wb.draft.startX) || Number(wb.draft.x) || 0;
                    const sy = Number(wb.draft.startY) || Number(wb.draft.y) || 0;
                    wb.draft.x = Math.min(sx, p.x);
                    wb.draft.y = Math.min(sy, p.y);
                    wb.draft.w = Math.abs(p.x - sx);
                    wb.draft.h = Math.abs(p.y - sy);
                    wb.draft.x2 = p.x;
                    wb.draft.y2 = p.y;
                }
                render();
                return;
            }
            if (wb.dragStart && safeString(wb.tool) === 'select') { const shape = selectedShape(); if (!shape) return; const dx = p.x - wb.dragStart.x; const dy = p.y - wb.dragStart.y; shape.x = (Number(wb.dragStart.origin.x) || 0) + dx; shape.y = (Number(wb.dragStart.origin.y) || 0) + dy; if (safeString(shape.type) === 'line') { shape.x2 = (Number(wb.dragStart.origin.x2) || 0) + dx; shape.y2 = (Number(wb.dragStart.origin.y2) || 0) + dy; } render(); }
        });
        const finish = () => {
            if (wb.drawing && wb.draft) {
                const draft = wb.draft;
                const lineLength = Math.hypot((Number(draft.x2) || 0) - (Number(draft.x) || 0), (Number(draft.y2) || 0) - (Number(draft.y) || 0));
                const keep = safeString(draft.type) === 'line'
                    ? lineLength > 6
                    : (Math.max(Number(draft.w) || 0, Number(draft.h) || 0) > 6);
                if (keep) {
                    const shape = {
                        ...draft,
                        id: `shape-${wb.nextId++}`,
                        label: `${safeString(draft.type)} ${wb.nextId - 1}`,
                    };
                    delete shape.startX;
                    delete shape.startY;
                    wb.shapes.push(shape);
                    wb.selectedId = shape.id;
                }
            }
            wb.drawing = false;
            wb.draft = null;
            wb.dragStart = null;
            render();
        };
        canvas.addEventListener('pointerup', finish);
        canvas.addEventListener('pointerleave', finish);
    }
    render();
}

function moduleWorkbenchPushLog(bucket, message, tone = 'ok', cap = 80, prefix = 'log') {
    if (!Array.isArray(bucket)) return;
    bucket.unshift({
        id: moduleWorkbenchMakeId(prefix),
        time: moduleWorkbenchTimeStamp(),
        tone,
        message: safeString(message),
    });
    if (bucket.length > cap) bucket.length = cap;
}

function moduleWorkbenchEnsureLiteGraphNodeType(LiteGraph) {
    if (!LiteGraph?.registerNodeType) return;
    if (LiteGraph.registered_node_types?.['thomas/flow_block']) return;
    class ThomasFlowBlock extends LiteGraph.LGraphNode {
        constructor() {
            super();
            this.title = 'Flow Block';
            this.addInput('in', 'flow');
            this.addOutput('out', 'flow');
            this.properties = {
                blockType: 'custom',
                kind: 'action',
                notes: '',
                approval: false,
            };
            this.size = [210, 86];
        }
    }
    LiteGraph.registerNodeType('thomas/flow_block', ThomasFlowBlock);
}

function moduleWorkbenchLiteGraphLinks(graphDataRaw) {
    const graphData = graphDataRaw && typeof graphDataRaw === 'object' ? graphDataRaw : {};
    const linksRaw = graphData.links;
    if (!linksRaw || typeof linksRaw !== 'object') return [];
    return Object.values(linksRaw)
        .map((entry) => (Array.isArray(entry) ? entry : []))
        .filter((entry) => entry.length >= 4)
        .map((entry) => ({
            originId: Number(entry[1]) || 0,
            targetId: Number(entry[3]) || 0,
        }))
        .filter((entry) => entry.originId > 0 && entry.targetId > 0);
}

function moduleWorkbenchFlowToN8n(graphDataRaw) {
    const graphData = graphDataRaw && typeof graphDataRaw === 'object' ? graphDataRaw : {};
    const nodesRaw = Array.isArray(graphData.nodes) ? graphData.nodes : [];
    const nodes = nodesRaw.map((nodeRaw, index) => {
        const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
        const id = String(Number(node.id) || (index + 1));
        const title = safeString(node.title) || `Flow ${index + 1}`;
        const name = `${title} [${id}]`;
        return {
            _id: id,
            id,
            name,
            type: 'n8n-nodes-base.noOp',
            typeVersion: 1,
            position: [
                Number(node.pos?.[0]) || ((index + 1) * 180),
                Number(node.pos?.[1]) || ((index + 1) * 80),
            ],
            parameters: {
                kind: safeString(node.properties?.kind) || 'action',
                blockType: safeString(node.properties?.blockType) || 'custom',
                notes: safeString(node.properties?.notes),
                approval: Boolean(node.properties?.approval),
            },
        };
    });
    const byId = new Map(nodes.map((node) => [node._id, node]));
    const links = moduleWorkbenchLiteGraphLinks(graphData);
    const connectionMap = new Map();
    links.forEach((edge) => {
        const from = byId.get(String(edge.originId));
        const to = byId.get(String(edge.targetId));
        if (!from || !to) return;
        if (!connectionMap.has(from.name)) connectionMap.set(from.name, []);
        connectionMap.get(from.name).push({
            node: to.name,
            type: 'main',
            index: 0,
        });
    });
    const connections = {};
    nodes.forEach((node) => {
        const outputs = connectionMap.get(node.name) || [];
        if (!outputs.length) return;
        connections[node.name] = {
            main: [outputs],
        };
    });
    return {
        name: 'Thomas Flow Export',
        active: false,
        settings: {},
        nodes: nodes.map((node) => ({
            id: node.id,
            name: node.name,
            type: node.type,
            typeVersion: node.typeVersion,
            position: node.position,
            parameters: node.parameters,
        })),
        connections,
    };
}

function moduleWorkbenchFlowToNodeRed(graphDataRaw) {
    const graphData = graphDataRaw && typeof graphDataRaw === 'object' ? graphDataRaw : {};
    const nodesRaw = Array.isArray(graphData.nodes) ? graphData.nodes : [];
    const tabId = `tab_${Date.now().toString(36)}`;
    const nodes = nodesRaw.map((nodeRaw, index) => {
        const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
        const id = `n_${String(Number(node.id) || (index + 1))}`;
        return {
            id,
            type: 'function',
            z: tabId,
            name: safeString(node.title) || `Flow ${index + 1}`,
            func: `// ${safeString(node.properties?.kind) || 'action'}\nreturn msg;`,
            outputs: 1,
            noerr: 0,
            initialize: '',
            finalize: '',
            libs: [],
            x: Number(node.pos?.[0]) || ((index + 1) * 200),
            y: Number(node.pos?.[1]) || ((index + 1) * 80),
            wires: [[]],
        };
    });
    const byId = new Map(nodes.map((node) => [node.id.replace(/^n_/, ''), node]));
    moduleWorkbenchLiteGraphLinks(graphData).forEach((edge) => {
        const from = byId.get(String(edge.originId));
        const to = byId.get(String(edge.targetId));
        if (!from || !to) return;
        from.wires[0].push(to.id);
    });
    return [
        { id: tabId, type: 'tab', label: 'Thomas Flow', disabled: false, info: '' },
        ...nodes,
    ];
}

