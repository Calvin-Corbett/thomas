
function trySetText(id, text){
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

export function inspectorSetRunId(runId){
  if (window?.ThomasInspector?.setRunId) return window.ThomasInspector.setRunId(runId);
  if (window?.thomasInspector?.setRunId) return window.thomasInspector.setRunId(runId);
  trySetText("inspectorRunId", runId);
}

export function inspectorReset(){
  if (window?.ThomasInspector?.reset) return window.ThomasInspector.reset();
  if (window?.thomasInspector?.reset) return window.thomasInspector.reset();
}

export function inspectorConsumeEvent(evt){
  if (window?.ThomasInspector?.consumeEvent) return window.ThomasInspector.consumeEvent(evt);
  if (window?.thomasInspector?.consumeEvent) return window.thomasInspector.consumeEvent(evt);
  if (window?.ThomasStore?.dispatchEvent) return window.ThomasStore.dispatchEvent(evt);
  console.warn("No inspector consumer wired. Event:", evt);
}
