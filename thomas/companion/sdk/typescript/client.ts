import type {
  CompanionAuditEventsResponse,
  CompanionBootstrapResponse,
  CompanionBundleApplyRequest,
  CompanionBundleApplyResponse,
  CompanionBundlePreviewRequest,
  CompanionBundlePreviewResponse,
  CompanionBundleVerifyRequest,
  CompanionBundleVerifyResponse,
  CompanionContractResponse,
  CompanionComplianceCheckRequest,
  CompanionComplianceCheckResponse,
  CompanionStudioCapabilitiesResponse,
  CompanionDeviceHeartbeatRequest,
  CompanionDeviceHeartbeatResponse,
  CompanionDevicePinReleaseRequest,
  CompanionDevicePinReleaseResponse,
  CompanionDeviceRegisterRequest,
  CompanionDeviceRegisterResponse,
  CompanionDeviceUnpinReleaseRequest,
  CompanionDeviceUnpinReleaseResponse,
  CompanionDevicesResponse,
  CompanionDeviceUpdatesCheckRequest,
  CompanionDeviceUpdatesCheckResponse,
  CompanionModuleListResponse,
  CompanionModuleToggleResponse,
  CompanionReleaseGetResponse,
  CompanionReleaseManifestResponse,
  CompanionReleasePromoteRequest,
  CompanionReleasePromoteResponse,
  CompanionReleasePublishRequest,
  CompanionReleasePublishResponse,
  CompanionReleaseRolloutRequest,
  CompanionReleaseRolloutResponse,
  CompanionPolicyProfileGetResponse,
  CompanionPolicyProfilesResponse,
  CompanionReleasesResponse,
  CompanionShipRequest,
  CompanionShipResponse,
  CompanionStudioBuildBundleRequest,
  CompanionStudioBuildBundleResponse,
  CompanionSlotRenderResponse,
  CompanionSlotsResponse,
  CompanionStatusResponse,
} from "./types";

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface CompanionClientOptions {
  baseUrl?: string;
  apiToken?: string;
  getApiToken?: () => string | undefined;
  peerIdentity?: string;
  getPeerIdentity?: () => string | undefined;
  fetchImpl?: FetchLike;
  defaultHeaders?: Record<string, string>;
}

export interface CompanionRequestOptions {
  signal?: AbortSignal;
  peerIdentity?: string;
}

export class CompanionApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly responseText: string;

  constructor(message: string, status: number, url: string, responseText: string) {
    super(message);
    this.name = "CompanionApiError";
    this.status = status;
    this.url = url;
    this.responseText = responseText;
  }
}

export class CompanionClient {
  private readonly baseUrl: string;
  private readonly apiToken?: string;
  private readonly getApiToken?: () => string | undefined;
  private readonly peerIdentity?: string;
  private readonly getPeerIdentity?: () => string | undefined;
  private readonly fetchImpl: FetchLike;
  private readonly defaultHeaders: Record<string, string>;

  constructor(options: CompanionClientOptions = {}) {
    this.baseUrl = (options.baseUrl || "").replace(/\/+$/, "");
    this.apiToken = options.apiToken;
    this.getApiToken = options.getApiToken;
    this.peerIdentity = options.peerIdentity;
    this.getPeerIdentity = options.getPeerIdentity;
    this.fetchImpl = options.fetchImpl || (globalThis.fetch as FetchLike);
    this.defaultHeaders = { ...(options.defaultHeaders || {}) };
    if (!this.fetchImpl) {
      throw new Error("No fetch implementation available. Pass fetchImpl in CompanionClientOptions.");
    }
  }

  async status(opts: CompanionRequestOptions = {}): Promise<CompanionStatusResponse> {
    return this.requestJson("GET", "/api/companion/v1/status", { signal: opts.signal });
  }

  async contract(opts: CompanionRequestOptions = {}): Promise<CompanionContractResponse> {
    return this.requestJson("GET", "/api/companion/v1/contract", { signal: opts.signal });
  }

