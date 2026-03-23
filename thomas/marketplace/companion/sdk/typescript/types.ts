export type JSONObject = Record<string, unknown>;

export interface CompanionKernelStatus {
  kernel_version: string;
  root: string;
  modules_dir: string;
  bundles_dir: string;
  require_signed_updates: boolean;
  tailscale_only: boolean;
  modules_count: number;
  devices_count: number;
  releases_count: number;
}

export interface CompanionPolicySummary {
  tailscale_only: boolean;
  tailscale_suffix: string;
  require_signed_updates: boolean;
  default_profile_id?: string;
  profiles_count?: number;
}

export interface CompanionPolicyProfile {
  profile_id: string;
  description: string;
  source_rules: string[];
  effective_from: string;
  deprecation_date: string;
  enforcement_level: "warn" | "block" | string;
  platforms: string[];
  distribution_channels: string[];
  storefront_regions: string[];
  allowed_component_types: string[];
  forbidden_component_types: string[];
  allowed_permissions: string[];
  allowed_runtime_capabilities: string[];
  blocked_url_schemes: string[];
  allowed_webview_domains: string[];
  allow_arbitrary_external_navigation: boolean;
  allowed_external_navigation_domains: string[];
  require_store_billing_for_digital: boolean;
  require_moderation_for_ugc: boolean;
  required_moderation_controls: string[];
  required_privacy_fields: string[];
  required_age_gate_for_ugc: boolean;
}

export interface CompanionStatusResponse {
  ok: boolean;
  api_version: "v1";
  kernel: CompanionKernelStatus;
  policy: CompanionPolicySummary;
  policy_profiles?: CompanionPolicyProfile[];
  endpoints: string[];
}

export interface CompanionContractResponse {
  ok: boolean;
  api_version: "v1";
  kernel_version: string;
  minimum_requirements: string[];
  module_contract_fields: string[];
  permission_allowlist: string[];
  signed_updates_required: boolean;
  tailscale_only: boolean;
  api_endpoints: string[];
}

export interface CompanionStudioReleaseControls {
  supports_rollout_pct: boolean;
  supports_target_devices: boolean;
  supports_exclude_devices: boolean;
  supports_min_app_version: boolean;
  supports_required_capabilities: boolean;
  supports_status: boolean;
  supports_device_pinning: boolean;
  supports_release_promote: boolean;
  supports_release_rollback: boolean;
}

export interface CompanionStudioCapabilitiesResponse {
  ok: boolean;
  api_version: "v1";
  generated_at: string;
  module_contract_fields: string[];
  permission_allowlist: string[];
  default_slots: string[];
  ui_component_primitives: string[];
  action_primitives: string[];
  data_primitives: string[];
  release_controls: CompanionStudioReleaseControls;
  policy_profiles?: CompanionPolicyProfile[];
  templates: {
    module: CompanionModuleContract;
    screen_payload: unknown;
  };
}

export interface CompanionModuleState {
  module_id: string;
  version: string;
  status: "enabled" | "disabled" | string;
  entrypoint: string;
  display_name: string;
  description: string;
  slots: string[];
  permissions: string[];
  source_bundle: string;
  installed_at: string;
  updated_at: string;
}

export interface CompanionModuleContract {
  id: string;
  version: string;
  entrypoint: string;
  slots: string[];
  permissions: string[];
  ui_schema_version: string;
  display_name: string;
  description: string;
}

export interface CompanionBundleFile {
  path: string;
  sha256: string;
}

export interface CompanionBundleSignature {
  algo: "hmac-sha256" | string;
  value: string;
}

export interface CompanionUpdateBundleManifest {
  schema_version: number;
  bundle_id: string;
  created_at: string;
  min_kernel_version: string;
  module: CompanionModuleContract;
  files: CompanionBundleFile[];
  release_notes: string;
  signature?: CompanionBundleSignature;
}

export interface CompanionSlotModuleRef {
  module_id: string;
  version: string;
  entrypoint: string;
  display_name: string;
}

