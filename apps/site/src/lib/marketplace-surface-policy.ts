import fs from "node:fs";
import path from "node:path";

type JsonRecord = Record<string, unknown>;

export type MarketplaceSurfacePolicy = {
  schema_version: number;
  strict_proxy_families: string[];
  hidden_ids: string[];
  hidden_prefixes: string[];
  hidden_terms: string[];
  scaffold_ids: string[];
  scaffold_prefixes: string[];
  scaffold_tags: string[];
  scaffold_terms: string[];
};

export type MarketplaceAvailability = "installable" | "catalog_only" | "scaffold" | "hidden";

const DEFAULT_POLICY: MarketplaceSurfacePolicy = {
  schema_version: 1,
  strict_proxy_families: [
    "browser",
    "gateway",
    "channel",
    "channels",
    "message",
    "messages",
    "plugin",
    "plugins",
    "openai",
    "responses",
    "mission",
    "missions",
  ],
  hidden_ids: [],
  hidden_prefixes: [],
  hidden_terms: [],
  scaffold_ids: [],
  scaffold_prefixes: [],
  scaffold_tags: ["scaffold", "placeholder", "proxy", "noop"],
  scaffold_terms: ["placeholder", "proxy/noop", "proxy noop", "not implemented", "stub"],
};

function safeString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const text = safeString(item).trim().toLowerCase();
    if (text && !out.includes(text)) {
      out.push(text);
    }
  }
  return out;
}

function repoRoot(): string {
  const envRoot = safeString(process.env.THOMAS_REPO_ROOT).trim();
  if (envRoot) {
    return path.resolve(envRoot);
  }
  const cwd = process.cwd();
  const candidates = [cwd, path.resolve(cwd, ".."), path.resolve(cwd, "../..")];
  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "definitions", "marketplace-surface-policy.json"))) {
      return candidate;
    }
  }
  return path.resolve(cwd, "../..");
}

function policyPath(): string {
  const explicit = safeString(process.env.THOMAS_MARKETPLACE_POLICY_PATH).trim();
  if (explicit) {
    return path.resolve(explicit);
  }
  return path.join(repoRoot(), "definitions", "marketplace-surface-policy.json");
}

export function loadMarketplaceSurfacePolicy(): MarketplaceSurfacePolicy {
  const out: MarketplaceSurfacePolicy = { ...DEFAULT_POLICY };
  const filePath = policyPath();
  if (!fs.existsSync(filePath)) {
    return out;
  }
  try {
    const payload = JSON.parse(fs.readFileSync(filePath, "utf-8")) as JsonRecord;
    out.schema_version = Number.parseInt(safeString(payload.schema_version), 10) || 1;
    out.strict_proxy_families = stringList(payload.strict_proxy_families);
    out.hidden_ids = stringList(payload.hidden_ids);
    out.hidden_prefixes = stringList(payload.hidden_prefixes);
    out.hidden_terms = stringList(payload.hidden_terms);
    out.scaffold_ids = stringList(payload.scaffold_ids);
    out.scaffold_prefixes = stringList(payload.scaffold_prefixes);
    out.scaffold_tags = stringList(payload.scaffold_tags);
    out.scaffold_terms = stringList(payload.scaffold_terms);
  } catch {
    return out;
  }
  return out;
}

function rowText(row: JsonRecord): string {
  return [
    safeString(row.id || row.plugin_id).trim().toLowerCase(),
    safeString(row.name).trim().toLowerCase(),
    safeString(row.display_name).trim().toLowerCase(),
    safeString(row.subtitle).trim().toLowerCase(),
    safeString(row.description).trim().toLowerCase(),
    safeString(row.source).trim().toLowerCase(),
    ...stringList(row.tags),
    ...stringList(row.categories),
    ...stringList(row.capabilities),
  ]
    .filter(Boolean)
    .join(" ");
}

function matchesExactOrPrefix(value: string, exact: string[], prefixes: string[]) {
  if (exact.includes(value)) return true;
  return prefixes.some((prefix) => prefix && value.startsWith(prefix));
}

export function classifyMarketplaceRow(
  row: JsonRecord,
  options: {
    installableCandidate: boolean;
    installableReason?: string;
  },
): {
  availability: MarketplaceAvailability;
  eligibility_reason: string;
  promotion_status: "official_hosted" | "inventory_only" | "blocked" | "suppressed";
  shipped_surface: boolean;
  needs_review: boolean;
} {
  const policy = loadMarketplaceSurfacePolicy();
  const pluginId = safeString(row.id || row.plugin_id).trim().toLowerCase();
  const text = rowText(row);
  const tags = new Set(stringList(row.tags));
  const explicitAvailability = safeString(row.availability).trim().toLowerCase();

  if (
    explicitAvailability === "hidden" ||
    matchesExactOrPrefix(pluginId, policy.hidden_ids, policy.hidden_prefixes) ||
    policy.hidden_terms.some((term) => term && text.includes(term))
  ) {
    return {
      availability: "hidden",
      eligibility_reason: "suppressed_by_policy",
      promotion_status: "suppressed",
      shipped_surface: false,
      needs_review: false,
    };
  }

  const scaffoldTerm = policy.scaffold_terms.find((term) => term && text.includes(term)) || "";
  if (
    explicitAvailability === "scaffold" ||
    matchesExactOrPrefix(pluginId, policy.scaffold_ids, policy.scaffold_prefixes) ||
    policy.scaffold_tags.some((tag) => tags.has(tag)) ||
    Boolean(scaffoldTerm)
  ) {
    return {
      availability: "scaffold",
      eligibility_reason: scaffoldTerm.includes("proxy") || scaffoldTerm.includes("noop") ? "proxy_noop" : "placeholder_surface",
      promotion_status: "blocked",
      shipped_surface: false,
      needs_review: true,
    };
  }

  if (explicitAvailability === "catalog_only" && !options.installableCandidate) {
    return {
      availability: "catalog_only",
      eligibility_reason: "missing_hosted_bundle",
      promotion_status: "inventory_only",
      shipped_surface: false,
      needs_review: false,
    };
  }

  if (options.installableCandidate) {
    return {
      availability: "installable",
      eligibility_reason: options.installableReason || "hosted_bundle_present",
      promotion_status: "official_hosted",
      shipped_surface: true,
      needs_review: false,
    };
  }

  return {
    availability: "catalog_only",
    eligibility_reason: "missing_hosted_bundle",
    promotion_status: "inventory_only",
    shipped_surface: false,
    needs_review: false,
  };
}

export function marketplaceRowIsVisible(
  row: { availability?: string },
  options: {
    includeCatalogOnly?: boolean;
    includeScaffold?: boolean;
    includeHidden?: boolean;
  } = {},
) {
  const availability = safeString(row.availability).trim().toLowerCase();
  if (availability === "hidden") return Boolean(options.includeHidden);
  if (availability === "scaffold") return Boolean(options.includeScaffold);
  if (availability === "catalog_only") return options.includeCatalogOnly !== false;
  return true;
}
