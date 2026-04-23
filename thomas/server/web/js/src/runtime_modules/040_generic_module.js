// Extracted from part-021.js
// Generic module content

                viewportConnected: false,
                viewportLoadState: 'idle',
                viewportBlockedHint: false,
                unrealRcUrl: 'http://127.0.0.1:30010',
                unrealRcEndpoint: '/remote/object/call',
                unrealRcPayload: '{\n  "objectPath": "/Game/Blueprints/BP_GameMode.BP_GameMode_C",\n  "functionName": "RunEditorTick",\n  "parameters": {}\n}',
                unrealRcResponse: '',
                sceneActors: [],
                selectedActorId: '',
                nextActorId: 1,
                assets: moduleGameStudioDefaultAssets(),
                selectedAssetId: 'asset-floor-grid',
                assetFilterType: 'all',
                assetSearch: '',
                bridge: {
                    status: 'idle',
                    lastPingMs: 0,
                    lastSeenAt: 0,
                    lastError: '',
                    routes: [],
                    pullCount: 0,
                    pushCount: 0,
                    actorSyncPath: '/Game/Blueprints/BP_LevelBridge.BP_LevelBridge_C',
                },
                bridgePollTimer: 0,
                selectedEngine: 'unreal',
                engineProjects: {},
                activeProjectByEngine: {},
                studioChat: [],
                chatDraft: '',
                projectDraftName: '',
                projectDraftPath: 'C:/games/MyUnrealProject/MyGame.uproject',
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'research_lab') {
            state.workbench[mode] = {
                mounted: false,
                lastQuery: '',
                queries: [],
                sources: [],
                notes: '',
                claims: [],
                synthesis: '',
                activeSourceId: '',
            };
        } else {
            state.workbench[mode] = { mounted: false };
        }
    }