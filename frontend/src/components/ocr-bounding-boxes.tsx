import { useState } from "react";
import type { OCRPageBlocks } from "@/types/api";
import { formatConfidence } from "@/lib/format";

/**
 * Schematic page-layout visualization, not a true image overlay -- the
 * backend stores bounding boxes (app/models/ocr_result.py's raw_blocks)
 * but doesn't serve a rendered page preview image, only the original
 * uploaded file. Rather than overstate what's available (e.g. faking an
 * overlay against a placeholder image), this draws the page as a plain
 * outlined rectangle at the correct aspect ratio and positions each
 * text block proportionally within it, using page_width/page_height to
 * scale real pixel coordinates down to the SVG's viewBox.
 */
export function OCRBoundingBoxes({ pages }: { pages: OCRPageBlocks[] }) {
  const [activePage, setActivePage] = useState(0);
  const [hoveredBlock, setHoveredBlock] = useState<number | null>(null);

  if (pages.length === 0) {
    return <p className="text-sm text-ink-400">No block-level detections recorded for this run.</p>;
  }

  const page = pages[activePage];
  const viewBoxWidth = 600;
  const viewBoxHeight = (page.page_height / page.page_width) * viewBoxWidth;
  const scale = viewBoxWidth / page.page_width;

  return (
    <div className="space-y-3">
      {pages.length > 1 && (
        <div className="flex gap-1">
          {pages.map((p, i) => (
            <button
              key={p.page_number}
              onClick={() => setActivePage(i)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                i === activePage ? "bg-ink-900 text-paper-50" : "bg-ink-100 text-ink-600 hover:bg-ink-200"
              }`}
            >
              Page {p.page_number}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-4">
        <svg
          viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`}
          className="rounded-md border border-ink-200 bg-white"
          style={{ width: 280, height: 280 * (viewBoxHeight / viewBoxWidth) }}
        >
          {page.blocks.map((block, i) => {
            const xs = block.bounding_box.map((p) => p[0] * scale);
            const ys = block.bounding_box.map((p) => p[1] * scale);
            const x = Math.min(...xs);
            const y = Math.min(...ys);
            const w = Math.max(...xs) - x;
            const h = Math.max(...ys) - y;
            const isHovered = hoveredBlock === i;
            return (
              <rect
                key={i}
                x={x}
                y={y}
                width={w}
                height={h}
                fill={isHovered ? "var(--color-seal-100)" : "transparent"}
                stroke={isHovered ? "var(--color-seal-500)" : "var(--color-ink-300)"}
                strokeWidth={isHovered ? 2 : 1}
                onMouseEnter={() => setHoveredBlock(i)}
                onMouseLeave={() => setHoveredBlock(null)}
                className="cursor-pointer transition-colors"
              />
            );
          })}
        </svg>

        <div className="flex-1 space-y-1.5 overflow-y-auto" style={{ maxHeight: 280 }}>
          {page.blocks.map((block, i) => (
            <div
              key={i}
              onMouseEnter={() => setHoveredBlock(i)}
              onMouseLeave={() => setHoveredBlock(null)}
              className={`cursor-default rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                hoveredBlock === i ? "bg-seal-50" : "hover:bg-ink-50"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-data truncate text-ink-700">{block.text}</span>
                <span className="font-data shrink-0 text-ink-400">
                  {formatConfidence(block.confidence)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-ink-400">
        Schematic layout, not a rendered page image -- positions are scaled from the stored
        bounding-box coordinates ({page.page_width}×{page.page_height}px).
      </p>
    </div>
  );
}