export interface CompanionSlotWidget {
  module_id: string;
  version: string;
  display_name: string;
  entrypoint: string;
  permissions: string[];
  payload: unknown;
}

export interface CompanionSlotRenderError {
  module_id: string;
  error: string;
}

export interface CompanionSlotRenderResponse {
  ok: boolean;
  slot: string;
  widgets: CompanionSlotWidget[];
  errors: CompanionSlotRenderError[];
  count: number;
}

export type CompanionSlotIndex = Record<string, CompanionSlotModuleRef[]>;

export interface CompanionModuleListResponse {
  ok: boolean;
  count: number;
  modules: CompanionModuleState[];
}

export interface CompanionSlotsResponse {
  ok: boolean;
  slots: CompanionSlotIndex;
  enabled_modules: number;
}

export interface CompanionModuleToggleResponse {
  ok: boolean;
  module?: CompanionModuleState;
  error?: string;
}

export interface CompanionBundleVerifyRequest {
  bundle_dir: string;
  actor?: string;
}

export interface CompanionBundleVerifyResponse {
  ok: boolean;
  errors: string[];
  warnings: string[];
  touched_paths: string[];
  module: CompanionModuleContract | null;
  manifest: CompanionUpdateBundleManifest | null;
  peer_identity: string;
  bundle_dir: string;
}

export interface CompanionBundleApplyRequest {
  bundle_dir: string;
  dry_run?: boolean;
  execute?: boolean;
  actor?: string;
}

export interface CompanionBundleApplyResponse {
  ok: boolean;
  dry_run: boolean;
  module_id?: string;
  bundle_id?: string;
  applied_files: string[];
  errors: string[];
  warnings: string[];
  peer_identity: string;
  bundle_dir: string;
}

export interface CompanionBundlePreviewRequest {
  bundle_dir: string;
  actor?: string;
}

export interface CompanionBundlePreviewWidget {
  module_id: string;
  version: string;
  display_name: string;
  entrypoint: string;
  permissions: string[];
  payload: unknown;
}

export interface CompanionBundlePreviewResponse {
  ok: boolean;
  bundle_dir: string;
  warnings: string[];
  errors?: string[];
  preview: {
    module: CompanionModuleContract;
    slots: Record<string, CompanionBundlePreviewWidget[]>;
  } | null;
}

export interface CompanionShipRequest {
  bundle_dir: string;
  channel?: string;
  actor?: string;
  execute?: boolean;
  target_device_id?: string;
  platform?: string;
  distribution_channel?: string;
  storefront_region?: string;
  policy_profile_id?: string;
  runtime_capability_set?: string[];
  required_capabilities?: string[];
  commerce_model?: "digital_in_app" | "physical_or_off_app" | "enterprise_internal" | string;
  store_billing_enabled?: boolean;
  ugc_enabled?: boolean;
  moderation_controls?: string[];
  age_gate_enabled?: boolean;
  collects_personal_data?: boolean;
  privacy_policy_url?: string;
  url_allowlist?: string[];
}

export interface CompanionShipResponse {
  ok: boolean;
  channel: string;
  verify: CompanionBundleVerifyResponse;
  apply: CompanionBundleApplyResponse | null;
  release: CompanionReleasePublishResponse | null;
  compliance?: CompanionComplianceCheckEnvelope | null;
}

export interface CompanionDevice {
  device_id: string;
  platform: string;
  app_version: string;
  channel: string;
  distribution_channel: string;
  storefront_region: string;
  app_build_id: string;
  tailscale_identity: string;
  capabilities: string[];
  runtime_capability_set: string[];
  installed_modules: Record<string, string>;
  metadata: JSONObject;
  policy_profile: string;
  pinned_release_id: string;
  pinned_at: string;
  created_at: string;
  last_seen_at: string;
}

export interface CompanionDevicesResponse {
  ok: boolean;
  count: number;
  devices: CompanionDevice[];
}

