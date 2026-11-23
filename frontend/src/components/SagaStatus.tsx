import { SAGA_STATUS } from "../format";
import type { SagaStatus } from "../types";

export function SagaStatusLabel({ status }: { status: SagaStatus }) {
  const s = SAGA_STATUS[status] ?? { label: status, tone: "run" };
  return (
    <span className={`status tone-${s.tone}`}>
      <span className="status-dot" aria-hidden="true" />
      {s.label}
    </span>
  );
}
