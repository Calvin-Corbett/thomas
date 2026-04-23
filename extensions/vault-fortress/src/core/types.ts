import { z } from "zod";

export const Scope = z.enum(["profile","api","logins","legal","medical","billing","misc"]);
export type Scope = z.infer<typeof Scope>;

export const Sensitivity = z.enum(["low","high","critical"]);
export type Sensitivity = z.infer<typeof Sensitivity>;

export const SecretRefSchema = z.string().regex(/^vault:\/\/[a-z0-9_-]+\/[a-z0-9_.-]+$/i, "Invalid vault ref");
export type SecretRef = z.infer<typeof SecretRefSchema>;

export const ToolIdSchema = z.string().regex(/^[a-z0-9_.-]{2,64}$/i, "Invalid toolId");
export type ToolId = z.infer<typeof ToolIdSchema>;

export const PurposeSchema = z.string().min(3).max(500);
export type Purpose = z.infer<typeof PurposeSchema>;

export const VaultMetaSchema = z.object({
  ref: SecretRefSchema,
  scope: Scope,
  sensitivity: Sensitivity,
  label: z.string().min(1).max(200),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type VaultMeta = z.infer<typeof VaultMetaSchema>;
