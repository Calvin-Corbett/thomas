/**
 * STT options:
 * - Browser SpeechRecognition (best local option available in some browsers)
 * - Server-side STT adapter via sending audio (not default in this pack)
 *
 * This STT client uses SpeechRecognition when available and emits interim/final hypotheses.
 */
export class BrowserSTT {
  constructor({ onResult, onError }) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.rec = SR ? new SR() : null;
    this.onResult = onResult;
    this.onError = onError;
    this._seq = 0;

    if (this.rec) {
      this.rec.continuous = true;
      this.rec.interimResults = true;
      this.rec.lang = "en-US";

      this.rec.onresult = (event) => {
        try {
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const r = event.results[i];
            const txt = r[0]?.transcript || "";
            const isFinal = !!r.isFinal;
            const conf = r[0]?.confidence ?? 0.0;
            this.onResult?.({ text: txt, is_final: isFinal, confidence: conf, seq: ++this._seq, src: "browser_sr" });
          }
        } catch (e) {
          this.onError?.(e);
        }
      };
      this.rec.onerror = (e) => this.onError?.(e);
      this.rec.onend = () => {
        // auto-restart handled by caller if desired
      };
    }
  }

  supported() { return !!this.rec; }

  start() {
    if (!this.rec) return;
    try { this.rec.start(); } catch {}
  }

  stop() {
    if (!this.rec) return;
    try { this.rec.stop(); } catch {}
  }
}
