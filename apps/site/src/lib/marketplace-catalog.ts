import crypto from "node:crypto";
import { getCanonicalSiteUrl } from "@/lib/site-config";
import { classifyMarketplaceRow, marketplaceRowIsVisible } from "@/lib/marketplace-surface-policy";
import { marketplaceSnapshot } from "@/lib/marketplace-snapshot.generated";

type JsonRecord = Record<string, unknown>;

export type HostedPluginRecord = {
  id: string;
  bundleBase64: string;
  bundleSizeBytes: number;
  sha256: string;
  manifest: JsonRecord;
};

export type MarketplaceCatalogRow = {
  id: string;
  plugin_id: string;
  name: string;
  display_name: string;
  version: string;
  subtitle: string;
  description: string;
  category: string;
  category_label: string;
  categories: string[];
  tags: string[];
  requires: string[];
  target: string;
  mode: string;
  mode_id: string;
  marketplace_type: string;
  marketplace_type_label: string;
  left_nav_behavior: string;
  default_nav_section: string;
  default_nav_order: number;
  entrypoint: string;
  capabilities: string[];
  kind: string;
  source: string;
  publisher_id: string;
  publisher_name: string;
  icon: string;
  api_namespace: string;
  download_available: boolean;
  installable: boolean;
  availability: "installable" | "catalog_only" | "scaffold" | "hidden";
  eligibility_reason: string;
  promotion_status: "official_hosted" | "inventory_only" | "blocked" | "suppressed";
  shipped_surface: boolean;
  needs_review: boolean;
  installed: boolean;
  enabled: boolean;
  workspace_id: string;
  download_url: string;
  manual_download_url: string;
  detail_url: string;
  open_in_thomas_url: string;
  store_url: string;
  channel: string;
  surface: {
    entry_html: string;
    title: string;
    surface_mode: string;
  };
};

export type MarketplaceCatalogPayload = {
  ok: true;
  generated_at: string;
  catalog_source: string;
  store_url: string;
  channel: string;
  count: number;
  total: number;
  categories: Array<{ id: string; label: string; count: number }>;
  types: Array<{ id: string; label: string; count: number }>;
  plugins: MarketplaceCatalogRow[];
};

const MARKETPLACE_TYPES = new Set(["app", "plugin", "dependency", "integration"]);
// "command_center" renamed to "app" (2026-06-11); legacy values normalize on read.
const LEGACY_TYPE_ALIASES: Record<string, string> = { command_center: "app" };
const LEFT_NAV_BEHAVIORS = new Set(["none", "workspace"]);
const DEFAULT_NAV_SECTIONS = new Set(["apps", "installed"]);
const LEGACY_NAV_ALIASES: Record<string, string> = { command_centers: "apps" };
const TYPE_LABELS: Record<string, string> = {
  app: "App",
  command_center: "App",
  plugin: "Plugin",
  dependency: "Dependency",
  integration: "Integration",
};
const TRUSTED_PUBLISHER_IDS = new Set(["thomas-official", "approved-partner"]);
const LOCAL_DEV_STORE_API_KEY = "local-dev-install-key";
const LOCAL_DEV_TOKEN_SECRET = crypto.randomBytes(32).toString("hex");
const MAX_DOWNLOAD_TOKEN_LENGTH = 2048;
const MAX_DOWNLOAD_TOKEN_PAYLOAD_LENGTH = 1024;

function safeString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function safeInt(value: unknown, fallback: number): number {
  const parsed = Number.parseInt(safeString(value), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const text = safeString(item).trim();
    if (text && !out.includes(text)) {
      out.push(text);
    }
  }
  return out;
}