  async studioCapabilities(
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionStudioCapabilitiesResponse> {
    return this.requestJson("GET", "/api/companion/v1/studio/capabilities", { signal: opts.signal });
  }

  async policyProfiles(opts: CompanionRequestOptions = {}): Promise<CompanionPolicyProfilesResponse> {
    return this.requestJson("GET", "/api/companion/v1/policy/profiles", { signal: opts.signal });
  }

  async policyProfile(
    profileId: string,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionPolicyProfileGetResponse> {
    const id = encodeURIComponent(String(profileId || "").trim());
    if (!id) throw new Error("profileId is required");
    return this.requestJson("GET", `/api/companion/v1/policy/profile/${id}`, { signal: opts.signal });
  }

  async bootstrap(
    params: {
      deviceId?: string;
      includeSlotPayloads?: boolean;
    } = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionBootstrapResponse> {
    const query: Record<string, string> = {};
    if (params.deviceId) query.device_id = params.deviceId;
    if (typeof params.includeSlotPayloads === "boolean") {
      query.include_slot_payloads = params.includeSlotPayloads ? "1" : "0";
    }
    return this.requestJson("GET", "/api/companion/v1/bootstrap", {
      query,
      signal: opts.signal,
    });
  }

  async modules(opts: CompanionRequestOptions = {}): Promise<CompanionModuleListResponse> {
    return this.requestJson("GET", "/api/companion/v1/modules", { signal: opts.signal });
  }

  async slots(opts: CompanionRequestOptions = {}): Promise<CompanionSlotsResponse> {
    return this.requestJson("GET", "/api/companion/v1/slots", { signal: opts.signal });
  }

  async slot(slot: string, opts: CompanionRequestOptions = {}): Promise<CompanionSlotRenderResponse> {
    const key = encodeURIComponent(String(slot || "").trim());
    if (!key) throw new Error("slot is required");
    return this.requestJson("GET", `/api/companion/v1/slots/${key}`, { signal: opts.signal });
  }

  async enableModule(moduleId: string, opts: CompanionRequestOptions = {}): Promise<CompanionModuleToggleResponse> {
    const id = encodeURIComponent(String(moduleId || "").trim());
    if (!id) throw new Error("moduleId is required");
    return this.requestJson("POST", `/api/companion/v1/modules/${id}/enable`, {
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async disableModule(
    moduleId: string,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionModuleToggleResponse> {
    const id = encodeURIComponent(String(moduleId || "").trim());
    if (!id) throw new Error("moduleId is required");
    return this.requestJson("POST", `/api/companion/v1/modules/${id}/disable`, {
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async studioBuildBundle(
    payload: CompanionStudioBuildBundleRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionStudioBuildBundleResponse> {
    return this.requestJson("POST", "/api/companion/v1/studio/build-bundle", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async verifyBundle(
    payload: CompanionBundleVerifyRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionBundleVerifyResponse> {
    return this.requestJson("POST", "/api/companion/v1/bundles/verify", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async previewBundle(
    payload: CompanionBundlePreviewRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionBundlePreviewResponse> {
    return this.requestJson("POST", "/api/companion/v1/bundles/preview", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async applyBundle(
    payload: CompanionBundleApplyRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionBundleApplyResponse> {
    return this.requestJson("POST", "/api/companion/v1/bundles/apply", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async ship(payload: CompanionShipRequest, opts: CompanionRequestOptions = {}): Promise<CompanionShipResponse> {
    return this.requestJson("POST", "/api/companion/v1/ship", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async complianceCheck(
    payload: CompanionComplianceCheckRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionComplianceCheckResponse> {
    return this.requestJson("POST", "/api/companion/v1/compliance/check", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async devices(
    params: { channel?: string } = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDevicesResponse> {
    const query: Record<string, string> = {};
    if (params.channel) query.channel = params.channel;
    return this.requestJson("GET", "/api/companion/v1/devices", {
      query,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async registerDevice(
    payload: CompanionDeviceRegisterRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDeviceRegisterResponse> {
    return this.requestJson("POST", "/api/companion/v1/devices/register", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async heartbeatDevice(
    deviceId: string,
    payload: CompanionDeviceHeartbeatRequest = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDeviceHeartbeatResponse> {
    const id = encodeURIComponent(String(deviceId || "").trim());
    if (!id) throw new Error("deviceId is required");
    return this.requestJson("POST", `/api/companion/v1/devices/${id}/heartbeat`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async pinDeviceRelease(
    deviceId: string,
    payload: CompanionDevicePinReleaseRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDevicePinReleaseResponse> {
    const id = encodeURIComponent(String(deviceId || "").trim());
    if (!id) throw new Error("deviceId is required");
    return this.requestJson("POST", `/api/companion/v1/devices/${id}/pin-release`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async unpinDeviceRelease(
    deviceId: string,
    payload: CompanionDeviceUnpinReleaseRequest = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDeviceUnpinReleaseResponse> {
    const id = encodeURIComponent(String(deviceId || "").trim());
    if (!id) throw new Error("deviceId is required");
    return this.requestJson("POST", `/api/companion/v1/devices/${id}/unpin-release`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async checkDeviceUpdates(
    deviceId: string,
    payload: CompanionDeviceUpdatesCheckRequest = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionDeviceUpdatesCheckResponse> {
    const id = encodeURIComponent(String(deviceId || "").trim());
    if (!id) throw new Error("deviceId is required");
    return this.requestJson("POST", `/api/companion/v1/devices/${id}/updates/check`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async releases(
    params: {
      channel?: string;
      moduleId?: string;
      limit?: number;
    } = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleasesResponse> {
    const query: Record<string, string> = {};
    if (params.channel) query.channel = params.channel;
    if (params.moduleId) query.module_id = params.moduleId;
    if (typeof params.limit === "number") query.limit = String(params.limit);
    return this.requestJson("GET", "/api/companion/v1/releases", {
      query,
      signal: opts.signal,
    });
  }

  async release(releaseId: string, opts: CompanionRequestOptions = {}): Promise<CompanionReleaseGetResponse> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    return this.requestJson("GET", `/api/companion/v1/releases/${id}`, {
      signal: opts.signal,
    });
  }

  async releaseManifest(
    releaseId: string,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleaseManifestResponse> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    return this.requestJson("GET", `/api/companion/v1/releases/${id}/manifest`, {
      signal: opts.signal,
    });
  }

  async downloadReleaseBundle(releaseId: string, opts: CompanionRequestOptions = {}): Promise<Blob> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    const res = await this.requestRaw("GET", `/api/companion/v1/releases/${id}/download`, {
      signal: opts.signal,
    });
    return res.blob();
  }

  async publishRelease(
    payload: CompanionReleasePublishRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleasePublishResponse> {
    return this.requestJson("POST", "/api/companion/v1/releases/publish", {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async setReleaseRollout(
    releaseId: string,
    payload: CompanionReleaseRolloutRequest,
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleaseRolloutResponse> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    return this.requestJson("POST", `/api/companion/v1/releases/${id}/rollout`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async promoteRelease(
    releaseId: string,
    payload: CompanionReleasePromoteRequest = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleasePromoteResponse> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    return this.requestJson("POST", `/api/companion/v1/releases/${id}/promote`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async rollbackRelease(
    releaseId: string,
    payload: CompanionReleasePromoteRequest = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionReleasePromoteResponse> {
    const id = encodeURIComponent(String(releaseId || "").trim());
    if (!id) throw new Error("releaseId is required");
    return this.requestJson("POST", `/api/companion/v1/releases/${id}/rollback`, {
      body: payload,
      signal: opts.signal,
      requirePeerIdentity: true,
      peerIdentity: opts.peerIdentity,
    });
  }

  async auditEvents(
    params: {
      limit?: number;
      eventType?: string;
    } = {},
    opts: CompanionRequestOptions = {},
  ): Promise<CompanionAuditEventsResponse> {
    const query: Record<string, string> = {};
    if (typeof params.limit === "number") query.limit = String(params.limit);
    if (params.eventType) query.event_type = params.eventType;
    return this.requestJson("GET", "/api/companion/v1/audit/events", {
      query,
      signal: opts.signal,
    });
  }

  private resolveApiToken(): string {
    const dynamic = this.getApiToken ? String(this.getApiToken() || "").trim() : "";
    if (dynamic) return dynamic;
    return String(this.apiToken || "").trim();
  }

  private resolvePeerIdentity(override?: string): string {
    const explicit = String(override || "").trim();
    if (explicit) return explicit;
    const dynamic = this.getPeerIdentity ? String(this.getPeerIdentity() || "").trim() : "";
    if (dynamic) return dynamic;
    return String(this.peerIdentity || "").trim();
  }

  private buildUrl(path: string, query?: Record<string, string>): string {
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    const queryParts: string[] = [];
    for (const [key, val] of Object.entries(query || {})) {
      const k = String(key || "").trim();
      if (!k) continue;
      queryParts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(val || ""))}`);
    }
    const queryString = queryParts.length ? `?${queryParts.join("&")}` : "";
    if (!this.baseUrl) return `${cleanPath}${queryString}`;
    return `${this.baseUrl}${cleanPath}${queryString}`;
  }

  private async requestJson<T>(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    options: {
      query?: Record<string, string>;
      body?: unknown;
      signal?: AbortSignal;
      requirePeerIdentity?: boolean;
      peerIdentity?: string;
    } = {},
  ): Promise<T> {
    const res = await this.requestRaw(method, path, options);
    return (await res.json()) as T;
  }

  private async requestRaw(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    options: {
      query?: Record<string, string>;
      body?: unknown;
      signal?: AbortSignal;
      requirePeerIdentity?: boolean;
      peerIdentity?: string;
    } = {},
  ): Promise<Response> {
    const url = this.buildUrl(path, options.query);
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...this.defaultHeaders,
    };

    const token = this.resolveApiToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    if (options.requirePeerIdentity) {
      const peer = this.resolvePeerIdentity(options.peerIdentity);
      if (!peer) {
        throw new Error(
          "Missing peer identity. Set CompanionClientOptions.peerIdentity/getPeerIdentity or pass opts.peerIdentity.",
        );
      }
      headers["X-Companion-Peer"] = peer;
    }

    const init: RequestInit = {
      method,
      headers,
      signal: options.signal,
    };

    if (typeof options.body !== "undefined") {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }

    const res = await this.fetchImpl(url, init);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new CompanionApiError(
        `Companion API ${method} ${path} failed: ${res.status}${text ? `: ${text}` : ""}`,
        res.status,
        url,
        text,
      );
    }
    return res;
  }
}
