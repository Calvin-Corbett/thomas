import { nowMs } from "./util.js";

/**
 * Audio capture strategies:
 * 1) MediaRecorder (preferred) => webm/opus chunks
 * 2) AudioWorklet PCM (fallback) => Float32 -> Int16 frames (not implemented fully here)
 *
 * This module is intentionally modular so you can upgrade the fallback path without touching UI logic.
 */

export class AudioCapture {
  constructor({ mime, onChunk, onVadStart, onVadEnd, onError }) {
    this.mime = mime || "audio/webm;codecs=opus";
    this.onChunk = onChunk;
    this.onVadStart = onVadStart;
    this.onVadEnd = onVadEnd;
    this.onError = onError;

    this.stream = null;
    this.rec = null;
    this.seq = 0;

    // VAD (simple energy threshold over time)
    this._audioCtx = null;
    this._analyser = null;
    this._vadTimer = null;
    this._speaking = false;
    this._vadCfg = { threshold: 0.02, hangMs: 450, pollMs: 60 };
    this._lastAbove = 0;
  }

  async start() {
    this.seq = 0;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    await this._startVAD(this.stream);

    if (typeof MediaRecorder !== "undefined") {
      this.rec = new MediaRecorder(this.stream, { mimeType: this.mime });
      this.rec.ondataavailable = async (e) => {
        if (!e.data || e.data.size === 0) return;
        const buf = await e.data.arrayBuffer();
        this.onChunk?.({ seq: ++this.seq, ts: nowMs(), mime: this.mime, data: buf });
      };
      this.rec.onerror = (e) => this.onError?.(e);
      // Small timeslice reduces latency but increases overhead; 120ms is a good middle ground.
      this.rec.start(120);
      return;
    }

    throw new Error("No MediaRecorder available (upgrade AudioWorklet fallback if needed).");
  }

  stop() {
    try {
      if (this.rec && this.rec.state !== "inactive") this.rec.stop();
    } catch {}
    this.rec = null;

    try {
      if (this.stream) {
        for (const t of this.stream.getTracks()) t.stop();
      }
    } catch {}
    this.stream = null;

    this._stopVAD();
  }

  async _startVAD(stream) {
    try {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = this._audioCtx.createMediaStreamSource(stream);
      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 512;
      src.connect(this._analyser);

      const buf = new Float32Array(this._analyser.fftSize);
      this._vadTimer = setInterval(() => {
        try {
          // measure RMS energy
          const data = new Float32Array(this._analyser.fftSize);
          this._analyser.getFloatTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
          const rms = Math.sqrt(sum / data.length);

          const now = nowMs();
          if (rms > this._vadCfg.threshold) {
            this._lastAbove = now;
            if (!this._speaking) {
              this._speaking = true;
              this.onVadStart?.({ ts: now, rms });
            }
          } else {
            if (this._speaking && (now - this._lastAbove) > this._vadCfg.hangMs) {
              this._speaking = false;
              this.onVadEnd?.({ ts: now, rms });
            }
          }
        } catch (e) {
          // ignore; keep VAD resilient
        }
      }, this._vadCfg.pollMs);
    } catch (e) {
      // VAD is optional; capture can still work.
      this.onError?.(e);
    }
  }

  _stopVAD() {
    if (this._vadTimer) clearInterval(this._vadTimer);
    this._vadTimer = null;
    try { if (this._audioCtx) this._audioCtx.close(); } catch {}
    this._audioCtx = null;
    this._analyser = null;
    this._speaking = false;
  }
}
