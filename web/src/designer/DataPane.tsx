/** Adapted tables. Each field can be dragged onto a well. */

import { useDraggable } from "@dnd-kit/core";

import type { DesignerField, DesignerTable } from "./model";

export function DataPane({ tables }: { tables: DesignerTable[] }) {
  return (
    <div>
      {tables.map((table) => (
        <section key={table.name}>
          <p className="pane-title">{table.name}</p>
          {table.fields.map((field) => (
            <FieldChip key={`${field.kind}:${field.name}`} field={field} />
          ))}
        </section>
      ))}
    </div>
  );
}

function FieldChip({ field }: { field: DesignerField }) {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: `field:${field.table}:${field.kind}:${field.name}`,
    data: { field },
  });
  return (
    <button ref={setNodeRef} type="button" className="field" {...listeners} {...attributes}>
      {field.name}
    </button>
  );
}
