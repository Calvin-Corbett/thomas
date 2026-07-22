/* Canvas workspace chrome and authoritative app_builder integration. */
(function () {
    'use strict';

    var contract = window.ThomasCanvasWorkspaceContract;
    var currentApi = null;

    function element(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function mark(node, key, options) {
        if (contract && typeof contract.annotate === 'function') contract.annotate(node, key, options);
        return node;
    }

    function action(label, instanceKey, className) {
        var button = element('button', className || 'ui-studio-btn', label);
        button.type = 'button';
        button.setAttribute('aria-label', label);
        return mark(button, 'action', { instanceKey: instanceKey, label: label });
    }

    function buildChrome(root) {
        mark(root, 'root');
        var toolbar = mark(element('header', 'ui-studio-toolbar'), 'toolbar');
        var brand = mark(element('div', 'ui-studio-brand'), 'brand');
        var eyes = element('span', 'thomas-eyes-mark');
        eyes.setAttribute('aria-hidden', 'true');
        eyes.appendChild(element('span')); eyes.appendChild(element('span'));
        brand.appendChild(eyes); brand.appendChild(element('strong', 'ui-studio-brand-name', 'Canvas'));
        toolbar.appendChild(brand);
        var gMode = mark(element('div', 'ui-studio-toolbar-group ui-studio-mode-group'), 'modeActions');
        var modeLabels = { design: 'Design', draw: 'Draw', model3d: '3D Model' };
        var modeButtons = {};
        Object.keys(modeLabels).forEach(function (key) {
            modeButtons[key] = action(modeLabels[key], 'mode-' + key, 'ui-studio-btn' + (key === 'design' ? ' is-accent' : ''));
            modeButtons[key].setAttribute('aria-pressed', key === 'design' ? 'true' : 'false'); gMode.appendChild(modeButtons[key]);
        });

        var gFile = mark(element('div', 'ui-studio-toolbar-group'), 'fileActions');
        var btnGen = action('Generate Code', 'generate-code', 'ui-studio-btn is-accent');
        var btnExport = action('Export Spec', 'export-spec');
        var btnSave = action('Save', 'save');
        gFile.appendChild(btnGen); gFile.appendChild(btnExport); gFile.appendChild(btnSave);

        var gAdd = mark(element('div', 'ui-studio-toolbar-group'), 'addActions');
        var addLabels = { container: '+ Box', text: '+ Text', button: '+ Button', card: '+ Card', input: '+ Input', image: '+ Image' };
        var addBtns = {};
        Object.keys(addLabels).forEach(function (key) {
            addBtns[key] = action(addLabels[key], 'add-' + key);
            gAdd.appendChild(addBtns[key]);
        });

        var gAi = mark(element('div', 'ui-studio-toolbar-group'), 'aiActions');
        var btnAi = action('AI Template', 'ai-template', 'ui-studio-btn is-mint');
        var btnSketch = action('Import Sketch', 'import-sketch', 'ui-studio-btn is-mint');
        gAi.appendChild(btnAi); gAi.appendChild(btnSketch);

        var gZoom = mark(element('div', 'ui-studio-toolbar-group'), 'zoomActions');
        var btnZoomOut = action('Zoom out', 'zoom-out'); btnZoomOut.textContent = '-';
        var zoomLabel = element('span', 'ui-studio-zoom-label', '100%');
        var btnZoomIn = action('Zoom in', 'zoom-in'); btnZoomIn.textContent = '+';
        var btnZoomReset = action('Reset zoom', 'zoom-reset'); btnZoomReset.textContent = 'Reset';
        gZoom.appendChild(btnZoomOut); gZoom.appendChild(zoomLabel); gZoom.appendChild(btnZoomIn); gZoom.appendChild(btnZoomReset);

        var gGrid = mark(element('div', 'ui-studio-toolbar-group'), 'historyActions');
        var gridToggle = mark(element('label', 'ui-studio-toggle'), 'action', { instanceKey: 'snap-grid', label: 'Snap to grid' });
        var gridCheck = document.createElement('input'); gridCheck.type = 'checkbox'; gridCheck.checked = true;
        gridToggle.appendChild(gridCheck); gridToggle.appendChild(document.createTextNode('Snap to grid'));
        var btnUndo = action('Undo', 'undo');
        var btnRedo = action('Redo', 'redo');
        var btnClear = action('Clear', 'clear');
        gGrid.appendChild(gridToggle); gGrid.appendChild(btnUndo); gGrid.appendChild(btnRedo); gGrid.appendChild(btnClear);
        toolbar.appendChild(gMode); toolbar.appendChild(gFile); toolbar.appendChild(gAdd); toolbar.appendChild(gAi); toolbar.appendChild(gZoom); toolbar.appendChild(gGrid);

        var rail = mark(element('nav', 'ui-studio-rail'), 'toolRail');
        rail.setAttribute('aria-label', 'Canvas tools');
        var toolDefs = [['select', 'V', 'Select (V)'], ['box', 'B', 'Box (B)'], ['shape', 'S', 'Shape (S)'], ['text', 'T', 'Text (T)'], ['pen', 'P', 'Pen (P)']];
        var toolButtons = {};
        toolDefs.forEach(function (definition) {
            var button = element('button', 'ui-studio-tool' + (definition[0] === 'select' ? ' is-active' : ''), definition[1]);
            button.type = 'button'; button.title = definition[2]; button.setAttribute('aria-label', definition[2]); button.setAttribute('data-tool', definition[0]);
            mark(button, 'tool', { instanceKey: definition[0], label: definition[2] });
            rail.appendChild(button); toolButtons[definition[0]] = button;
        });

        var stageWrap = mark(element('main', 'ui-studio-stage-wrap'), 'stage');
        var canvas = document.createElement('canvas'); canvas.className = 'ui-studio-stage tool-select';
        canvas.setAttribute('aria-label', 'Canvas design surface'); canvas.setAttribute('tabindex', '0');
        var readout = mark(element('div', 'ui-studio-readout', 'Ready'), 'stageReadout');
        var sketchInput = document.createElement('input'); sketchInput.type = 'file'; sketchInput.accept = 'image/*'; sketchInput.hidden = true;
        var lab3dHost = mark(element('div', 'ui-studio-lab3d'), 'modelStage'); lab3dHost.hidden = true;
        stageWrap.appendChild(canvas); stageWrap.appendChild(lab3dHost); stageWrap.appendChild(readout); stageWrap.appendChild(sketchInput);

        var side = mark(element('aside', 'ui-studio-side'), 'inspector');
        var sideTabs = element('nav', 'ui-studio-side-tabs'); sideTabs.setAttribute('aria-label', 'Canvas side panels');
        var sideButtons = { layers: action('Layers', 'side-layers'), properties: action('Properties', 'side-properties') };
        Object.keys(sideButtons).forEach(function (key) { sideButtons[key].className = 'ui-studio-side-tab' + (key === 'layers' ? ' is-active' : ''); sideTabs.appendChild(sideButtons[key]); });
        var layersSec = mark(element('section', 'ui-studio-side-section is-grow'), 'layers');
        layersSec.appendChild(element('div', 'ui-studio-side-title', 'Layers'));
        var layers = element('div', 'ui-studio-layers'); layersSec.appendChild(layers);
        var propsSec = mark(element('section', 'ui-studio-side-section'), 'properties');
        propsSec.hidden = true; propsSec.appendChild(element('div', 'ui-studio-side-title', 'Properties'));
        var props = element('div', 'ui-studio-props'); propsSec.appendChild(props);
        side.appendChild(sideTabs); side.appendChild(layersSec); side.appendChild(propsSec);

        var modal = mark(element('div', 'ui-studio-modal'), 'preview'); modal.hidden = true;
        modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-label', 'Generated code preview');
        var card = element('div', 'ui-studio-modal-card');
        var head = element('div', 'ui-studio-modal-head');
        head.appendChild(element('div', 'ui-studio-modal-title', 'Generated code'));
        var modalTabs = mark(element('div', 'ui-studio-modal-tabs'), 'previewTabs'); head.appendChild(modalTabs);
        var body = element('div', 'ui-studio-modal-body');
        var modalCode = mark(element('pre', 'ui-studio-code', ''), 'previewCode'); body.appendChild(modalCode);
        var foot = element('div', 'ui-studio-modal-foot');
        var modalCopy = action('Copy', 'preview-copy');
        var modalDownload = action('Download files', 'preview-download', 'ui-studio-btn is-accent');
        var modalClose = action('Close', 'preview-close');
        modalClose.addEventListener('click', function () { modal.hidden = true; });
        foot.appendChild(modalCopy); foot.appendChild(modalDownload); foot.appendChild(modalClose);
        card.appendChild(head); card.appendChild(body); card.appendChild(foot); modal.appendChild(card);
        modal.addEventListener('click', function (event) { if (event.target === modal) modal.hidden = true; });
        root.appendChild(toolbar); root.appendChild(rail); root.appendChild(stageWrap); root.appendChild(side); root.appendChild(modal);
        function showSide(key) {
            layersSec.hidden = key !== 'layers'; propsSec.hidden = key !== 'properties';
            Object.keys(sideButtons).forEach(function (name) { sideButtons[name].classList.toggle('is-active', name === key); sideButtons[name].setAttribute('aria-pressed', name === key ? 'true' : 'false'); });
        }
        Object.keys(sideButtons).forEach(function (key) { sideButtons[key].onclick = function () { showSide(key); }; });

        return {
            canvas: canvas, stageWrap: stageWrap, lab3dHost: lab3dHost, readout: readout, layers: layers, props: props, conversation: null,
            zoomLabel: zoomLabel, sketchInput: sketchInput, aiBtn: btnAi,
            modal: modal, modalTabs: modalTabs, modalCode: modalCode, modalCopy: modalCopy, modalDownload: modalDownload,
            fields: {},
            syncTools: function (activeTool) {
                var selected = activeTool || 'select';
                Object.keys(toolButtons).forEach(function (key) {
                    var active = key === selected;
                    toolButtons[key].classList.toggle('is-active', active);
                    toolButtons[key].setAttribute('aria-pressed', active ? 'true' : 'false');
                });
            },
            syncMode: function (mode) {
                Object.keys(modeButtons).forEach(function (key) { var active = key === mode; modeButtons[key].classList.toggle('is-accent', active); modeButtons[key].setAttribute('aria-pressed', active ? 'true' : 'false'); });
            },
            bind: function (handlers) {
                btnGen.onclick = handlers.onGenerate; btnExport.onclick = handlers.onExport; btnSave.onclick = handlers.onSave;
                btnAi.onclick = handlers.onAi; btnSketch.onclick = handlers.onSketch;
                btnZoomIn.onclick = handlers.onZoomIn; btnZoomOut.onclick = handlers.onZoomOut; btnZoomReset.onclick = handlers.onZoomReset;
                btnUndo.onclick = handlers.onUndo; btnRedo.onclick = handlers.onRedo; btnClear.onclick = handlers.onClear;
                gridCheck.onchange = function () { handlers.onGrid(gridCheck.checked); };
                addBtns.container.onclick = handlers.onAddContainer; addBtns.text.onclick = handlers.onAddText; addBtns.button.onclick = handlers.onAddButton;
                addBtns.card.onclick = handlers.onAddCard; addBtns.input.onclick = handlers.onAddInput; addBtns.image.onclick = handlers.onAddImage;
                Object.keys(toolButtons).forEach(function (key) { toolButtons[key].onclick = function () { handlers.onTool(key); }; });
                Object.keys(modeButtons).forEach(function (key) { modeButtons[key].onclick = function () { handlers.onMode(key); }; });
            },
            unbind: function () {
                [btnGen, btnExport, btnSave, btnAi, btnSketch, btnZoomIn, btnZoomOut, btnZoomReset, btnUndo, btnRedo, btnClear]
                    .forEach(function (button) { button.onclick = null; });
                gridCheck.onchange = null;
                Object.keys(addBtns).forEach(function (key) { addBtns[key].onclick = null; });
                Object.keys(toolButtons).forEach(function (key) { toolButtons[key].onclick = null; });
                Object.keys(modeButtons).forEach(function (key) { modeButtons[key].onclick = null; });
                Object.keys(sideButtons).forEach(function (key) { sideButtons[key].onclick = null; });
            }
        };
    }

    function destroyController(workbench) {
        if (!workbench || !workbench.uiStudioCanvas) return false;
        var controller = workbench.uiStudioCanvas;
        workbench.uiStudioCanvas = null;
        if (controller && typeof controller.destroy === 'function') controller.destroy();
        return true;
    }

    function resolveWorkbench() {
        try {
            if (typeof window.moduleEnsureRuntime !== 'function') return null;
            var state = window.moduleEnsureRuntime();
            return state && state.workbench ? state.workbench[contract ? contract.MODE_ID : 'app_builder'] : null;
        } catch (_error) { return null; }
    }

    function install(api) {
        currentApi = api || currentApi;
        if (typeof window.moduleWorkbenchTeardown === 'function' && !window.moduleWorkbenchTeardown.__thomasCanvasTeardown) {
            var priorTeardown = window.moduleWorkbenchTeardown;
            var wrappedTeardown = function moduleWorkbenchTeardownWithCanvas(mode) {
                if (String(mode || '') === (contract ? contract.MODE_ID : 'app_builder')) destroyController(resolveWorkbench());
                return priorTeardown.apply(this, arguments);
            };
            wrappedTeardown.__thomasCanvasTeardown = true;
            window.moduleWorkbenchTeardown = wrappedTeardown;
        }
        window.moduleRenderWorkbenchAppBuilder = function moduleRenderWorkbenchAppBuilderCanvas(container, workbench) {
            if (!container || !currentApi || typeof currentApi.mount !== 'function') return null;
            destroyController(workbench);
            container.innerHTML = '';
            var host = document.createElement('section'); host.className = 'ui-studio-host ui-studio-host-solo';
            host.setAttribute('aria-label', 'Canvas workspace'); container.appendChild(host);
            try {
                var controller = currentApi.mount(host, { apiBase: '/api/canvas' });
                if (workbench) workbench.uiStudioCanvas = controller;
            } catch (error) {
                host.textContent = 'Canvas failed to load: ' + String(error && error.message || error || 'Unknown error');
                host.classList.add('ui-studio-empty');
            }
            return host;
        };
    }

    window.ThomasCanvasWorkspaceRuntime = {
        buildChrome: buildChrome,
        destroyController: destroyController,
        install: install
    };
}());
