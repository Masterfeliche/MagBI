/** Download chart PNGs, a landscape PDF, and visual-data CSV/XLSX. */

export const EXPORT_ROW_WARNING = 150_000;
const PAGE_WIDTH = 792;
const PAGE_HEIGHT = 612;

export function exportReport(root: HTMLElement, name: string): number {
  const canvases = [...root.querySelectorAll("canvas")] as HTMLCanvasElement[];
  canvases.forEach((canvas, index) => {
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = `${name}-${index + 1}.png`;
    link.click();
  });
  const images = canvases.flatMap((canvas) => {
    const jpeg = jpegFromCanvas(canvas);
    return jpeg ? [jpeg] : [];
  });
  const pdf = landscapePdfFromJpegs(images);
  downloadBlob(new Uint8Array(pdf), `${name}.pdf`, "application/pdf");
  return canvases.length;
}

export function exportVisualData(
  columns: string[],
  rows: unknown[][],
  name: string,
  kind: "csv" | "xlsx",
): void {
  if (rows.length > EXPORT_ROW_WARNING) {
    window.alert("This export has more than 150,000 rows.");
  }
  if (kind === "xlsx") {
    const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
    const body = rows
      .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(String(cell ?? ""))}</td>`).join("")}</tr>`)
      .join("");
    downloadBlob(
      `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`,
      `${name}.xls`,
      "application/vnd.ms-excel",
    );
    return;
  }
  const lines = [
    columns.join(","),
    ...rows.map((row) => row.map((cell) => csvCell(cell)).join(",")),
  ];
  downloadBlob(lines.join("\n"), `${name}.csv`, "text/csv");
}

export function landscapePdfFromJpegs(
  images: Array<{ bytes: Uint8Array; width: number; height: number }>,
): Uint8Array {
  const pages = images.length === 0
    ? [{ bytes: new Uint8Array(), width: 1, height: 1, empty: true }]
    : images.map((image) => ({ ...image, empty: false }));
  const parts: Uint8Array[] = [];
  const offsets: number[] = [0];
  let pos = 0;
  function add(data: Uint8Array | string) {
    const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
    parts.push(bytes);
    pos += bytes.length;
  }
  add("%PDF-1.4\n");
  offsets[1] = pos;
  add("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");
  offsets[2] = pos;
  const kids = pages.map((_, index) => `${3 + index * 3} 0 R`).join(" ");
  add(`2 0 obj\n<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>\nendobj\n`);
  pages.forEach((image, index) => {
    const pageObj = 3 + index * 3;
    const contentObj = pageObj + 1;
    const imageObj = pageObj + 2;
    const scale = Math.min(PAGE_WIDTH / image.width, PAGE_HEIGHT / image.height);
    const width = image.width * scale;
    const height = image.height * scale;
    const x = (PAGE_WIDTH - width) / 2;
    const y = (PAGE_HEIGHT - height) / 2;
    const content = image.empty
      ? ""
      : `q ${width.toFixed(2)} 0 0 ${height.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)} cm /Im${index} Do Q`;
    const resources = image.empty ? "" : `/Resources << /XObject << /Im${index} ${imageObj} 0 R >> >>`;
    offsets[pageObj] = pos;
    add(`${pageObj} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_WIDTH} ${PAGE_HEIGHT}] /Contents ${contentObj} 0 R ${resources} >>\nendobj\n`);
    offsets[contentObj] = pos;
    add(`${contentObj} 0 obj\n<< /Length ${content.length} >>\nstream\n${content}\nendstream\nendobj\n`);
    offsets[imageObj] = pos;
    if (image.empty) {
      add(`${imageObj} 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 0 >>\nstream\nendstream\nendobj\n`);
      return;
    }
    add(`${imageObj} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${image.width} /Height ${image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${image.bytes.length} >>\nstream\n`);
    add(image.bytes);
    add("\nendstream\nendobj\n");
  });
  const xrefPos = pos;
  const maxObj = 2 + pages.length * 3;
  let xref = `xref\n0 ${maxObj + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= maxObj; i += 1) {
    xref += `${String(offsets[i] ?? 0).padStart(10, "0")} 00000 n \n`;
  }
  add(xref);
  add(`trailer\n<< /Size ${maxObj + 1} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`);
  const out = new Uint8Array(pos);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function jpegFromCanvas(canvas: HTMLCanvasElement): { bytes: Uint8Array; width: number; height: number } | null {
  if (canvas.width === 0 || canvas.height === 0) return null;
  const url = canvas.toDataURL("image/jpeg", 0.85);
  const comma = url.indexOf(",");
  if (comma < 0) return null;
  const binary = atob(url.slice(comma + 1));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return { bytes, width: canvas.width, height: canvas.height };
}

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function downloadBlob(content: string | Uint8Array, filename: string, type: string): void {
  const blob = new Blob([content as BlobPart], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