export interface CompanionDeviceRegisterRequest {
  device_id: string;
  platform?: string;
  app_version?: string;
  channel?: string;
  distribution_channel?: string;
  storefront_region?: string;
  app_build_id?: string;
  capabilities?: string[];
  runtime_capability_set?: string[];
  installed_modules?: Record<string, string>;
  metadata?: JSONObject;
  policy_profile_id?: string;
  actor?: string;
}

export interface CompanionDeviceRegisterResponse {
  ok: boolean;
  device: CompanionDevice;
}

export interface CompanionDeviceHeartbeatRequest {
  platform?: string;
  app_version?: string;
  channel?: string;
  distribution_channel?: string;
  storefront_region?: string;
  app_build_id?: string;
  capabilities?: string[];
  runtime_capability_set?: string[];
  installed_modules?: Record<string, string>;
  metadata?: JSONObject;
  policy_profile_id?: string;
  actor?: string;
}

export interface CompanionDeviceHeartbeatResponse {
  ok: boolean;
  device?: CompanionDevice;
  error?: string;
}

export interface CompanionRelease {
  release_id: string;
  channel: string;
  created_at: string;
  bundle_id: string;
  bundle_dir: string;
  manifest_path: string;
  module_id: string;
  module_version: string;
  min_kernel_version: string;
  release_notes: string;
  published_by: string;
  rollout_pct: number;
  target_devices: string[];
  exclude_devices: string[];
  min_app_version: string;
  required_capabilities: string[];
  status: string;
  policy_profile_id: string;
  compliance_report_id: string;
  compliance_status: string;
  compliance_violations: number;
  compliance_warnings: number;
  compliance_checked_at: string;
  bundle_archive_sha256?: string;
  bundle_archive_size?: number;
}

export interface CompanionDeviceUpdatesCheckRequest {
  channel?: string;
  installed_modules?: Record<string, string>;
  actor?: string;
}

export interface CompanionDeviceUpdatesCheckResponse {
  ok: boolean;
  device_id?: string;
  channel?: string;
  source?: "pinned" | "channel" | string;
  pinned_release_id?: string;
  count?: number;
  updates?: CompanionRelease[];
  error?: string;
}

export interface CompanionReleasesResponse {
  ok: boolean;
  count: number;
  releases: CompanionRelease[];
}

export interface CompanionReleaseGetResponse {
  ok: boolean;
  release?: CompanionRelease;
  error?: string;
}

export interface CompanionReleaseManifestResponse {
  ok: boolean;
  release?: CompanionRelease;
  manifest?: CompanionUpdateBundleManifest;
  error?: string;
}

export interface CompanionReleaseRolloutRequest {
  rollout_pct?: number;
  target_devices?: string[];
  exclude_devices?: string[];
  min_app_version?: string;
  required_capabilities?: string[];
  status?: string;
  actor?: string;
}

export interface CompanionReleaseRolloutResponse {
  ok: boolean;
  release?: CompanionRelease;
  error?: string;
}

export interface CompanionReleasePromoteRequest {
  channel?: string;
  actor?: string;
}

export interface CompanionReleasePromoteResponse {
  ok: boolean;
  error?: string;
  release: CompanionRelease | null;
}

export interface CompanionDevicePinReleaseRequest {
  release_id: string;
  actor?: string;
}

export interface CompanionDevicePinReleaseResponse {
  ok: boolean;
  device?: CompanionDevice;
  release?: CompanionRelease;
  error?: string;
}

export interface CompanionDeviceUnpinReleaseRequest {
  actor?: string;
}

export interface CompanionDeviceUnpinReleaseResponse {
  ok: boolean;
  device?: CompanionDevice;
  error?: string;
}

export interface CompanionStudioBuildBundleRequest {
  module?: {
    id: string;
    version: string;
    entrypoint?: string;
    slots?: string[];
    permissions?: string[];
    ui_schema_version?: string;
    display_name?: string;
    description?: string;
  };
  module_id?: string;
  module_version?: string;
  display_name?: string;
  description?: string;
  slots?: string[];
  permissions?: string[];
  screen_payload?: unknown;
  release_notes?: string;
  min_kernel_version?: string;
  output_dir?: string;
  overwrite?: boolean;
  extra_files?: Array<{ path: string; content: unknown }>;
}

