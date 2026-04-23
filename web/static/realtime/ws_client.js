import { nowMs } from "./util.js";

export class RealtimeWS {
  constructor({ url, onMessage, onOpen, onClose, onError, autoReconnect=true }) {
    this.url = url;
    this.ws = null;
    this.onMessage = onMessage;
    this.onOpen = onOpen;
    this.onClose = onClose;
    this.onError = onError;
    this.autoReconnect = autoReconnect;

    this._pingN = 0;
    this._pingTimer = null;

    this._reconnectTimer = null;
    this._reconnectAttempt = 0;
    this._closing = false;
  }

  connect() {
    if (this.ws) return;
    this._closing = false;
    this._openSocket();
  }

  _openSocket() {
    this.ws = new WebSocket(this.url);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      this._reconnectAttempt = 0;
      this.onOpen?.();
      this._startPing();
    };

    this.ws.onclose = () => {
      this._stopPing();
      const ws = this.ws;
      this.ws = null;
      this.onClose?.(ws);
      if (this.autoReconnect && !this._closing) this._scheduleReconnect();
    };

    this.ws.onerror = (e) => this.onError?.(e);

    this.ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const obj = JSON.parse(ev.data);
          this.onMessage?.(obj);
        } catch (e) {
          this.onMessage?.({ t: "error", code: "bad_json", message: String(e) });
        }
      } else {
        this.onMessage?.({ t: "binary", bytes: ev.data?.byteLength || 0 });
      }
    };
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    this._reconnectAttempt++;
    const base = Math.min(8000, 300 * Math.pow(1.55, this._reconnectAttempt));
    const jitter = Math.random() * 150;
    const wait = Math.round(base + jitter);
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (!this.ws && !this._closing) this._openSocket();
    }, wait);
  }

  close() {
    this._closing = true;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._reconnectTimer = null;

    if (!this.ws) return;
    try { this.ws.close(); } catch {}
    this.ws = null;
    this._stopPing();
  }

  send(obj) {
    if (!this.ws) return false;
    this.ws.send(JSON.stringify({ ...obj }));
    return true;
  }

  sendBinary(buf) {
    if (!this.ws) return false;
    this.ws.send(buf);
    return true;
  }

  sendInterrupt(reason="interrupt") {
    return this.send({ t: "interrupt", reason });
  }

  sendPing() {
    this._pingN++;
    return this.send({ t: "ping", n: this._pingN, client_ts: nowMs() });
  }

  _startPing() {
    this._pingTimer = setInterval(() => this.sendPing(), 8000);
  }
  _stopPing() {
    if (this._pingTimer) clearInterval(this._pingTimer);
    this._pingTimer = null;
  }
}
