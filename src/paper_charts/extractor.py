"""Caption-guided figure detection and cropping for scholarly PDFs.

This is a heuristic extractor: it associates caption blocks with nearby PDF
image/vector elements. It intentionally records confidence and source geometry
so a later review step can catch imperfect crops.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import fitz

CAPTION_PATTERN = re.compile(
    r"^\s*(?:figure|fig\.?|figura|figs\.?)\s*"
    r"(?P<number>(?:s)?\d+[a-z]?(?:\.\d+)?)\b[.:\s–—-]*(?P<caption>.*)$",
    re.IGNORECASE | re.DOTALL,
)
MANIFEST_FIELDS = [
    "figure_id",
    "page",
    "figure_number",
    "caption",
    "image_path",
    "confidence",
    "bbox_x0_pt",
    "bbox_y0_pt",
    "bbox_x1_pt",
    "bbox_y1_pt",
]


@dataclass
class Caption:
    number: str
    text: str
    rect: fitz.Rect


@dataclass
class Graphic:
    rect: fitz.Rect


def _text_blocks(page: fitz.Page) -> List[Tuple[str, fitz.Rect]]:
    blocks: List[Tuple[str, fitz.Rect]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        text = "\n".join(
            "".join(span.get("text", "") for span in line.get("spans", []))
            for line in block.get("lines", [])
        ).strip()
        if text:
            blocks.append((text, fitz.Rect(block["bbox"])))
    return blocks


def _captions(blocks: Sequence[Tuple[str, fitz.Rect]]) -> List[Caption]:
    found: List[Caption] = []
    for text, rect in blocks:
        match = CAPTION_PATTERN.match(text)
        if match:
            found.append(
                Caption(
                    number=match.group("number"),
                    text=" ".join(match.group("caption").split()),
                    rect=rect,
                )
            )
    return found


def _visual_elements(page: fitz.Page) -> List[Graphic]:
    elements: List[Graphic] = []
    page_area = max(_area(page.rect), 1)

    # Image blocks include raster charts embedded in the PDF.
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") == 1 and "bbox" in block:
            rect = fitz.Rect(block["bbox"])
            if _area(rect) > 4 and _area(rect) < page_area * 0.8:
                elements.append(Graphic(rect))

    # Vector plots are composed of PDF drawing paths rather than image blocks.
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        if rect.is_empty:
            continue
        if _area(rect) > page_area * 0.8:
            continue
        # Ignore tiny isolated marks such as bullets and punctuation.
        if rect.width < 1.5 and rect.height < 1.5:
            continue
        elements.append(Graphic(rect))
    return elements


def _area(rect: fitz.Rect) -> float:
    """Return rectangle area without relying on newer PyMuPDF Rect methods."""
    return max(0.0, rect.width) * max(0.0, rect.height)


def _rect_gap(a: fitz.Rect, b: fitz.Rect) -> float:
    dx = max(a.x0 - b.x1, b.x0 - a.x1, 0)
    dy = max(a.y0 - b.y1, b.y0 - a.y1, 0)
    return (dx * dx + dy * dy) ** 0.5


def _components(elements: Sequence[Graphic], join_distance: float = 18) -> List[fitz.Rect]:
    """Merge nearby vector/image elements into candidate figure regions."""
    if not elements:
        return []
    parent = list(range(len(elements)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    ordered = sorted(range(len(elements)), key=lambda i: elements[i].rect.y0)
    for position, first in enumerate(ordered):
        first_rect = elements[first].rect
        for second in ordered[position + 1 :]:
            second_rect = elements[second].rect
            if second_rect.y0 - first_rect.y1 > join_distance:
                break
            if _rect_gap(first_rect, second_rect) <= join_distance:
                first_root, second_root = root(first), root(second)
                if first_root != second_root:
                    parent[second_root] = first_root

    groups: Dict[int, fitz.Rect] = {}
    for index, element in enumerate(elements):
        group = root(index)
        if group in groups:
            groups[group] |= element.rect
        else:
            groups[group] = fitz.Rect(element.rect)
    return list(groups.values())


def _horizontal_overlap(a: fitz.Rect, b: fitz.Rect) -> float:
    shared = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    denominator = max(min(a.width, b.width), 1.0)
    return shared / denominator


def _caption_gap(graphic: fitz.Rect, caption: fitz.Rect) -> float:
    if graphic.y1 <= caption.y0:
        return caption.y0 - graphic.y1
    if caption.y1 <= graphic.y0:
        return graphic.y0 - caption.y1
    return 0.0


def _pick_graphic(caption: Caption, candidates: Sequence[fitz.Rect]) -> Optional[Tuple[fitz.Rect, str]]:
    scored: List[Tuple[float, fitz.Rect, float, float]] = []
    for candidate in candidates:
        gap = _caption_gap(candidate, caption.rect)
        overlap = _horizontal_overlap(candidate, caption.rect)
        # Captions normally sit next to the figure, and within the same column.
        if gap > 140 or (overlap < 0.12 and gap > 48):
            continue
        score = gap + (1 - overlap) * 45
        scored.append((score, candidate, gap, overlap))
    if not scored:
        return None
    _, selected, gap, overlap = min(scored, key=lambda item: item[0])
    confidence = "high" if gap <= 32 and overlap >= 0.45 else "medium"
    if gap > 76 or overlap < 0.2:
        confidence = "low"
    return selected, confidence


def _include_nearby_labels(rect: fitz.Rect, blocks: Sequence[Tuple[str, fitz.Rect]]) -> fitz.Rect:
    # Axis titles and tick labels are text, not drawing paths. Include text close
    # to the visual region while avoiding surrounding paragraph text.
    label_zone = fitz.Rect(rect.x0 - 28, rect.y0 - 28, rect.x1 + 28, rect.y1 + 28)
    expanded = fitz.Rect(rect)
    for _text, block_rect in blocks:
        intersection = label_zone & block_rect
        if not intersection.is_empty and _area(intersection) >= _area(block_rect) * 0.15:
            expanded |= block_rect
    return expanded


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^\w.-]+", "_", path.stem, flags=re.UNICODE).strip("._")
    return stem or "article"


def extract_figures(pdf_path: Path, output_dir: Path, dpi: int = 200) -> List[dict]:
    """Extract caption-associated figure crops and return manifest records."""
    pdf_path = pdf_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Input must be an existing PDF file.")
    if dpi < 72 or dpi > 600:
        raise ValueError("DPI must be between 72 and 600.")

    image_dir = output_dir / "figures"
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest: List[dict] = []
    stem = _safe_stem(pdf_path)

    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            blocks = _text_blocks(page)
            page_captions = _captions(blocks)
            if not page_captions:
                continue
            candidates = _components(_visual_elements(page))
            claimed: List[fitz.Rect] = []

            for caption_index, caption in enumerate(page_captions, start=1):
                available = [
                    candidate
                    for candidate in candidates
                    if not any(_rect_gap(candidate, used) < 8 for used in claimed)
                ]
                match = _pick_graphic(caption, available)
                if match is None:
                    continue
                graphic, confidence = match
                claimed.append(graphic)
                crop = _include_nearby_labels(graphic, blocks)
                crop.x0 = max(page.rect.x0, crop.x0 - 8)
                crop.y0 = max(page.rect.y0, crop.y0 - 8)
                crop.x1 = min(page.rect.x1, crop.x1 + 8)
                crop.y1 = min(page.rect.y1, crop.y1 + 8)
                if crop.is_empty:
                    continue

                figure_id = f"{stem}-p{page_index + 1:03}-fig{caption.number}"
                if caption_index > 1:
                    figure_id += f"-{caption_index}"
                image_name = f"{figure_id}.png"
                image_path = image_dir / image_name
                page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=crop, alpha=False).save(image_path)
                manifest.append(
                    {
                        "figure_id": figure_id,
                        "page": page_index + 1,
                        "figure_number": caption.number,
                        "caption": caption.text,
                        "image_path": (Path("figures") / image_name).as_posix(),
                        "confidence": confidence,
                        "bbox_x0_pt": round(crop.x0, 2),
                        "bbox_y0_pt": round(crop.y0, 2),
                        "bbox_x1_pt": round(crop.x1, 2),
                        "bbox_y1_pt": round(crop.y1, 2),
                    }
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "figures.csv").open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)
    return manifest
