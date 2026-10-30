/** Download each chart canvas as a PNG, then open a printable page for PDF. */

export function exportReport(root: HTMLElement, name: string): number {
  const canvases = [...root.querySelectorAll("canvas")] as HTMLCanvasElement[];
  canvases.forEach((canvas, index) => {
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = `${name}-${index + 1}.png`;
    link.click();
  });
  if (canvases.length === 0) return 0;
  const page = window.open("", "_blank");
  if (!page) return canvases.length;
  const images = canvases.map((canvas) => `<img src="${canvas.toDataURL("image/png")}" style="max-width:100%;margin:12px 0" />`).join("");
  page.document.write(`<title>${name}</title><body>${images}<script>window.print()<\/script></body>`);
  page.document.close();
  return canvases.length;
}
