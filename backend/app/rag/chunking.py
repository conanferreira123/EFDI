"""Structure-Aware Chunking for EFDI documents.

Consumes canonical OCRResult.full_text and preserves:
- Page boundaries (=== PAGE {n} ===)
- Section boundaries (HEADER & METADATA, PARTIES, LINE ITEMS, TOTALS & SUMMARY, TERMS)
- Markdown table structures and headers
- Line-item tables (<=15 rows intact; >15 rows in sliding windows repeating the header)
- Chunk-level JSON metadata without any ExtractionResult dependency.
"""
from dataclasses import dataclass, field
import re
from typing import Any, List, Optional


@dataclass
class ChunkData:
    chunk_index: int
    page_number: int
    chunk_type: str  # HEADER, PARTIES, LINE_ITEMS, SUMMARY, TERMS
    content: str
    metadata_json: dict[str, Any] = field(default_factory=dict)
    section: Optional[str] = None


_cached_hybrid_chunker = None


def get_hybrid_chunker():
    global _cached_hybrid_chunker
    if _cached_hybrid_chunker is None:
        from docling.chunking import HybridChunker
        _cached_hybrid_chunker = HybridChunker(
            tokenizer="sentence-transformers/all-MiniLM-L6-v2",
            max_tokens=512,
            merge_peers=True,
        )
    return _cached_hybrid_chunker


class DoclingNativeChunker:
    """Chunks native DoclingDocument using Docling's HybridChunker.

    Consumes native DoclingDocument directly, utilizing TableFormer structure,
    cell-matching, and sentence-transformers tokenizer windowing to produce
    semantically contextualized chunks.
    """

    def chunk_document(self, dl_doc: Any) -> List[ChunkData]:
        from docling_core.types.doc.labels import DocItemLabel

        chunker = get_hybrid_chunker()
        doc_chunks = list(chunker.chunk(dl_doc))
        result: List[ChunkData] = []

        for idx, c in enumerate(doc_chunks):
            content = chunker.serialize(c).strip()
            if not content:
                continue

            meta = getattr(c, "meta", None)
            headings = getattr(meta, "headings", []) if meta else []
            doc_items = getattr(meta, "doc_items", []) if meta else []

            page_number = 1
            if doc_items and hasattr(doc_items[0], "prov") and doc_items[0].prov:
                page_number = getattr(doc_items[0].prov[0], "page_no", 1)

            chunk_type = "OTHER"
            section = "OTHER"
            headings_upper = [h.upper() for h in headings] if headings else []
            has_table = any(
                getattr(item, "label", None) == DocItemLabel.TABLE
                or "table" in str(getattr(item, "label", "")).lower()
                for item in doc_items
            )

            if any("ITEM" in h for h in headings_upper) or (has_table and not any("SUMMARY" in h or "TOTAL" in h for h in headings_upper)):
                chunk_type = "LINE_ITEMS"
                section = "LINE_ITEMS"
            elif any("SUMMARY" in h or "TOTAL" in h for h in headings_upper) or (has_table and any("SUMMARY" in h or "TOTAL" in h for h in headings_upper)):
                chunk_type = "SUMMARY"
                section = "TOTALS"
            elif any("TERM" in h or "CONDITION" in h or "PAYMENT" in h for h in headings_upper):
                chunk_type = "TERMS"
                section = "PAYMENT"
            elif any("SELLER" in h or "CLIENT" in h or "BILL TO" in h or "BUYER" in h for h in headings_upper):
                chunk_type = "PARTIES"
                section = "SELLER"
            elif any("HEADER" in h or "INVOICE" in h for h in headings_upper):
                chunk_type = "HEADER"
                section = "HEADER"
            elif idx == 0:
                chunk_type = "HEADER"
                section = "HEADER"

            metadata_json = {
                "source": "docling_hybrid_chunker",
                "headings": headings,
                "doc_items_count": len(doc_items),
                "has_table": has_table,
            }

            result.append(
                ChunkData(
                    chunk_index=idx,
                    page_number=page_number,
                    chunk_type=chunk_type,
                    section=section,
                    content=content,
                    metadata_json=metadata_json,
                )
            )

        return result


