import type { ReactNode } from "react";

export type StatusType = "implemented" | "partial" | "planned";

type StatusChipProps = {
  status: StatusType;
  label?: string;
  className?: string;
};

const statusLabel: Record<StatusType, string> = {
  implemented: "Implemented",
  partial: "Partial",
  planned: "Declared",
};

export function StatusChip({ status, label, className }: StatusChipProps) {
  return (
    <span className={`status-chip status-chip-${status} ${className ?? ""}`.trim()} role="status">
      {label ?? statusLabel[status]}
    </span>
  );
}
