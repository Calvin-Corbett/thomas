/* Canvas workspace contract for Thomas shared UI Edit Mode. */
(function () {
    'use strict';

    var NAME = 'Canvas';
    var MODE_ID = 'app_builder';
    var COMPONENTS = {
        root: ['canvas.workspace', 'Canvas workspace', 'root protected', 'move=false resize=false preserveHandlers=true preserveA11y=true'],
        toolbar: ['canvas.toolbar', 'Canvas toolbar', 'layout resize contain=parent', 'minWidth=300 minHeight=44'],
        brand: ['canvas.brand', 'Canvas identity', 'move contain=parent', 'minWidth=90 minHeight=28'],
        fileActions: ['canvas.actions.file', 'Canvas file actions', 'move contain=parent', 'minWidth=210 minHeight=32'],
        addActions: ['canvas.actions.add', 'Add elements', 'move resize contain=parent', 'minWidth=240 minHeight=32'],
        aiActions: ['canvas.actions.ai', 'Canvas AI actions', 'move contain=parent', 'minWidth=180 minHeight=32'],
        zoomActions: ['canvas.actions.zoom', 'Canvas zoom controls', 'move contain=parent', 'minWidth=170 minHeight=32'],
        historyActions: ['canvas.actions.history', 'Canvas history controls', 'move contain=parent', 'minWidth=230 minHeight=32'],
        modeActions: ['canvas.actions.modes', 'Creation modes', 'move contain=parent', 'minWidth=220 minHeight=32'],
        toolRail: ['canvas.tool-rail', 'Canvas tool rail', 'layout resize contain=parent', 'minWidth=44 minHeight=180 maxWidth=120'],
        stage: ['canvas.stage', 'Design stage', 'layout resize contain=parent', 'minWidth=280 minHeight=260'],
        stageReadout: ['canvas.stage-readout', 'Canvas status readout', 'move contain=parent', 'minWidth=120 minHeight=24'],
        inspector: ['canvas.inspector', 'Canvas inspector', 'layout resize contain=parent', 'minWidth=220 minHeight=260 maxWidth=560'],
        conversation: ['canvas.conversation', 'Thomas conversation', 'layout resize contain=parent', 'minWidth=260 minHeight=240 maxWidth=620'],
        modelStage: ['canvas.stage.3d', '3D modeling stage', 'layout resize contain=parent', 'minWidth=320 minHeight=280'],
        layers: ['canvas.layers', 'Canvas layers', 'layout resize contain=parent', 'minWidth=180 minHeight=120'],
        properties: ['canvas.properties', 'Canvas properties', 'layout resize contain=parent', 'minWidth=180 minHeight=140'],
        preview: ['canvas.preview', 'Generated code preview', 'layout resize contain=parent', 'minWidth=320 minHeight=260'],
        previewTabs: ['canvas.preview-tabs', 'Generated file tabs', 'move resize contain=parent', 'minWidth=180 minHeight=32'],
        previewCode: ['canvas.preview-code', 'Generated code', 'layout resize contain=parent', 'minWidth=280 minHeight=180'],
        layer: ['canvas.layer', 'Canvas layer', 'move contain=parent', 'minWidth=160 minHeight=28'],
        action: ['canvas.action', 'Canvas action', 'protected controls', 'minWidth=36 minHeight=28'],
        tool: ['canvas.tool', 'Canvas tool', 'protected controls', 'minWidth=36 minHeight=36']
    };

    function safePart(value) {
        return String(value === null || value === undefined ? '' : value)
            .toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'item';
    }

    function descriptor(key) {
        return COMPONENTS[key] || COMPONENTS.action;
    }

    function annotate(node, key, options) {
        if (!node || typeof node.setAttribute !== 'function') return node;
        options = options || {};
        var definition = descriptor(key);
        var instanceKey = options.instanceKey === undefined ? '' : String(options.instanceKey);
        var id = options.id || definition[0];
        if (instanceKey) id += '.' + safePart(instanceKey);
        node.setAttribute('data-ui-id', id);
        node.setAttribute('data-ui-label', options.label || definition[1]);
        node.setAttribute('data-ui-component', options.component || key);
        node.setAttribute('data-ui-policy', options.policy || definition[2]);
        node.setAttribute('data-ui-constraints', options.constraints || definition[3]);
        if (instanceKey) node.setAttribute('data-ui-instance-key', instanceKey);
        return node;
    }

    function responseData(response) {
        if (response && response.data && typeof response.data === 'object') return response.data;
        return response;
    }

    window.ThomasCanvasWorkspaceContract = {
        NAME: NAME,
        MODE_ID: MODE_ID,
        COMPONENTS: COMPONENTS,
        annotate: annotate,
        responseData: responseData,
        safePart: safePart
    };
}());