function slugify(value: unknown): string {
  return safeString(value).trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function slugLabel(value: unknown): string {
  const parts = safeString(value)
    .replace(/_/g, "-")
    .split("-")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return "Other";
  return parts.map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function normalizeCategories(raw: JsonRecord): string[] {
  const categories = stringList(raw.categories);
  const primary = slugify(raw.category) || "other";
  if (!categories.includes(primary)) {
    categories.unshift(primary);
  }
  return categories;
}

function ensureTag(tags: string[], value: unknown) {
  const text = safeString(value).trim();
  if (text && !tags.includes(text)) {
    tags.push(text);
  }
}

function inferMarketplaceType(raw: JsonRecord, target: string, mode: string, hosted: HostedPluginRecord | null): string {
  let explicit = safeString(raw.marketplace_type || hosted?.manifest.marketplace_type).trim().toLowerCase();
  explicit = LEGACY_TYPE_ALIASES[explicit] ?? explicit;
  if (MARKETPLACE_TYPES.has(explicit)) {
    return explicit;
  }
  if (hosted && safeString(hosted.manifest.kind).toLowerCase() === "desktop_plugin" && mode) {
    return "app";
  }
  if (target === "desktop" && mode) {
    return "app";
  }
  return "plugin";
}

function inferLeftNavBehavior(raw: JsonRecord, marketplaceType: string, hosted: HostedPluginRecord | null): string {
  const explicit = safeString(raw.left_nav_behavior || hosted?.manifest.left_nav_behavior).trim().toLowerCase();
  if (LEFT_NAV_BEHAVIORS.has(explicit)) {
    return explicit;
  }
  return marketplaceType === "app" ? "workspace" : "none";
}

function inferDefaultNavSection(raw: JsonRecord, marketplaceType: string, leftNavBehavior: string, hosted: HostedPluginRecord | null): string {
  let explicit = safeString(raw.default_nav_section || hosted?.manifest.default_nav_section).trim().toLowerCase();
  explicit = LEGACY_NAV_ALIASES[explicit] ?? explicit;
  if (DEFAULT_NAV_SECTIONS.has(explicit)) {
    return explicit;
  }
  return marketplaceType === "app" || leftNavBehavior === "workspace" ? "apps" : "installed";
}

function catalogStoreUrl(): string {
  return getCanonicalSiteUrl().replace(/\/+$/, "");
}

function buildOpenInThomasUrl(pluginId: string, storeUrl: string, channel: string): string {
  return `thomas://install-plugin?plugin_id=${encodeURIComponent(pluginId)}&store=${encodeURIComponent(storeUrl)}&channel=${encodeURIComponent(channel)}`;
}

function isProductionRuntime(): boolean {
  return process.env.NODE_ENV === "production" || process.env.THOMAS_ENV === "production";
}

function getTokenSecret(): string {
  const configuredSecret = safeString(process.env.THOMAS_SITE_PLUGIN_SIGN_SECRET || process.env.THOMAS_PLUGIN_SIGN_SECRET).trim();
  if (configuredSecret) {
    return configuredSecret;
  }
  if (isProductionRuntime()) {
    throw new Error(
      "THOMAS_SITE_PLUGIN_SIGN_SECRET or THOMAS_PLUGIN_SIGN_SECRET must be set in production before plugin downloads are enabled",
    );
  }
  return LOCAL_DEV_TOKEN_SECRET;
}

export function getStoreApiKey(): string {
  const configuredKey = safeString(process.env.THOMAS_PLUGIN_STORE_API_KEY).trim();
  if (configuredKey) {
    return configuredKey;
  }
  if (isProductionRuntime()) {
    throw new Error("THOMAS_PLUGIN_STORE_API_KEY must be set in production before plugin downloads are enabled");
  }
  return LOCAL_DEV_STORE_API_KEY;
}

export function storeApiKeysMatch(candidate: string, expected: string): boolean {
  const candidateBuffer = Buffer.from(safeString(candidate), "utf-8");
  const expectedBuffer = Buffer.from(safeString(expected), "utf-8");
  if (!candidateBuffer.length || candidateBuffer.length !== expectedBuffer.length) {
    return false;
  }
  return crypto.timingSafeEqual(candidateBuffer, expectedBuffer);
}

export function buildDownloadToken(pluginId: string, expires: number): string {
  const normalizedPluginId = safeString(pluginId).trim();
  if (!normalizedPluginId || !Number.isFinite(expires)) {
    throw new Error("Plugin download token requires a plugin id and finite expiry");
  }
  const encodedPayload = Buffer.from(
    JSON.stringify({
      plugin_id: normalizedPluginId,
      exp: Math.floor(expires),
    }),
    "utf-8",
  ).toString("base64url");
  const signature = crypto.createHmac("sha256", getTokenSecret()).update(encodedPayload).digest("hex");
  return `${encodedPayload}.${signature}`;
}

export function verifyDownloadToken(token: string): { pluginId: string; expires: number } | null {
  const normalizedToken = safeString(token);
  if (normalizedToken.length > MAX_DOWNLOAD_TOKEN_LENGTH) {
    return null;
  }

  const [encodedPayload, signature, extra] = normalizedToken.split(".");
  if (encodedPayload.length > MAX_DOWNLOAD_TOKEN_PAYLOAD_LENGTH) {
    return null;
  }
  if (!encodedPayload || !signature || extra || !/^[a-f0-9]{64}$/.test(signature)) {
    return null;
  }
  const expected = crypto.createHmac("sha256", getTokenSecret()).update(encodedPayload).digest("hex");
  if (!crypto.timingSafeEqual(Buffer.from(signature, "utf-8"), Buffer.from(expected, "utf-8"))) {
    return null;
  }

  let payload: JsonRecord;
  try {
    payload = JSON.parse(Buffer.from(encodedPayload, "base64url").toString("utf-8")) as JsonRecord;
  } catch {
    return null;
  }

  const pluginId = safeString(payload.plugin_id).trim();
  const expires = Number.parseInt(safeString(payload.exp), 10);
  if (!pluginId || !Number.isFinite(expires) || Date.now() / 1000 > expires) {
    return null;
  }
  return { pluginId, expires };
}

export function loadHostedPlugins(): Map<string, HostedPluginRecord> {
  const out = new Map<string, HostedPluginRecord>();
  const hostedPluginsRaw = (marketplaceSnapshot as JsonRecord).hostedPlugins;
  const hostedPlugins = Array.isArray(hostedPluginsRaw) ? hostedPluginsRaw : [];

  for (const rawEntry of hostedPlugins) {
    const entry = rawEntry && typeof rawEntry === "object" ? (rawEntry as JsonRecord) : null;
    if (!entry) {
      continue;
    }
    const manifest = entry.manifest && typeof entry.manifest === "object" ? (entry.manifest as JsonRecord) : {};
    const publisherId = safeString(manifest.publisher_id).trim();
    const signature = safeString(manifest.signature).trim();
    if (!TRUSTED_PUBLISHER_IDS.has(publisherId) || !signature) {
      continue;
    }
    const id = safeString(entry.id).trim();
    const bundleBase64 = safeString(entry.bundleBase64).trim();
    if (!id || !bundleBase64) {
      continue;
    }
    out.set(id, {
      id,
      bundleBase64,
      bundleSizeBytes: safeInt(entry.bundleSizeBytes, 0),
      sha256: safeString(entry.sha256).trim() || crypto.createHash("sha256").update(Buffer.from(bundleBase64, "base64")).digest("hex"),
      manifest,
    });
  }
  return out;
}

function normalizeCatalogRow(
  rawItem: JsonRecord,
  options: {
    hosted: HostedPluginRecord | null;
    storeUrl: string;
    channel: string;
  },
): MarketplaceCatalogRow | null {
  const { hosted, storeUrl, channel } = options;
  const pluginId = safeString(rawItem.id || rawItem.plugin_id || hosted?.id).trim();
  if (!pluginId) return null;
  const categories = normalizeCategories(rawItem);
  const target = safeString(rawItem.target || hosted?.manifest.target).trim();
  const mode = safeString(rawItem.mode || rawItem.mode_id || hosted?.manifest.mode_id).trim();
  const marketplaceType = inferMarketplaceType(rawItem, target, mode, hosted);
  const leftNavBehavior = inferLeftNavBehavior(rawItem, marketplaceType, hosted);
  const defaultNavSection = inferDefaultNavSection(rawItem, marketplaceType, leftNavBehavior, hosted);
  const tags = stringList(rawItem.tags || hosted?.manifest.tags);
  for (const value of categories) ensureTag(tags, value);
  ensureTag(tags, marketplaceType);
  ensureTag(tags, target);
  ensureTag(tags, mode);
  ensureTag(tags, leftNavBehavior);

  const hostedManifest = hosted?.manifest || {};
  const version = safeString(rawItem.version || hostedManifest.version).trim() || "0.0.0";
  const category = slugify(categories[0] || rawItem.category) || "other";
  const detailUrl = `${storeUrl}/api/v1/plugins/${encodeURIComponent(pluginId)}`;
  const manualDownloadUrl = `${storeUrl}/api/v1/plugins/${encodeURIComponent(pluginId)}/manual-download`;
  const policy = classifyMarketplaceRow(
    {
      ...rawItem,
      id: pluginId,
      plugin_id: pluginId,
      display_name:
        safeString(rawItem.display_name || rawItem.name || hostedManifest.display_name || hostedManifest.name).trim() || pluginId,
      description: safeString(rawItem.description || hostedManifest.description).trim(),
      subtitle: safeString(rawItem.subtitle || hostedManifest.subtitle).trim(),
      tags,
      categories,
      capabilities: stringList(rawItem.capabilities || hostedManifest.capabilities),
      source: hosted ? "website/hosted-plugin-store" : "website/catalog",
    },
    { installableCandidate: Boolean(hosted), installableReason: "hosted_bundle_present" },
  );
  const installable = policy.availability === "installable" && Boolean(hosted);

  return {
    id: pluginId,
    plugin_id: pluginId,
    name: safeString(rawItem.name || rawItem.display_name || hostedManifest.name || hostedManifest.display_name).trim() || pluginId,
    display_name:
      safeString(rawItem.display_name || rawItem.name || hostedManifest.display_name || hostedManifest.name).trim() || pluginId,
    version,
    subtitle: safeString(rawItem.subtitle || hostedManifest.subtitle).trim(),
    description: safeString(rawItem.description || hostedManifest.description).trim(),
    category,
    category_label: slugLabel(category),
    categories,
    tags,
    requires: stringList(rawItem.requires || hostedManifest.requires),
    target,
    mode,
    mode_id: safeString(rawItem.mode_id || rawItem.mode || hostedManifest.mode_id).trim(),
    marketplace_type: marketplaceType,
    marketplace_type_label: TYPE_LABELS[marketplaceType] || "Plugin",
    left_nav_behavior: leftNavBehavior,
    default_nav_section: defaultNavSection,
    default_nav_order: safeInt(rawItem.default_nav_order || hostedManifest.default_nav_order, marketplaceType === "app" ? 400 : 900),
    entrypoint: safeString(rawItem.entrypoint || hostedManifest.entrypoint).trim() || "hooks.py",
    capabilities: stringList(rawItem.capabilities || hostedManifest.capabilities),
    kind: safeString(rawItem.kind || hostedManifest.kind).trim() || (hosted ? "desktop_plugin" : "extension_pack"),
    source: hosted ? "website/hosted-plugin-store" : "website/catalog",
    publisher_id: safeString(hostedManifest.publisher_id).trim() || "thomas-official",
    publisher_name: safeString(hostedManifest.publisher_name).trim() || "Thomas",
    icon: safeString(hostedManifest.icon).trim() || "ph-puzzle-piece",
    api_namespace: safeString(hostedManifest.api_namespace).trim() || pluginId,
    download_available: installable,
    installable,
    availability: policy.availability,
    eligibility_reason: policy.eligibility_reason,
    promotion_status: policy.promotion_status,
    shipped_surface: policy.shipped_surface,
    needs_review: policy.needs_review,
    installed: false,
    enabled: false,
    workspace_id: leftNavBehavior === "workspace" ? safeString(rawItem.mode_id || hostedManifest.mode_id).trim() : "",
    download_url: installable ? manualDownloadUrl : "",
    manual_download_url: installable ? manualDownloadUrl : "",
    detail_url: installable ? detailUrl : "",
    open_in_thomas_url: installable ? buildOpenInThomasUrl(pluginId, storeUrl, channel) : "",
    store_url: storeUrl,
    channel,
    surface: {
      entry_html: safeString((hostedManifest.surface as JsonRecord | undefined)?.entry_html).trim(),
      title: safeString((hostedManifest.surface as JsonRecord | undefined)?.title).trim() || safeString(rawItem.name || hostedManifest.display_name).trim() || pluginId,
      surface_mode: safeString((hostedManifest.surface as JsonRecord | undefined)?.surface_mode).trim() || "immersive",
    },
  };
}

export function buildMarketplaceCatalog(channel = "stable"): MarketplaceCatalogPayload {
  const packs = Array.isArray(marketplaceSnapshot.packs) ? marketplaceSnapshot.packs : [];
  const hosted = loadHostedPlugins();
  const storeUrl = catalogStoreUrl();
  const seen = new Set<string>();
  const rows: MarketplaceCatalogRow[] = [];

  for (const item of packs) {
    if (!item || typeof item !== "object") continue;
    const pluginId = safeString((item as JsonRecord).id).trim();
    const row = normalizeCatalogRow(item as JsonRecord, {
      hosted: pluginId ? hosted.get(pluginId) || null : null,
      storeUrl,
      channel,
    });
    if (!row || !marketplaceRowIsVisible(row, { includeCatalogOnly: true, includeScaffold: false })) continue;
    seen.add(row.id);
    rows.push(row);
  }

  for (const [pluginId, plugin] of hosted.entries()) {
    if (seen.has(pluginId)) continue;
    const row = normalizeCatalogRow(plugin.manifest, { hosted: plugin, storeUrl, channel });
    if (!row || !marketplaceRowIsVisible(row, { includeCatalogOnly: true, includeScaffold: false })) continue;
    rows.push(row);
  }

  rows.sort((left, right) => {
    const installWeight = Number(Boolean(right.installable)) - Number(Boolean(left.installable));
    if (installWeight) return installWeight;
    const typeWeight =
      ["app", "plugin", "integration", "dependency"].indexOf(left.marketplace_type) -
      ["app", "plugin", "integration", "dependency"].indexOf(right.marketplace_type);
    if (typeWeight) return typeWeight;
    return left.display_name.localeCompare(right.display_name);
  });

  const categoryCounts = new Map<string, number>();
  const typeCounts = new Map<string, number>();
  for (const row of rows) {
    categoryCounts.set(row.category, (categoryCounts.get(row.category) || 0) + 1);
    typeCounts.set(row.marketplace_type, (typeCounts.get(row.marketplace_type) || 0) + 1);
  }

  return {
    ok: true,
    generated_at: safeString(marketplaceSnapshot.generatedAt).trim() || new Date().toISOString(),
    catalog_source: safeString(marketplaceSnapshot.catalogSource).trim() || "extensions/catalog.json",
    store_url: storeUrl,
    channel,
    count: rows.length,
    total: rows.length,
    categories: Array.from(categoryCounts.entries())
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .map(([id, count]) => ({ id, label: slugLabel(id), count })),
    types: Array.from(typeCounts.entries())
      .sort((left, right) => left[0].localeCompare(right[0]))
      .map(([id, count]) => ({ id, label: TYPE_LABELS[id] || slugLabel(id), count })),
    plugins: rows,
  };
}

export function getMarketplaceCatalogPlugin(pluginId: string, channel = "stable"): MarketplaceCatalogRow | null {
  const catalog = buildMarketplaceCatalog(channel);
  return catalog.plugins.find((plugin) => plugin.id === pluginId) || null;
}

export function getMarketplaceInstallablePlugin(pluginId: string, channel = "stable"): MarketplaceCatalogRow | null {
  const plugin = getMarketplaceCatalogPlugin(pluginId, channel);
  if (!plugin || !plugin.installable) {
    return null;
  }
  return plugin;
}

export function getHostedPlugin(pluginId: string): HostedPluginRecord | null {
  return loadHostedPlugins().get(pluginId) || null;
}
