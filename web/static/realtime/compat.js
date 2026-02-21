export function detectCompat() {
  const hasWS = typeof WebSocket !== "undefined";
  const hasMediaDevices = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  const hasMediaRecorder = typeof MediaRecorder !== "undefined";
  const hasSpeechSynth = typeof window.speechSynthesis !== "undefined";
  const hasSpeechRec = typeof window.webkitSpeechRecognition !== "undefined" || typeof window.SpeechRecognition !== "undefined";

  // MediaRecorder mime support
  let bestMime = null;
  if (hasMediaRecorder) {
    const mimes = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
    ];
    for (const m of mimes) {
      try {
        if (MediaRecorder.isTypeSupported(m)) { bestMime = m; break; }
      } catch {}
    }
  }

  return {
    hasWS, hasMediaDevices, hasMediaRecorder,
    hasSpeechSynth, hasSpeechRec,
    bestMime,
    userAgent: navigator.userAgent,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown"
  };
}

export function prettyCompat(c) {
  const lines = [];
  lines.push(`ws: ${c.hasWS}`);
  lines.push(`getUserMedia: ${c.hasMediaDevices}`);
  lines.push(`MediaRecorder: ${c.hasMediaRecorder} (${c.bestMime || "n/a"})`);
  lines.push(`SpeechSynthesis: ${c.hasSpeechSynth}`);
  lines.push(`SpeechRecognition: ${c.hasSpeechRec}`);
  lines.push(`tz: ${c.tz}`);
  return lines.join("\n");
}
