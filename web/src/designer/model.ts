/** Read the API's snake_case dataset definition into the designer's field list. */

export interface DesignerField {
  table: string;
  name: string;
  kind: "column" | "measure";
  dataType: string;
}

export interface DesignerTable {
  name: string;
  fields: DesignerField[];
}

interface ApiColumn {
  name?: string;
  data_type?: string;
}

interface ApiMeasure {
  name?: string;
}

interface ApiTable {
  name?: string;
  columns?: ApiColumn[];
  measures?: ApiMeasure[];
}

export function adaptDataset(definition: unknown): DesignerTable[] {
  const tables = readTables(definition);
  return tables.flatMap((table) => {
    const name = text(table.name);
    if (!name) return [];
    const fields: DesignerField[] = [];
    for (const column of table.columns ?? []) {
      const columnName = text(column.name);
      if (!columnName) continue;
      fields.push({
        table: name,
        name: columnName,
        kind: "column",
        dataType: text(column.data_type) || "string",
      });
    }
    for (const measure of table.measures ?? []) {
      const measureName = text(measure.name);
      if (!measureName) continue;
      fields.push({
        table: name,
        name: measureName,
        kind: "measure",
        dataType: "decimal",
      });
    }
    return [{ name, fields }];
  });
}

export function isNumeric(dataType: string): boolean {
  return dataType === "integer" || dataType === "decimal";
}

function readTables(definition: unknown): ApiTable[] {
  if (!definition || typeof definition !== "object") return [];
  const tables = (definition as { tables?: unknown }).tables;
  if (!Array.isArray(tables)) return [];
  return tables.filter((table): table is ApiTable => !!table && typeof table === "object");
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
