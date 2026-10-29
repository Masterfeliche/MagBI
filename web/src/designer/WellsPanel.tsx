/** Y-axis, X-axis, Legend, and the other wells for the selected visual. */

import { useDroppable } from "@dnd-kit/core";

import type { FieldBinding } from "../types/report";
import type { WellSpec } from "./catalog";

export function WellsPanel({
  wells,
  bindings,
  onRemove,
}: {
  wells: WellSpec[];
  bindings: Record<string, FieldBinding[]>;
  onRemove: (wellName: string, index: number) => void;
}) {
  if (wells.length === 0) return <p className="hint">Select a visual.</p>;
  return (
    <div>
      {wells.map((well) => (
        <WellBucket
          key={well.name}
          well={well}
          bindings={bindings[well.name] ?? []}
          onRemove={(index) => onRemove(well.name, index)}
        />
      ))}
    </div>
  );
}

function WellBucket({
  well,
  bindings,
  onRemove,
}: {
  well: WellSpec;
  bindings: FieldBinding[];
  onRemove: (index: number) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `well:${well.name}`, data: { well: well.name } });
  return (
    <div ref={setNodeRef} className={isOver ? "well over" : "well"}>
      <div>{well.displayName}</div>
      {bindings.map((binding, index) => (
        <div key={`${binding.table}:${binding.column ?? binding.measure}:${index}`}>
          {binding.measure ?? binding.column}
          {binding.aggregation ? ` (${binding.aggregation})` : ""}
          <button type="button" onClick={() => onRemove(index)}>
            Remove
          </button>
        </div>
      ))}
    </div>
  );
}