export interface CompanionStudioBuildBundleResponse {
  ok: boolean;
  bundle_dir?: string;
  manifest?: CompanionUpdateBundleManifest;
  files?: CompanionBundleFile[];
  file_count?: number;
  error?: string;
}

export interface CompanionReleasePublishRequest {
  bundle_dir: string;
  channel?: string;
  actor?: string;
  target_device_id?: string;
  platform?: string;
  distribution_channel?: string;
  storefront_region?: string;
  policy_profile_id?: string;
  runtime_capability_set?: string[];
  required_capabilities?: string[];
  commerce_model?: "digital_in_app" | "physical_or_off_app" | "enterprise_internal" | string;
  store_billing_enabled?: boolean;
  ugc_enabled?: boolean;
  moderation_controls?: string[];
  age_gate_enabled?: boolean;
  collects_personal_data?: boolean;
  privacy_policy_url?: string;
  url_allowlist?: string[];
}

export interface CompanionReleasePublishResponse {
  ok: boolean;
  errors: string[];
  warnings: string[];
  release: CompanionRelease | null;
  verify?: CompanionBundleVerifyResponse;
  compliance?: CompanionComplianceCheckEnvelope;
}

export interface CompanionComplianceViolation {
  code: string;
  severity: "warn" | "block" | string;
  message: string;
  path: string;
  remediation: string;
}

export interface CompanionComplianceReport {
  report_id: string;
  ok: boolean;
  checked_at: string;
  policy_profile_id: string;
  enforcement_level: "warn" | "block" | string;
  violations: CompanionComplianceViolation[];
  warnings: string[];
  counts: {
    violations: number;
    blocking_violations: number;
    warnings: number;
  };
  inputs: JSONObject;
}

export interface CompanionComplianceCheckEnvelope {
  ok: boolean;
  report: CompanionComplianceReport;
  context: JSONObject;
}

export interface CompanionComplianceCheckRequest {
  bundle_dir: string;
  actor?: string;
  target_device_id?: string;
  platform?: string;
  distribution_channel?: string;
  storefront_region?: string;
  policy_profile_id?: string;
  runtime_capability_set?: string[];
  required_capabilities?: string[];
  commerce_model?: "digital_in_app" | "physical_or_off_app" | "enterprise_internal" | string;
  store_billing_enabled?: boolean;
  ugc_enabled?: boolean;
  moderation_controls?: string[];
  age_gate_enabled?: boolean;
  collects_personal_data?: boolean;
  privacy_policy_url?: string;
  url_allowlist?: string[];
}

export interface CompanionComplianceCheckResponse {
  ok: boolean;
  bundle_dir: string;
  verify: CompanionBundleVerifyResponse;
  compliance: CompanionComplianceCheckEnvelope;
}

export interface CompanionPolicyProfilesResponse {
  ok: boolean;
  count: number;
  profiles: CompanionPolicyProfile[];
}

export interface CompanionPolicyProfileGetResponse {
  ok: boolean;
  profile?: CompanionPolicyProfile;
  error?: string;
}

export interface CompanionAuditEvent {
  timestamp: string;
  event_type: string;
  actor: string;
  peer_identity: string;
  details: JSONObject;
}

export interface CompanionAuditEventsResponse {
  ok: boolean;
  count: number;
  events: CompanionAuditEvent[];
}

export interface CompanionBootstrapResponse {
  ok: boolean;
  api_version: "v1";
  generated_at: string;
  kernel: CompanionKernelStatus;
  policy: CompanionPolicySummary;
  device: CompanionDevice | null;
  modules: CompanionModuleState[];
  slots: CompanionSlotIndex;
  slot_payloads: Record<string, Omit<CompanionSlotRenderResponse, "ok">>;
}