class StructureAwareChunker:
    """Structure-aware chunker tailored to EFDI OCR structured output."""

    PAGE_PATTERN = re.compile(r"^=== PAGE (\d+) ===$", re.MULTILINE)
    SECTION_PATTERN = re.compile(
        r"^=== (HEADER & METADATA|PARTIES|LINE ITEMS|TOTALS & SUMMARY) ===$",
        re.MULTILINE,
    )

    SECTION_TYPE_MAP = {
        "HEADER & METADATA": "HEADER",
        "PARTIES": "PARTIES",
        "LINE ITEMS": "LINE_ITEMS",
        "TOTALS & SUMMARY": "SUMMARY",
    }

    SECTION_TO_FIRST_CLASS_MAP = {
        "HEADER & METADATA": "HEADER",
        "PARTIES": "SELLER",
        "LINE ITEMS": "LINE_ITEMS",
        "TOTALS & SUMMARY": "TOTALS",
        "TERMS & CONDITIONS": "PAYMENT",
        "PREAMBLE": "HEADER",
        "DOCUMENT_BODY": "OTHER",
    }

    def __init__(self, table_max_rows: int = 15, table_window_size: int = 10, table_window_step: int = 8):
        self.table_max_rows = table_max_rows
        self.table_window_size = table_window_size
        self.table_window_step = table_window_step

    def chunk_document(
        self, full_text: str, raw_blocks: Optional[List[dict]] = None
    ) -> List[ChunkData]:
        """Split canonical full_text into structured ChunkData items."""
        if not full_text or not full_text.strip():
            return []

        pages = self._split_by_page(full_text)
        chunks: List[ChunkData] = []
        global_chunk_index = 0

        for page_num, page_content in pages:
            page_chunks = self._chunk_page(
                page_num=page_num,
                page_content=page_content,
                start_index=global_chunk_index,
                raw_blocks=raw_blocks,
            )
            chunks.extend(page_chunks)
            global_chunk_index += len(page_chunks)

        return chunks

    def _split_by_page(self, text: str) -> List[tuple[int, str]]:
        """Split text into (page_number, text) tuples based on page markers."""
        matches = list(self.PAGE_PATTERN.finditer(text))
        if not matches:
            return [(1, text.strip())]

        pages: List[tuple[int, str]] = []
        for i, match in enumerate(matches):
            page_num = int(match.group(1))
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            page_content = text[start_pos:end_pos].strip()
            if page_content:
                pages.append((page_num, page_content))

        return pages if pages else [(1, text.strip())]

    def _chunk_page(
        self,
        page_num: int,
        page_content: str,
        start_index: int,
        raw_blocks: Optional[List[dict]] = None,
    ) -> List[ChunkData]:
        """Chunk a single page into sections using explicit markers or content-aware structure detection."""
        matches = list(self.SECTION_PATTERN.finditer(page_content))
        if matches:
            return self._chunk_page_with_markers(page_num, page_content, start_index, matches, raw_blocks)
        return self._chunk_page_content_aware(page_num, page_content, start_index, raw_blocks)

    def _chunk_page_content_aware(
        self,
        page_num: int,
        page_content: str,
        start_index: int,
        raw_blocks: Optional[List[dict]] = None,
    ) -> List[ChunkData]:
        """
        Content-aware page chunking for heading-free structured OCR text.
        Identifies Markdown table blocks (LINE_ITEMS), preceding content (HEADER),
        numerical totals (SUMMARY), and contractual clauses (TERMS).
        """
        lines = [l.strip() for l in page_content.splitlines()]
        # Filter non-empty line indices
        non_empty = [(i, l) for i, l in enumerate(lines) if l]
        if not non_empty:
            return []

        chunks: List[ChunkData] = []
        current_index = start_index

        # Find Markdown table boundary: consecutive lines starting with '|'
        table_start_idx = None
        table_end_idx = None
        for i, line in enumerate(lines):
            if line.startswith("|") and ("---" in line or "|" in line[1:]):
                if table_start_idx is None:
                    # Look back if the preceding line was a table header line (starts with |)
                    if i > 0 and lines[i - 1].startswith("|"):
                        table_start_idx = i - 1
                    else:
                        table_start_idx = i
                table_end_idx = i
            elif table_start_idx is not None and not line.startswith("|"):
                # Table ended
                break

        if table_start_idx is not None and table_end_idx is not None:
            # 1. Pre-table section: Header, metadata, and parties
            pre_table_lines = [l for l in lines[:table_start_idx] if l]
            if pre_table_lines:
                pre_content = "\n".join(pre_table_lines)
                bbox_refs = self._find_bbox_refs(pre_content, raw_blocks, page_num)
                chunks.append(
                    ChunkData(
                        chunk_index=current_index,
                        page_number=page_num,
                        chunk_type="HEADER",
                        content=pre_content,
                        metadata_json={
                            "chunk_index": current_index,
                            "section": "HEADER",
                            "page_number": page_num,
                            "has_table": False,
                            "bounding_box_refs": bbox_refs,
                            "line_range": [1, len(pre_table_lines)],
                        },
                        section="HEADER",
                    )
                )
                current_index += 1

            # 2. Table section: Line items
            table_lines_content = "\n".join(lines[table_start_idx:table_end_idx + 1])
            table_chunks = self._chunk_table_section(
                section_body=table_lines_content,
                page_num=page_num,
                start_index=current_index,
                raw_blocks=raw_blocks,
            )
            chunks.extend(table_chunks)
            current_index += len(table_chunks)

            # 3. Post-table section: Totals, summary, and terms
            post_table_lines = [l for l in lines[table_end_idx + 1:] if l]
            if post_table_lines:
                post_content = "\n".join(post_table_lines)
                post_chunks = self._chunk_summary_and_terms(
                    section_body=post_content,
                    page_num=page_num,
                    start_index=current_index,
                    raw_blocks=raw_blocks,
                )
                chunks.extend(post_chunks)
                current_index += len(post_chunks)

            return chunks

        # Non-tabular document handling:
        # Check if page contains summary or terms triggers
        summary_chunks = self._chunk_summary_and_terms(
            section_body=page_content,
            page_num=page_num,
            start_index=current_index,
            raw_blocks=raw_blocks,
        )
        if summary_chunks:
            return summary_chunks

        # Fallback for plain narrative/general documents
        content = "\n".join([l for l in lines if l])
        bbox_refs = self._find_bbox_refs(content, raw_blocks, page_num)
        chunks.append(
            ChunkData(
                chunk_index=current_index,
                page_number=page_num,
                chunk_type="TERMS",
                content=content,
                metadata_json={
                    "chunk_index": current_index,
                    "section": "DOCUMENT_BODY",
                    "page_number": page_num,
                    "has_table": False,
                    "bounding_box_refs": bbox_refs,
                    "line_range": [1, len(lines)],
                },
                section="OTHER",
            )
        )
        return chunks

    def _chunk_page_with_markers(
        self,
        page_num: int,
        page_content: str,
        start_index: int,
        matches: List[Any],
        raw_blocks: Optional[List[dict]] = None,
    ) -> List[ChunkData]:
        """Legacy chunking using explicit section markers."""
        chunks: List[ChunkData] = []
        current_index = start_index

        # Process any content before the first section marker (e.g. leading header)
        if matches[0].start() > 0:
            preamble = page_content[: matches[0].start()].strip()
            if preamble:
                preamble_lines = preamble.splitlines()
                bbox_refs = self._find_bbox_refs(preamble, raw_blocks, page_num)
                chunks.append(
                    ChunkData(
                        chunk_index=current_index,
                        page_number=page_num,
                        chunk_type="HEADER",
                        content=preamble,
                        metadata_json={
                            "chunk_index": current_index,
                            "section": "PREAMBLE",
                            "page_number": page_num,
                            "has_table": False,
                            "bounding_box_refs": bbox_refs,
                            "line_range": [1, len(preamble_lines)],
                        },
                        section="HEADER",
                    )
                )
                current_index += 1

        for i, match in enumerate(matches):
            section_name = match.group(1)
            chunk_type = self.SECTION_TYPE_MAP.get(section_name, "TERMS")
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(page_content)
            section_body = page_content[start_pos:end_pos].strip()

            if not section_body:
                continue

            if chunk_type == "LINE_ITEMS":
                table_chunks = self._chunk_table_section(
                    section_body=section_body,
                    page_num=page_num,
                    start_index=current_index,
                    raw_blocks=raw_blocks,
                )
                chunks.extend(table_chunks)
                current_index += len(table_chunks)
            elif chunk_type == "SUMMARY":
                # Totals & summary may be followed by footer notes / terms
                summary_chunks = self._chunk_summary_and_terms(
                    section_body=section_body,
                    page_num=page_num,
                    start_index=current_index,
                    raw_blocks=raw_blocks,
                )
                chunks.extend(summary_chunks)
                current_index += len(summary_chunks)
            else:
                lines = section_body.splitlines()
                bbox_refs = self._find_bbox_refs(section_body, raw_blocks, page_num)
                chunks.append(
                    ChunkData(
                        chunk_index=current_index,
                        page_number=page_num,
                        chunk_type=chunk_type,
                        content=f"=== {section_name} ===\n{section_body}",
                        metadata_json={
                            "chunk_index": current_index,
                            "section": section_name,
                            "page_number": page_num,
                            "has_table": "|" in section_body,
                            "bounding_box_refs": bbox_refs,
                            "line_range": [1, len(lines)],
                        },
                        section=self.SECTION_TO_FIRST_CLASS_MAP.get(section_name, "OTHER"),
                    )
                )
                current_index += 1

        return chunks

    def _chunk_table_section(
        self,
        section_body: str,
        page_num: int,
        start_index: int,
        raw_blocks: Optional[List[dict]],
    ) -> List[ChunkData]:
        """Handle line items table with sliding window when data rows > 15."""
        lines = [l for l in section_body.splitlines() if l.strip()]
        table_lines = [l for l in lines if l.strip().startswith("|")]
        non_table_lines = [l for l in lines if not l.strip().startswith("|")]

        chunks: List[ChunkData] = []
        current_index = start_index

        if not table_lines:
            # Fallback if no table pipe rows found
            bbox_refs = self._find_bbox_refs(section_body, raw_blocks, page_num)
            chunks.append(
                ChunkData(
                    chunk_index=current_index,
                    page_number=page_num,
                    chunk_type="LINE_ITEMS",
                    content=section_body,
                    metadata_json={
                        "chunk_index": current_index,
                        "section": "LINE ITEMS",
                        "page_number": page_num,
                        "has_table": False,
                        "bounding_box_refs": bbox_refs,
                        "line_range": [1, len(lines)],
                    },
                    section="LINE_ITEMS",
                )
            )
            return chunks

        # Extract markdown header (typically first 2 lines: header names + separator |---|)
        header_rows: List[str] = []
        data_rows: List[str] = []

        for idx, row in enumerate(table_lines):
            if idx == 0:
                header_rows.append(row)
            elif idx == 1 and ("---" in row or "===" in row):
                header_rows.append(row)
            else:
                data_rows.append(row)

        header_str = "\n".join(header_rows)

        if len(data_rows) <= self.table_max_rows:
            # Table is small enough to keep intact in a single chunk
            full_content = ""
            if non_table_lines:
                full_content += "\n".join(non_table_lines) + "\n\n"
            full_content += "\n".join(table_lines)

            bbox_refs = self._find_bbox_refs(full_content, raw_blocks, page_num)
            chunks.append(
                ChunkData(
                    chunk_index=current_index,
                    page_number=page_num,
                    chunk_type="LINE_ITEMS",
                    content=full_content,
                    metadata_json={
                        "chunk_index": current_index,
                        "section": "LINE ITEMS",
                        "page_number": page_num,
                        "has_table": True,
                        "table_rows_count": len(data_rows),
                        "bounding_box_refs": bbox_refs,
                        "line_range": [1, len(lines)],
                    },
                    section="LINE_ITEMS",
                )
            )
            return chunks

        # Table exceeds table_max_rows -- use sliding window
        window_size = self.table_window_size
        step = self.table_window_step
        total_rows = len(data_rows)
        start_row = 0
        window_num = 1

        while start_row < total_rows:
            end_row = min(start_row + window_size, total_rows)
            sliced_data = data_rows[start_row:end_row]

            window_content = ""
            if header_str:
                window_content += f"{header_str}\n"
            window_content += "\n".join(sliced_data)

            bbox_refs = self._find_bbox_refs(window_content, raw_blocks, page_num)
            chunks.append(
                ChunkData(
                    chunk_index=current_index,
                    page_number=page_num,
                    chunk_type="LINE_ITEMS",
                    content=window_content,
                    metadata_json={
                        "chunk_index": current_index,
                        "section": "LINE ITEMS",
                        "page_number": page_num,
                        "has_table": True,
                        "window_index": window_num,
                        "row_range": [start_row + 1, end_row],
                        "total_table_rows": total_rows,
                        "bounding_box_refs": bbox_refs,
                        "line_range": [start_row + 1, end_row],
                    },
                    section="LINE_ITEMS",
                )
            )
            current_index += 1
            window_num += 1

            if end_row >= total_rows:
                break
            start_row += step

        return chunks

    def _chunk_summary_and_terms(
        self,
        section_body: str,
        page_num: int,
        start_index: int,
        raw_blocks: Optional[List[dict]],
    ) -> List[ChunkData]:
        """Separate numeric totals from trailing payment terms, penalties, and delivery clauses."""
        lines = [l.strip() for l in section_body.splitlines() if l.strip()]
        chunks: List[ChunkData] = []
        current_index = start_index

        # Terms trigger keywords that typically begin footer/terms paragraphs
        terms_triggers = [
            "payment terms",
            "terms of payment",
            "discount",
            "interest penalty",
            "incoterms",
            "delivery terms",
            "dispute",
            "jurisdiction",
            "bank details",
            "remittance",
            "notice",
        ]

        totals_lines: List[str] = []
        terms_lines: List[str] = []
        in_terms = False

        for line in lines:
            line_lower = line.lower()
            if not in_terms:
                if any(trigger in line_lower for trigger in terms_triggers):
                    in_terms = True
                    terms_lines.append(line)
                else:
                    totals_lines.append(line)
            else:
                terms_lines.append(line)

        # Emit SUMMARY chunk if totals found
        if totals_lines:
            summary_text = "\n".join(totals_lines)
            bbox_refs = self._find_bbox_refs(summary_text, raw_blocks, page_num)
            chunks.append(
                ChunkData(
                    chunk_index=current_index,
                    page_number=page_num,
                    chunk_type="SUMMARY",
                    content=summary_text,
                    metadata_json={
                        "chunk_index": current_index,
                        "section": "TOTALS & SUMMARY",
                        "page_number": page_num,
                        "has_table": False,
                        "bounding_box_refs": bbox_refs,
                        "line_range": [1, len(totals_lines)],
                    },
                    section="TOTALS",
                )
            )
            current_index += 1

        # Emit TERMS chunk for trailing contractual clauses
        if terms_lines:
            terms_text = "\n".join(terms_lines)
            bbox_refs = self._find_bbox_refs(terms_text, raw_blocks, page_num)
            chunks.append(
                ChunkData(
                    chunk_index=current_index,
                    page_number=page_num,
                    chunk_type="TERMS",
                    content=terms_text,
                    metadata_json={
                        "chunk_index": current_index,
                        "section": "TERMS & CONDITIONS",
                        "page_number": page_num,
                        "has_table": False,
                        "bounding_box_refs": bbox_refs,
                        "line_range": [len(totals_lines) + 1, len(lines)],
                    },
                    section="PAYMENT",
                )
            )

        return chunks

    def _find_bbox_refs(
        self, text_content: str, raw_blocks: Optional[List[dict]], page_num: int
    ) -> List[dict]:
        """Find overlapping bounding boxes from raw_blocks for visual provenance."""
        if not raw_blocks:
            return []

        refs: List[dict] = []
        normalized_content = text_content.lower()

        for idx, block in enumerate(raw_blocks):
            block_page = block.get("page_number", block.get("page", 1))
            if block_page != page_num:
                continue

            block_text = block.get("text", "").strip()
            if not block_text or len(block_text) < 3:
                continue

            if block_text.lower() in normalized_content:
                bbox = block.get("bounding_box", block.get("bbox"))
                refs.append({
                    "block_id": idx,
                    "text": block_text,
                    "confidence": block.get("confidence", 1.0),
                    "bounding_box": bbox,
                })

            if len(refs) >= 10:  # Cap at 10 most relevant bounding boxes per chunk
                break

        return refs
