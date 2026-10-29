/** Y-axis, X-axis, Legend, and the other wells for the selected visual. */

import { useDroppable } from "@dnd-kit/core";

import type { FieldBinding } from "../types/report";
import type { WellSpec } from "./catalog";

export function WellsPanel({
  wells,
  bindings,
}: {
  wells: WellSpec[];
  bindings: Record<string, FieldBinding[]>;
}) {
  if (wells.length === 0) return <p className="hint">Select a visual.</p>;
  return (
    <div>
      {wells.map((well) => (
        <WellBucket key={well.name} well={well} bindings={bindings[well.name] ?? []} />
      ))}
    </div>
  );
}

function WellBucket({ well, bindings }: { well: WellSpec; bindings: FieldBinding[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: `well:${well.name}`, data: { well: well.name } });
  return (
    <div ref={setNodeRef} className={isOver ? "well over" : "well"}>
      <div>{well.displayName}</div>
      {bindings.map((binding, index) => (
        <div key={`${binding.table}:${binding.column ?? binding.measure}:${index}`}>
          {binding.measure ?? binding.column}
          {binding.aggregation ? ` (${binding.aggregation})` : ""}
        </div>
      ))}
    </div>
  );
}
