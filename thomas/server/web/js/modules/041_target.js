// Extracted from part-021b.js
// From target

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