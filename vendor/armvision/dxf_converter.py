"""
DXF converter utilities.
"""

from __future__ import annotations

import shutil
import subprocess
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from skimage.morphology import skeletonize
import ezdxf
from ezdxf.math import Vec2
from svgpathtools import svg2paths2


def _count_dxf_entities(dxf_path: Path) -> dict[str, int]:
    counts = {
        "LINE": 0,
        "ARC": 0,
        "CIRCLE": 0,
        "POINT": 0,
        "SPLINE": 0,
        "LWPOLYLINE": 0,
        "POLYLINE": 0,
    }
    if not dxf_path.exists():
        return counts

    lines = dxf_path.read_text(errors="ignore").splitlines()
    for idx, line in enumerate(lines[:-1]):
        if line.strip() != "0":
            continue
        entity = lines[idx + 1].strip()
        if entity in counts:
            counts[entity] += 1
    return counts


def _write_dxf_stats_txt(dxf_path: Path) -> Path:
    counts = _count_dxf_entities(dxf_path)
    steps = counts["LINE"] + counts["ARC"] + counts["CIRCLE"]
    txt_path = dxf_path.parent / "CAD.txt"
    txt_path.write_text(
        "\n".join(
            [
                f"DXF文件: {dxf_path.name}",
                f"POINT: {counts['POINT']}",
                f"LINE: {counts['LINE']}",
                f"ARC: {counts['ARC']}",
                f"CIRCLE: {counts['CIRCLE']}",
                f"SPLINE: {counts['SPLINE']}",
                f"LWPOLYLINE: {counts['LWPOLYLINE']}",
                f"POLYLINE: {counts['POLYLINE']}",
                f"总步数: {steps}",
                "",
                "步数规则: LINE + ARC + CIRCLE",
                "POINT 仅作为规则点，不计入绘制步数",
            ]
        ),
        encoding="utf-8",
    )
    return txt_path


def convert_logo_image_to_line_dxf(
    image_path: str | Path,
    dxf_path: str | Path,
    target_width_mm: float = 100.0,
    target_height_mm: float = 100.0,
    max_steps: int = 800,
    simplify_epsilon_px: float = 0.45,
) -> int:
    """Trace filled logo/icon regions directly to LINE entities.

    This avoids skeletonizing a 1px lineart preview, which makes circles and
    logo curves look stair-stepped. The output is still LINE-only.
    """
    import cv2

    image_path = Path(image_path)
    dxf_path = Path(dxf_path)
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    non_white = ((gray < 242) | ((saturation > 35) & (gray < 252))).astype(np.uint8) * 255
    mask = cv2.bitwise_or(otsu, non_white)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return 0

    height, width = gray.shape
    image_area = height * width
    min_area = max(6.0, image_area * 0.00001)
    min_perimeter = max(12.0, min(height, width) * 0.01)
    usable = []
    for contour in contours:
        area = abs(cv2.contourArea(contour))
        perimeter = cv2.arcLength(contour, closed=True)
        if area >= min_area and perimeter >= min_perimeter:
            usable.append((contour, perimeter))

    if not usable:
        return 0

    epsilon_scale = 1.0
    approximated: list[np.ndarray] = []
    total_segments = 0
    unlimited_steps = max_steps <= 0
    while True:
        approximated = []
        total_segments = 0
        for contour, perimeter in usable:
            epsilon = max(float(simplify_epsilon_px) * epsilon_scale, perimeter * 0.00045, 0.25)
            approx = cv2.approxPolyDP(contour, epsilon, closed=True)
            if len(approx) < 2:
                continue
            approximated.append(approx)
            total_segments += len(approx)
        if unlimited_steps or total_segments <= max_steps or epsilon_scale >= 18.0:
            break
        epsilon_scale *= 1.25

    if not unlimited_steps and total_segments > max_steps:
        raise RuntimeError(
            f"logo line segment count {total_segments} exceeds max_steps {max_steps}; "
            "increase DXF step limit or simplify the logo"
        )

    doc = _new_compatible_dxf()
    msp = doc.modelspace()
    x_factor = float(target_width_mm) / max(width - 1, 1)
    y_factor = float(target_height_mm) / max(height - 1, 1)

    path_count = 0
    for approx in approximated:
        pts = approx.reshape(-1, 2)
        if len(pts) < 2:
            continue
        closed_pts = np.vstack([pts, pts[0]])
        for p0, p1 in zip(closed_pts[:-1], closed_pts[1:]):
            x0, y0 = float(p0[0]) * x_factor, (height - 1 - float(p0[1])) * y_factor
            x1, y1 = float(p1[0]) * x_factor, (height - 1 - float(p1[1])) * y_factor
            if math.hypot(x1 - x0, y1 - y0) <= 1e-9:
                continue
            msp.add_line((x0, y0), (x1, y1), dxfattribs={"color": 7})
            path_count += 1

    if path_count > 0:
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(str(dxf_path))
        _normalize_dxf_text_for_controller(dxf_path)
        _write_dxf_stats_txt(dxf_path)

    return path_count


def _logo_contours_from_image(
    image_path: str | Path,
    simplify_epsilon_px: float = 0.18,
    min_area_ratio: float = 0.000002,
) -> tuple[list[np.ndarray], int, int]:
    import cv2

    image_path = Path(image_path)
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    non_white = ((gray < 242) | ((saturation > 35) & (gray < 252))).astype(np.uint8) * 255
    mask = cv2.bitwise_or(otsu, non_white)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    height, width = gray.shape
    image_area = height * width
    min_area = max(2.0, image_area * min_area_ratio)
    min_perimeter = max(6.0, min(height, width) * 0.004)
    approximated: list[np.ndarray] = []
    for contour in contours:
        area = abs(cv2.contourArea(contour))
        perimeter = cv2.arcLength(contour, closed=True)
        if area < min_area or perimeter < min_perimeter:
            continue
        epsilon = max(float(simplify_epsilon_px), perimeter * 0.00025, 0.08)
        approx = cv2.approxPolyDP(contour, epsilon, closed=True)
        if len(approx) >= 2:
            approximated.append(approx)
    return approximated, width, height


def append_logo_image_to_dxf(
    dxf_path: str | Path,
    logo_image_path: str | Path,
    logo_width_mm: float,
    offset_x_mm: float,
    offset_y_top_mm: float,
    canvas_height_mm: float,
    simplify_epsilon_px: float = 0.18,
    min_area_ratio: float = 0.000002,
    max_steps: int = 600,
    include_text: bool = False,
) -> int:
    """Append a small centerline logo to an existing DXF.

    The logo is added after the main image conversion, so it does not consume the
    main image's max_steps budget.
    """
    dxf_path = Path(dxf_path)
    logo_image_path = Path(logo_image_path)
    if not dxf_path.exists() or not logo_image_path.exists():
        return 0

    def detect_text_cut_ratio(image_path: Path) -> float | None:
        import cv2
        import numpy as np

        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        dark = gray < 220
        row_counts = dark.sum(axis=1)
        threshold = max(2, int(gray.shape[1] * 0.002))
        rows = np.flatnonzero(row_counts > threshold)
        if rows.size <= 0:
            return None
        runs: list[tuple[int, int]] = []
        start = int(rows[0])
        prev = int(rows[0])
        for row in rows[1:]:
            row = int(row)
            if row > prev + 1:
                runs.append((start, prev))
                start = row
            prev = row
        runs.append((start, prev))
        if len(runs) < 2:
            return None
        gaps = [(runs[i][1], runs[i + 1][0], runs[i + 1][0] - runs[i][1]) for i in range(len(runs) - 1)]
        gap_start, gap_end, gap_size = max(gaps, key=lambda item: item[2])
        if gap_size < gray.shape[0] * 0.03:
            return None
        return ((gap_start + gap_end) / 2.0) / max(gray.shape[0], 1)

    tmp_logo_dxf = dxf_path.with_suffix(".logo_tmp.dxf")
    try:
        text_cut_ratio = detect_text_cut_ratio(logo_image_path)
        if include_text and text_cut_ratio is None:
            # Fallback split: the icon stays in the upper region and the HUACHENG
            # letters stay in the lower region even when gap detection is noisy.
            text_cut_ratio = 0.60
        work_width = max(float(logo_width_mm) * 4.0, 80.0)
        centerline_count = _centerline_to_dxf(
            logo_image_path,
            tmp_logo_dxf,
            scale_x=work_width,
            scale_y=work_width,
            threshold=220,
            smooth_iterations=4,
            simplify_epsilon_px=0.45,
            min_path_length_mm=0.08,
            entity_mode="line",
            max_steps=max_steps,
            smooth_before_simplify=True,
            post_smooth_iterations=1,
        )
        if centerline_count <= 0 or not tmp_logo_dxf.exists():
            return 0

        tmp_doc = ezdxf.readfile(str(tmp_logo_dxf))
        tmp_lines = [ent for ent in tmp_doc.modelspace() if ent.dxftype() == "LINE"]
        if not tmp_lines:
            return 0

        xs = [pt for ent in tmp_lines for pt in (float(ent.dxf.start.x), float(ent.dxf.end.x))]
        ys = [pt for ent in tmp_lines for pt in (float(ent.dxf.start.y), float(ent.dxf.end.y))]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        src_w = max(max_x - min_x, 1e-9)
        src_h = max(max_y - min_y, 1e-9)

        doc = ezdxf.readfile(str(dxf_path))
        if "LOGO" not in doc.layers:
            doc.layers.add("LOGO", color=7)
        if "LOGO_TEXT" not in doc.layers:
            doc.layers.add("LOGO_TEXT", color=7)
        msp = doc.modelspace()
        target_scale = float(logo_width_mm) / src_w
        target_h = src_h * target_scale
        offset_y_bottom_mm = float(canvas_height_mm) - float(offset_y_top_mm) - target_h

        logo_segments: list[tuple[float, float, float, float]] = []
        text_segments: list[tuple[float, float, float, float]] = []
        for ent in tmp_lines:
            mid_src_y = (float(ent.dxf.start.y) + float(ent.dxf.end.y)) / 2.0
            top_ratio = 1.0 - ((mid_src_y - min_y) / src_h)
            # text_cut_ratio is measured from top to bottom of the source image.
            # The icon sits above, the HUACHENG letters sit below.
            layer = "LOGO_TEXT" if text_cut_ratio is not None and top_ratio > text_cut_ratio else "LOGO"
            if layer == "LOGO_TEXT" and not include_text:
                continue
            x0 = float(offset_x_mm) + (float(ent.dxf.start.x) - min_x) * target_scale
            y0 = offset_y_bottom_mm + (float(ent.dxf.start.y) - min_y) * target_scale
            x1 = float(offset_x_mm) + (float(ent.dxf.end.x) - min_x) * target_scale
            y1 = offset_y_bottom_mm + (float(ent.dxf.end.y) - min_y) * target_scale
            if math.hypot(x1 - x0, y1 - y0) <= 1e-9:
                continue
            if layer == "LOGO_TEXT":
                text_segments.append((x0, y0, x1, y1))
            else:
                logo_segments.append((x0, y0, x1, y1))

        if include_text and text_segments:
            # The icon has a low tail close to the word mark. A simple horizontal
            # split can misclassify that tail as LOGO_TEXT, which makes the robot
            # start letters before the icon visually finishes. Keep only the
            # lowest connected vertical band as text; return upper fragments to
            # the icon layer.
            intervals = sorted(
                (min(y0, y1), max(y0, y1), idx)
                for idx, (_x0, y0, _x1, y1) in enumerate(text_segments)
            )
            band_gap_tol = max(target_h * 0.025, float(logo_width_mm) * 0.015, 0.35)
            bands: list[dict[str, object]] = []
            for low, high, idx in intervals:
                if not bands or low > float(bands[-1]["high"]) + band_gap_tol:
                    bands.append({"low": low, "high": high, "indices": [idx]})
                else:
                    bands[-1]["high"] = max(float(bands[-1]["high"]), high)
                    indices = bands[-1]["indices"]
                    assert isinstance(indices, list)
                    indices.append(idx)

            if len(bands) > 1:
                text_band = min(bands, key=lambda band: float(band["low"]))
                text_indices = set(text_band["indices"])
                reclassified_logo_segments = [
                    segment
                    for idx, segment in enumerate(text_segments)
                    if idx not in text_indices
                ]
                text_segments = [
                    segment
                    for idx, segment in enumerate(text_segments)
                    if idx in text_indices
                ]
                logo_segments.extend(reclassified_logo_segments)

        path_count = 0
        for x0, y0, x1, y1 in logo_segments:
            msp.add_line((x0, y0), (x1, y1), dxfattribs={"color": 7, "layer": "LOGO"})
            path_count += 1
        for x0, y0, x1, y1 in text_segments:
            msp.add_line((x0, y0), (x1, y1), dxfattribs={"color": 7, "layer": "LOGO_TEXT"})
            path_count += 1

        if path_count > 0:
            doc.saveas(str(dxf_path))
            _normalize_dxf_text_for_controller(dxf_path)
            _write_dxf_stats_txt(dxf_path)
        return path_count
    finally:
        tmp_logo_dxf.unlink(missing_ok=True)


def _new_compatible_dxf():
    """Create a DXF document closer to the controller's known-good sample."""
    doc = ezdxf.new(dxfversion="R2000", setup=False)
    doc.header["$DWGCODEPAGE"] = "ANSI_936"
    return doc


def _cleanup_stale_dxf_variants(dxf_path: Path) -> None:
    # ezdxf may leave "#name.dxf"-style files behind if a save is interrupted.
    for candidate in dxf_path.parent.glob(f"#*{dxf_path.name}"):
        if candidate != dxf_path:
            candidate.unlink(missing_ok=True)


def _normalize_dxf_text_for_controller(dxf_path: Path) -> None:
    """Reduce DXF to the controller-friendly minimal structure and header style."""
    if not dxf_path.exists():
        return

    lines = dxf_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    minimized: list[str] = []
    i = 0
    keep_sections = {"HEADER", "TABLES", "ENTITIES"}
    while i < len(lines):
        if (
            i + 3 < len(lines)
            and lines[i].strip() == "0"
            and lines[i + 1].strip() == "SECTION"
            and lines[i + 2].strip() == "2"
        ):
            sec_name = lines[i + 3].strip()
            j = i + 4
            while j + 1 < len(lines):
                if lines[j].strip() == "0" and lines[j + 1].strip() == "ENDSEC":
                    j += 2
                    break
                j += 1
            if sec_name in keep_sections:
                minimized.extend(lines[i:j])
            i = j
            continue
        if i + 1 < len(lines) and lines[i].strip() == "0" and lines[i + 1].strip() == "EOF":
            minimized.extend(lines[i : i + 2])
            break
        i += 1

    normalized: list[str] = []
    i = 0
    while i < len(minimized):
        if i + 3 < len(minimized) and minimized[i].strip() == "9":
            var_name = minimized[i + 1].strip()
            if var_name in {"$LASTSAVEDBY", "$INSUNITS", "$ACADMAINTVER"}:
                i += 4
                continue
            if var_name == "$DWGCODEPAGE":
                normalized.extend([minimized[i], minimized[i + 1], minimized[i + 2], "ANSI_936"])
                i += 4
                continue
        normalized.append(minimized[i])
        i += 1

    dxf_path.write_text("\n".join(normalized) + "\n", encoding="utf-8")


def _convert_to_pbm(image_path: Path, threshold: int = 128) -> Path:
    img = Image.open(image_path).convert("L")
    bw = img.point(lambda x: 0 if x < threshold else 255, "1")
    pbm_path = image_path.with_suffix(".pbm")
    bw.save(pbm_path)
    return pbm_path


def _skeleton_neighbors(
    pixels: set[tuple[int, int]], point: tuple[int, int]
) -> list[tuple[int, int]]:
    """Return graph neighbours without diagonal corner-touch false forks.

    A raster skeleton often has both a diagonal edge and its two orthogonal
    alternatives. Treating all three as graph edges turns a smooth stroke into
    a cluster of fake junctions. Keep the diagonal only when it is the sole
    connection, so true branches remain available for repeated pen strokes.
    """
    x, y = point
    adjacent: list[tuple[int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            neighbour = (x + dx, y + dy)
            if neighbour not in pixels:
                continue
            if dx != 0 and dy != 0:
                # If an orthogonal bridge exists, diagonal adjacency is only a
                # raster corner touch, not another physical pen branch.
                if (x + dx, y) in pixels or (x, y + dy) in pixels:
                    continue
            adjacent.append(neighbour)
    return adjacent


def _skeleton_paths(binary: np.ndarray) -> list[list[tuple[int, int]]]:
    pixels = {(x, y) for y, x in np.argwhere(binary)}
    if not pixels:
        return []

    neighbors = {}
    for x, y in pixels:
        adj = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if (nx, ny) in pixels:
                    adj.append((nx, ny))
        neighbors[(x, y)] = adj

    def edge_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    visited_edges = set()
    paths: list[list[tuple[int, int]]] = []

    endpoints = [p for p in pixels if len(neighbors[p]) == 1]
    for start in endpoints:
        for nxt in neighbors[start]:
            ek = edge_key(start, nxt)
            if ek in visited_edges:
                continue
            path = [start, nxt]
            visited_edges.add(ek)
            prev, curr = start, nxt
            while True:
                next_candidates = [p for p in neighbors[curr] if p != prev]
                if len(next_candidates) != 1:
                    break
                nxt2 = next_candidates[0]
                ek2 = edge_key(curr, nxt2)
                if ek2 in visited_edges:
                    break
                path.append(nxt2)
                visited_edges.add(ek2)
                prev, curr = curr, nxt2
            paths.append(path)

    for start in pixels:
        for nxt in neighbors[start]:
            ek = edge_key(start, nxt)
            if ek in visited_edges:
                continue
            path = [start, nxt]
            visited_edges.add(ek)
            prev, curr = start, nxt
            while True:
                next_candidates = [p for p in neighbors[curr] if p != prev]
                if not next_candidates:
                    break
                if len(next_candidates) > 1:
                    break
                nxt2 = next_candidates[0]
                ek2 = edge_key(curr, nxt2)
                if ek2 in visited_edges:
                    break
                path.append(nxt2)
                visited_edges.add(ek2)
                prev, curr = curr, nxt2
            paths.append(path)

    return paths


def _prune_skeleton_spurs(binary: np.ndarray, max_spur_px: int = 5, iterations: int = 2) -> np.ndarray:
    """Remove tiny terminal branches created around skeleton junctions."""
    if max_spur_px <= 0:
        return binary

    pruned = binary.astype(bool).copy()
    for _ in range(max(1, iterations)):
        pixels = {(x, y) for y, x in np.argwhere(pruned)}
        if not pixels:
            break

        neighbors: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for x, y in pixels:
            adj = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    p = (x + dx, y + dy)
                    if p in pixels:
                        adj.append(p)
            neighbors[(x, y)] = adj

        to_remove: set[tuple[int, int]] = set()
        endpoints = [p for p, adj in neighbors.items() if len(adj) == 1]
        for endpoint in endpoints:
            branch = [endpoint]
            prev = None
            curr = endpoint
            while True:
                next_candidates = [p for p in neighbors.get(curr, []) if p != prev]
                if len(next_candidates) != 1:
                    break
                nxt = next_candidates[0]
                if len(neighbors.get(nxt, [])) != 2:
                    if len(neighbors.get(nxt, [])) >= 3 and len(branch) <= max_spur_px:
                        to_remove.update(branch)
                    break
                branch.append(nxt)
                if len(branch) > max_spur_px:
                    break
                prev, curr = curr, nxt

        if not to_remove:
            break
        for x, y in to_remove:
            pruned[y, x] = False

    return pruned


def _portrait_mouth_bridge(binary: np.ndarray) -> np.ndarray:
    """Reconnect thin lip strokes in the central lower-face band for portraits."""
    if binary.ndim != 2:
        return binary
    height, width = binary.shape
    if height < 16 or width < 16:
        return binary

    x0 = max(0, int(round(width * 0.22)))
    x1 = min(width, int(round(width * 0.78)))
    y0 = max(0, int(round(height * 0.52)))
    y1 = min(height, int(round(height * 0.82)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return binary

    roi = (binary[y0:y1, x0:x1] > 0).astype(np.uint8) * 255
    # First do a soft 2D close to reconnect anti-aliased lip gaps, then a
    # stronger horizontal close because lip strokes are mostly horizontal.
    close_kernel_soft = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, close_kernel_soft, iterations=1)
    close_kernel_wide = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, close_kernel_wide, iterations=1)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
    roi = cv2.dilate(roi, dilate_kernel, iterations=1)

    bridged = binary.copy()
    bridged[y0:y1, x0:x1] = np.logical_or(bridged[y0:y1, x0:x1], roi > 0)
    return bridged


def _pixel_path_length(path: list[tuple[int, int]]) -> float:
    if len(path) < 2:
        return 0.0
    return sum(math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(path[:-1], path[1:]))


def _chaikin_smooth(points: list[Vec2], iterations: int = 2) -> list[Vec2]:
    if iterations <= 0 or len(points) < 3:
        return points

    smooth = points
    for _ in range(iterations):
        new_points = [smooth[0]]
        for p0, p1 in zip(smooth[:-1], smooth[1:]):
            q = p0 * 0.75 + p1 * 0.25
            r = p0 * 0.25 + p1 * 0.75
            new_points.extend([q, r])
        new_points.append(smooth[-1])
        smooth = new_points
    return smooth


def _smooth_between_sharp_turns(
    points: list[Vec2],
    iterations: int = 2,
    angle_threshold_deg: float = 55.0,
) -> list[Vec2]:
    if iterations <= 0 or len(points) < 4:
        return points

    cos_threshold = np.cos(np.deg2rad(angle_threshold_deg))
    break_indices = [0]
    for idx in range(1, len(points) - 1):
        p0, p1, p2 = points[idx - 1], points[idx], points[idx + 1]
        v1 = p1 - p0
        v2 = p2 - p1
        len1 = v1.magnitude
        len2 = v2.magnitude
        if len1 <= 1e-9 or len2 <= 1e-9:
            continue
        cos_angle = (v1.x * v2.x + v1.y * v2.y) / (len1 * len2)
        if cos_angle < cos_threshold:
            break_indices.append(idx)
    break_indices.append(len(points) - 1)

    if len(break_indices) <= 2:
        return _chaikin_smooth(points, iterations=iterations)

    smoothed: list[Vec2] = []
    for start, end in zip(break_indices[:-1], break_indices[1:]):
        segment = points[start:end + 1]
        if len(segment) >= 4:
            segment = _chaikin_smooth(segment, iterations=iterations)
        if smoothed:
            smoothed.extend(segment[1:])
        else:
            smoothed.extend(segment)
    return smoothed


def _point_line_distance(point: Vec2, start: Vec2, end: Vec2) -> float:
    segment = end - start
    seg_len_sq = segment.x * segment.x + segment.y * segment.y
    if seg_len_sq == 0:
        return point.distance(start)
    t = ((point - start).x * segment.x + (point - start).y * segment.y) / seg_len_sq
    t = max(0.0, min(1.0, t))
    projection = start + segment * t
    return point.distance(projection)


def _rdp_simplify(points: list[Vec2], epsilon: float) -> list[Vec2]:
    if epsilon <= 0 or len(points) < 3:
        return points

    max_dist = -1.0
    split_index = -1
    start = points[0]
    end = points[-1]
    for idx in range(1, len(points) - 1):
        dist = _point_line_distance(points[idx], start, end)
        if dist > max_dist:
            max_dist = dist
            split_index = idx

    if max_dist <= epsilon or split_index < 0:
        return [start, end]

    left = _rdp_simplify(points[: split_index + 1], epsilon)
    right = _rdp_simplify(points[split_index:], epsilon)
    return left[:-1] + right


def _polyline_length(points: list[Vec2]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(p0.distance(p1) for p0, p1 in zip(points[:-1], points[1:]))


def _circle_from_3pts(a: Vec2, b: Vec2, c: Vec2) -> tuple[Vec2, float]:
    x1, y1 = a.x, a.y
    x2, y2 = b.x, b.y
    x3, y3 = c.x, c.y
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        raise ValueError("collinear")
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    center = Vec2(ux, uy)
    return center, center.distance(a)


def _angle_deg(center: Vec2, p: Vec2) -> float:
    return math.degrees(math.atan2(p.y - center.y, p.x - center.x)) % 360.0


def _contains_ccw(a0: float, a1: float, am: float) -> bool:
    span = (a1 - a0) % 360.0
    rel = (am - a0) % 360.0
    return rel <= span


def _arc_angles_through_mid(start: Vec2, mid: Vec2, end: Vec2, center: Vec2) -> tuple[float, float]:
    """Return DXF ARC start/end angles, preferring the shorter arc through mid."""
    a0 = _angle_deg(center, start)
    a1 = _angle_deg(center, end)
    am = _angle_deg(center, mid)

    ccw_span = (a1 - a0) % 360.0
    ccw_rel = (am - a0) % 360.0
    if ccw_rel <= ccw_span:
        cw_span = (a0 - a1) % 360.0
        if ccw_span <= cw_span:
            return a0, a1
        return a1, a0

    return a1, a0


def _cross_z(a: Vec2, b: Vec2, c: Vec2) -> float:
    ab = b - a
    bc = c - b
    return ab.x * bc.y - ab.y * bc.x


def _normalize_angle_diff_deg(a: float, b: float) -> float:
    diff = (b - a) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def _try_fit_arc(points: list[Vec2]) -> tuple | None:
    if len(points) < 3:
        return None

    start = points[0]
    end = points[-1]
    mid = points[len(points) // 2]
    chord = start.distance(end)
    if chord <= 0.45:
        return None

    poly_len = _polyline_length(points)
    if poly_len <= 1e-9:
        return None

    # If the curve is only slightly bent, prefer LINE over ARC.
    bend_ratio = poly_len / max(chord, 1e-9)
    if bend_ratio < 1.045:
        return None

    turn_sign = 0
    nonzero_turns = 0
    for p0, p1, p2 in zip(points[:-2], points[1:-1], points[2:]):
        cz = _cross_z(p0, p1, p2)
        if abs(cz) <= 1e-6:
            continue
        sign = 1 if cz > 0 else -1
        nonzero_turns += 1
        if turn_sign == 0:
            turn_sign = sign
        elif sign != turn_sign:
            return None

    if nonzero_turns == 0:
        return None

    try:
        center, radius = _circle_from_3pts(start, mid, end)
        sa, ea = _arc_angles_through_mid(start, mid, end, center)
    except Exception:
        return None

    span = (ea - sa) % 360.0
    if span > 180.0:
        span = 360.0 - span
    if not (26.0 <= span <= 150.0):
        return None
    if not (1.2 <= radius <= 120.0):
        return None

    max_radial_error = max(0.10, min(0.32, 0.026 * chord + 0.010 * radius))
    angle_samples = [_angle_deg(center, p) for p in points]
    total_abs_turn = 0.0
    for a0, a1 in zip(angle_samples[:-1], angle_samples[1:]):
        step = _normalize_angle_diff_deg(a0, a1)
        if abs(step) > 95.0:
            return None
        if turn_sign > 0 and step < -2.0:
            return None
        if turn_sign < 0 and step > 2.0:
            return None
        total_abs_turn += abs(step)

    if total_abs_turn < 12.0 or total_abs_turn > 175.0:
        return None

    radial_errors = [abs(center.distance(p) - radius) for p in points]
    if max(radial_errors) > max_radial_error:
        return None

    arc_len = math.radians(span) * radius
    if poly_len <= 1e-9 or abs(poly_len - arc_len) > max(0.25, poly_len * 0.18):
        return None

    return ("ARC", start, mid, end, center, radius, sa, ea)


def _fit_line_arc_primitives(points: list[Vec2]) -> list[tuple]:
    """Fit a simplified open centerline to LINE/ARC primitives with arc preference."""
    if len(points) < 2:
        return []
    if len(points) == 2:
        return [("LINE", points[0], points[1])]

    primitives: list[tuple] = []
    i = 0
    while i < len(points) - 1:
        best_arc = None
        best_arc_span = 0
        max_window = min(7, len(points) - i)
        for window in range(max_window, 2, -1):
            candidate = _try_fit_arc(points[i : i + window])
            if candidate is None:
                continue
            span_score = window
            if span_score > best_arc_span:
                best_arc = candidate
                best_arc_span = span_score

        if best_arc is not None:
            primitives.append(best_arc)
            i += best_arc_span - 1
            continue

        line_end = i + 1
        while line_end + 1 < len(points):
            start = points[i]
            candidate_end = points[line_end + 1]
            max_dev = 0.0
            for probe in points[i + 1 : line_end + 1]:
                max_dev = max(max_dev, _point_line_distance(probe, start, candidate_end))
            if max_dev > 0.11:
                break
            line_end += 1

        p0, p1 = points[i], points[line_end]
        if p0.distance(p1) > 1e-9:
            primitives.append(("LINE", p0, p1))
        i = line_end

    return primitives


def _has_sharp_turn(points: list[Vec2], angle_threshold_deg: float = 55.0) -> bool:
    if len(points) < 3:
        return False

    cos_threshold = np.cos(np.deg2rad(angle_threshold_deg))
    for p0, p1, p2 in zip(points[:-2], points[1:-1], points[2:]):
        v1 = p1 - p0
        v2 = p2 - p1
        len1 = v1.magnitude
        len2 = v2.magnitude
        if len1 <= 1e-9 or len2 <= 1e-9:
            continue
        cos_angle = (v1.x * v2.x + v1.y * v2.y) / (len1 * len2)
        if cos_angle < cos_threshold:
            return True
    return False


def _path_span(points: list[Vec2]) -> float:
    if not points:
        return 0.0
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _fit_vec2_paths_to_box(
    paths: list[list[Vec2]],
    target_width: float | None,
    target_height: float | None,
) -> list[list[Vec2]]:
    if not target_width or not target_height:
        return paths

    all_points = [point for path in paths for point in path]
    if not all_points:
        return paths

    min_x = min(point.x for point in all_points)
    max_x = max(point.x for point in all_points)
    min_y = min(point.y for point in all_points)
    max_y = max(point.y for point in all_points)
    content_width = max_x - min_x
    content_height = max_y - min_y
    if content_width <= 1e-9 or content_height <= 1e-9:
        return paths

    box_width = float(target_width)
    box_height = float(target_height)
    fit = min(box_width / content_width, box_height / content_height)
    dx = (box_width - content_width * fit) / 2.0 - min_x * fit
    dy = (box_height - content_height * fit) / 2.0 - min_y * fit
    return [[Vec2(point.x * fit + dx, point.y * fit + dy) for point in path] for path in paths]


def _path_keep_priority(
    points: list[Vec2],
    path_len: float,
    span: float,
    primitive_count: int,
    width_mm: float,
    height_mm: float,
    portrait_hair_suppression: bool = False,
) -> float:
    """Higher score means the path is more important to keep.

    Heuristic goal for portraits:
    - keep face contour, eyes, brows, nose, mouth, ears, neck
    - drop hair wisps / outer small tail fragments first when step budget is tight
    """
    if not points:
        return -1e9

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx = 0.5 * (min_x + max_x)
    cy = 0.5 * (min_y + max_y)
    nx = cx / max(width_mm, 1e-9)
    ny = cy / max(height_mm, 1e-9)
    width_n = (max_x - min_x) / max(width_mm, 1e-9)
    height_n = (max_y - min_y) / max(height_mm, 1e-9)
    max_dim = max(width_mm, height_mm, 1e-9)
    min_dim = min(width_mm, height_mm, 1e-9)

    center_dist = math.hypot((nx - 0.5) / 0.5, (ny - 0.48) / 0.52)
    score = 0.0

    # Remove tiny dot-like fragments first to free steps for long contours.
    if path_len < 1.2 and span < 0.9:
        score -= 260.0
    elif path_len < 2.0 and span < 1.4:
        score -= 180.0
    elif path_len < 3.2 and span < 2.2:
        score -= 95.0

    # User-defined organ priority:
    # 1 mouth > 2 central face > 4 ear/jaw/neck > 3 eyebrows = 5 long contours > 6 hair fragments > 7 noise.
    long_contour_score = min(path_len / max_dim, 0.75) * 120.0
    long_contour_score += min(span / max_dim, 0.55) * 70.0
    score += long_contour_score
    score += min(primitive_count, 18) * 1.2

    # Central face region: prioritize eyes, brows, nose, mouth.
    if 0.24 <= nx <= 0.76 and 0.22 <= ny <= 0.74:
        score += 240.0
    if 0.30 <= nx <= 0.70 and 0.24 <= ny <= 0.70:
        score += 115.0
    # Eye band: short arcs around the upper-middle face must survive step pruning.
    if 0.20 <= nx <= 0.80 and 0.44 <= ny <= 0.66 and path_len >= 0.45:
        score += 180.0
    if 0.28 <= nx <= 0.72 and 0.42 <= ny <= 0.70 and span >= 0.35:
        score += 95.0
    # Eyebrows are kept at the same class as long/principal contours.
    if 0.26 <= nx <= 0.74 and 0.48 <= ny <= 0.72 and width_n >= height_n * 1.2:
        score += 150.0
    if 0.32 <= nx <= 0.68 and 0.52 <= ny <= 0.68 and path_len >= 0.7:
        score += 95.0
    # Nose band: central short lines are useful even if very simple.
    if 0.38 <= nx <= 0.62 and 0.32 <= ny <= 0.58 and path_len >= 0.35:
        score += 170.0
    # Mouth strokes are usually short central fragments; keep them ahead of hair/noise.
    if 0.28 <= nx <= 0.72 and 0.18 <= ny <= 0.48:
        score += 320.0
    if 0.36 <= nx <= 0.64 and 0.22 <= ny <= 0.42 and path_len >= 0.5:
        score += 150.0

    # Ear / jaw / neck outrank eyebrows and long contours, but stay below central face.
    if 0.16 <= nx <= 0.84 and 0.10 <= ny <= 0.78:
        score += 120.0

    is_outer_hair_contour = (
        ny > 0.52
        and center_dist > 0.38
        and (path_len > 0.16 * min_dim or span > 0.16 * min_dim)
    )
    if is_outer_hair_contour:
        score += 175.0
        if path_len > 0.24 * min_dim or span > 0.22 * min_dim:
            score += 90.0

    # Penalize tiny fragments near the outer top/side hair area first.
    if not is_outer_hair_contour and ny > 0.60 and center_dist > 0.48 and path_len < 18.0:
        score -= 150.0
    if not is_outer_hair_contour and ny > 0.52 and center_dist > 0.62 and span < 10.0:
        score -= 70.0
    if not is_outer_hair_contour and center_dist > 0.78 and path_len < 24.0:
        score -= 55.0
    if not is_outer_hair_contour and ny > 0.72 and span < 16.0:
        score -= 85.0

    # Interior hair strokes often appear as long thin vertical/diagonal strands in the
    # upper half. Penalize them so eyes/nose/mouth are not pruned away.
    if 0.18 <= nx <= 0.82 and ny > 0.55 and height_n > width_n * 2.0 and span < 0.45 * min_dim:
        score -= 120.0

    if portrait_hair_suppression:
        # Portrait AI often overdraws hair as many long, parallel strands. These lines
        # are visually expensive for the robot and can push eyes/mouth out of budget.
        in_hair_zone = ny > 0.54 and (center_dist > 0.24 or height_n > width_n * 1.35)
        looks_like_strand = (
            (height_n > width_n * 1.45 or width_n > height_n * 1.45)
            and span > 0.06 * min_dim
            and path_len > 0.07 * min_dim
        )
        top_side_wisp = ny > 0.68 and (nx < 0.32 or nx > 0.68 or center_dist > 0.38)
        if in_hair_zone and looks_like_strand and not is_outer_hair_contour:
            score -= 260.0
        if in_hair_zone and looks_like_strand and is_outer_hair_contour:
            score -= 95.0
        if top_side_wisp:
            score -= 180.0
        # Long lower-side strands are common in generated female portraits. Keep a few
        # silhouette lines, but do not let many interior parallel strands outrank facial features.
        if ny > 0.38 and center_dist > 0.45 and looks_like_strand and width_n < 0.18:
            score -= 140.0

    # Thin top-side slivers are usually hair tips, not identity-critical geometry.
    if not is_outer_hair_contour and (width_n < 0.06 or height_n < 0.06) and ny > 0.55 and center_dist > 0.50:
        score -= 30.0

    # Small isolated central specks are usually noise, not useful facial structure.
    if path_len < 2.6 and span < 1.8 and width_n < 0.025 and height_n < 0.025:
        if 0.28 <= nx <= 0.72 and 0.18 <= ny <= 0.48:
            score -= 20.0
        elif 0.26 <= nx <= 0.74 and 0.48 <= ny <= 0.72 and width_n >= height_n * 1.2:
            score -= 35.0
        else:
            score -= 70.0

    # Reward genuinely long strokes so saved steps go to major contours.
    if path_len > 0.18 * min_dim:
        score += 24.0
    if path_len > 0.28 * min_dim:
        score += 20.0

    return score


def _binary_runs(row: np.ndarray) -> list[tuple[int, int]]:
    padded = np.pad(row.astype(np.uint8), (1, 1))
    changes = np.diff(padded.astype(np.int16))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def _serpentine_fill_paths(
    runs_by_y: list[tuple[int, list[tuple[int, int]]]],
) -> list[list[tuple[int, int]]]:
    """Join overlapping runs on adjacent rows into continuous zigzag paths."""
    finished: list[list[tuple[int, int]]] = []
    active: list[dict] = []

    for y, runs in runs_by_y:
        candidates: list[tuple[int, int, int]] = []
        for active_index, state in enumerate(active):
            old_x0, old_x1 = state["interval"]
            for run_index, (x0, x1) in enumerate(runs):
                overlap = min(old_x1, x1) - max(old_x0, x0) + 1
                if overlap > 0:
                    candidates.append((overlap, active_index, run_index))
        candidates.sort(reverse=True)

        matched_active: set[int] = set()
        matched_runs: set[int] = set()
        assignments: dict[int, int] = {}
        for _, active_index, run_index in candidates:
            if active_index in matched_active or run_index in matched_runs:
                continue
            matched_active.add(active_index)
            matched_runs.add(run_index)
            assignments[run_index] = active_index

        next_active: list[dict] = []
        for run_index, (x0, x1) in enumerate(runs):
            if run_index in assignments:
                state = active[assignments[run_index]]
            else:
                state = {"path": [], "interval": (x0, x1), "reverse": False}
            start, end = ((x1, y), (x0, y)) if state["reverse"] else ((x0, y), (x1, y))
            # Extending the same point list inserts the short in-area turn from
            # the preceding row and keeps the pen down through the whole branch.
            state["path"].extend((start, end))
            state["interval"] = (x0, x1)
            state["reverse"] = not state["reverse"]
            next_active.append(state)

        for active_index, state in enumerate(active):
            if active_index not in matched_active and len(state["path"]) >= 2:
                finished.append(state["path"])
        active = next_active

    finished.extend(state["path"] for state in active if len(state["path"]) >= 2)
    return finished


def _build_hybrid_fill_paths(
    binary: np.ndarray,
    *,
    mm_per_px: float,
    mode: str,
    spacing_mm: float,
    wide_threshold_mm: float,
) -> tuple[list[list[tuple[int, int]]], np.ndarray]:
    """Classify filled regions and return 0.25 mm serpentine scan paths."""
    import cv2

    mask = binary.astype(np.uint8)
    height, width = mask.shape
    spacing_px = max(1, round(spacing_mm / max(mm_per_px, 1e-9)))
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    radius_threshold_px = (wide_threshold_mm / 2.0) / max(mm_per_px, 1e-9)

    # Portrait mode is intentionally conservative. Compact dense isolated blobs
    # in the eye band are normally pupils; hair, brows and frames stay centerline.
    portrait_mask = np.zeros_like(mask)
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "portrait":
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for component_id in range(1, count):
            x, y, w, h, area = [int(value) for value in stats[component_id]]
            width_mm = w * mm_per_px
            height_mm = h * mm_per_px
            density = area / max(w * h, 1)
            aspect = w / max(h, 1)
            center_x = (x + w * 0.5) / max(width, 1)
            center_y = (y + h * 0.5) / max(height, 1)
            if (
                0.65 <= width_mm <= 4.0
                and 0.65 <= height_mm <= 4.0
                and 0.55 <= aspect <= 1.8
                and density >= 0.52
                and 0.20 <= center_x <= 0.80
                and 0.20 <= center_y <= 0.55
            ):
                portrait_mask[labels == component_id] = 1


    coverage = np.zeros_like(mask)
    runs_by_y: list[tuple[int, list[tuple[int, int]]]] = []
    for y in range(0, height, spacing_px):
        selected: list[tuple[int, int]] = []
        row_mask = portrait_mask[y] if normalized_mode == "portrait" else mask[y]
        for x0, x1 in _binary_runs(row_mask.astype(bool)):
            wide_enough = float(distance[y, x0:x1 + 1].max()) >= radius_threshold_px
            if x1 > x0 and (normalized_mode == "portrait" or wide_enough):
                selected.append((x0, x1))
                coverage[y, x0:x1 + 1] = 1
        runs_by_y.append((y, selected))

    return _serpentine_fill_paths(runs_by_y), coverage


def _detect_iris_pair(binary: np.ndarray) -> list[tuple[float, float, float]] | None:
    """Find a plausible left/right iris pair from round closed line contours."""
    import cv2

    height, width = binary.shape
    min_dim = float(min(width, height))
    contours, _ = cv2.findContours(
        binary.astype(np.uint8) * 255,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    candidates: list[tuple[float, float, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, closed=True))
        if area <= 0.0 or perimeter <= 0.0:
            continue
        x, y, contour_w, contour_h = cv2.boundingRect(contour)
        radius = (contour_w + contour_h) * 0.25
        aspect = contour_w / max(float(contour_h), 1.0)
        circularity = 4.0 * math.pi * area / (perimeter * perimeter)
        center_x = x + contour_w * 0.5
        center_y = y + contour_h * 0.5
        if not (
            min_dim * 0.008 <= radius <= min_dim * 0.035
            and 0.70 <= aspect <= 1.40
            and circularity >= 0.55
            and width * 0.15 <= center_x <= width * 0.85
            and height * 0.24 <= center_y <= height * 0.58
        ):
            continue
        candidates.append((center_x, center_y, radius))

    best_pair: list[tuple[float, float, float]] | None = None
    best_score = float("inf")
    for index, first in enumerate(candidates):
        for second in candidates[index + 1 :]:
            left, right = sorted((first, second), key=lambda item: item[0])
            separation = right[0] - left[0]
            if not width * 0.10 <= separation <= width * 0.42:
                continue
            radius_ratio = max(left[2], right[2]) / max(min(left[2], right[2]), 1e-9)
            if radius_ratio > 1.55:
                continue
            vertical_delta = abs(left[1] - right[1])
            if vertical_delta > max(height * 0.035, max(left[2], right[2]) * 1.5):
                continue
            midpoint_x = (left[0] + right[0]) * 0.5
            midpoint_y = (left[1] + right[1]) * 0.5
            score = (
                vertical_delta / height * 8.0
                + abs(left[2] - right[2]) / max(left[2], right[2]) * 2.0
                + abs(midpoint_x / width - 0.5) * 2.0
                + abs(midpoint_y / height - 0.42) * 0.35
                - (left[2] + right[2]) / min_dim * 0.25
            )
            if score < best_score:
                best_score = score
                best_pair = [left, right]
    return best_pair


def _outline_fallback_paths_for_junctions(
    binary: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, list[list[tuple[int, int]]]]:
    """Outline compact branched components inside dynamically detected eye regions."""
    import cv2

    iris_pair = _detect_iris_pair(binary)
    if iris_pair is None:
        return binary, []
    eye_separation = iris_pair[1][0] - iris_pair[0][0]
    eye_windows: list[tuple[float, float, float, float]] = []
    for center_x, center_y, radius in iris_pair:
        half_width = max(radius * 3.5, eye_separation * 0.32)
        half_height = max(radius * 2.0, height * 0.035)
        eye_windows.append(
            (
                center_x - half_width,
                center_x + half_width,
                center_y - half_height,
                center_y + half_height,
            )
        )

    probe = skeletonize(binary)
    pixels = {(x, y) for y, x in np.argwhere(probe)}
    if not pixels:
        return binary, []
    branch_points = [point for point in pixels if len(_skeleton_neighbors(pixels, point)) >= 3]
    if not branch_points:
        return binary, []
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    selected: set[int] = set()
    for x, y in branch_points:
        if not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in eye_windows):
            continue
        label = int(labels[y, x])
        if label <= 0 or label in selected:
            continue
        _, _, component_w, component_h, area = stats[label]
        if (
            area >= 12
            and component_w <= max(24, int(width * 0.30))
            and component_h <= max(24, int(height * 0.16))
        ):
            selected.add(label)
    if not selected:
        return binary, []
    remaining = binary.copy()
    outline_paths: list[list[tuple[int, int]]] = []
    for label in selected:
        component = (labels == label).astype(np.uint8) * 255
        remaining[labels == label] = False
        contours, _ = cv2.findContours(component, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            if len(contour) < 8:
                continue
            points = [(int(point[0][0]), int(point[0][1])) for point in contour]
            if points[0] != points[-1]:
                points.append(points[0])
            outline_paths.append(points)
    return remaining, outline_paths


def _centerline_to_dxf(
    image_path: Path,
    dxf_path: Path | None,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    fit_box_width: float | None = None,
    fit_box_height: float | None = None,
    threshold: int = 128,
    smooth_iterations: int = 5,
    simplify_epsilon_px: float = 1.2,
    min_path_length_mm: float = 0.12,
    entity_mode: str = "polyline",
    max_steps: int = 800,
    smooth_before_simplify: bool = False,
    post_smooth_iterations: int = 0,
    prune_spurs_px: int = 5,
    min_path_px: int = 14,
    portrait_hair_suppression: bool = False,
    portrait_feature_protection: bool = False,
    preserve_junction_branches: bool = False,
    trace_mode: str = "centerline",
    junction_outline_fallback: bool = False,
    hybrid_fill_mode: str | None = None,
    fill_spacing_mm: float = 0.25,
    fill_wide_threshold_mm: float = 0.8,
    return_document: bool = False,
) -> int | tuple[int, object | None]:
    img = Image.open(image_path).convert("L")
    arr = np.array(img)
    height, width = arr.shape
    solid_binary = arr < threshold
    normalized_trace_mode = str(trace_mode).strip().lower()
    if normalized_trace_mode == "edge":
        # Trace the two visible boundaries of a thick black stroke instead of
        # collapsing the stroke to one medial-axis line.
        import cv2
        softened = cv2.GaussianBlur(arr, (3, 3), 0.45)
        binary = cv2.Canny(softened, 30, 90).astype(bool)
    else:
        binary = solid_binary.copy()
    if threshold >= 180 and normalized_trace_mode != "edge":
        # AI line-art can contain very light gray strokes. A fixed threshold loses
        # those strokes before pruning even starts, so add a local-contrast pass
        # that keeps faint lines on a near-white background.
        local_mean = np.array(img.filter(ImageFilter.BoxBlur(7)))
        faint_line = (arr < 238) & ((local_mean.astype(np.int16) - arr.astype(np.int16)) >= 5)
        binary = binary | faint_line
    if portrait_hair_suppression:
        binary = _portrait_mouth_bridge(binary)
    outline_fallback_paths: list[list[tuple[int, int]]] = []
    if junction_outline_fallback and normalized_trace_mode != "edge":
        binary, outline_fallback_paths = _outline_fallback_paths_for_junctions(binary, width, height)

    # Pixel coordinates span 0..width-1 and 0..height-1. These factors are also
    # used to convert the requested 0.25 mm fill spacing into source pixels.
    x_factor = scale_x / max(width - 1, 1)
    y_factor = scale_y / max(height - 1, 1)
    min_scale = min(x_factor, y_factor)
    fill_paths: list[list[tuple[int, int]]] = []
    if hybrid_fill_mode:
        fill_paths, fill_coverage = _build_hybrid_fill_paths(
            solid_binary,
            mm_per_px=min_scale,
            mode=hybrid_fill_mode,
            spacing_mm=fill_spacing_mm,
            wide_threshold_mm=fill_wide_threshold_mm,
        )
        if fill_coverage.any():
            import cv2

            spacing_px = max(1, round(fill_spacing_mm / max(min_scale, 1e-9)))
            coverage_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (3, max(3, spacing_px * 2 + 1))
            )
            covered_area = cv2.dilate(
                fill_coverage.astype(np.uint8), coverage_kernel, iterations=1
            ).astype(bool)
            # Confirmed filled pixels are removed from centerline extraction so a
            # block is not drawn twice as both a skeleton and a hatch pattern.
            binary = binary & ~covered_area

    skeleton = skeletonize(binary)
    skeleton = _prune_skeleton_spurs(skeleton, max_spur_px=prune_spurs_px)
    paths = _skeleton_paths(skeleton)
    if min_path_px > 0:
        paths = [path for path in paths if _pixel_path_length(path) >= float(min_path_px)]
    # New rule: only compact coarse intersections around the eyes fall back to
    # visible contour tracing; every other path uses the original pipeline.
    paths.extend(outline_fallback_paths)

    if not paths and not fill_paths:
        return (0, None) if return_document else 0

    doc = _new_compatible_dxf()
    msp = doc.modelspace()
    path_count = 0
    fill_entity_count = sum(max(0, len(path) - 1) for path in fill_paths)
    unlimited_steps = max_steps <= 0
    if not unlimited_steps and fill_entity_count > max_steps:
        raise RuntimeError(
            f"fill segment count {fill_entity_count} exceeds max_steps {max_steps}; "
            "increase DXF step limit or use a larger fill spacing"
        )
    centerline_max_steps = (2**63 - 1) if unlimited_steps else max(1, max_steps - fill_entity_count)

    # Pixel skeleton coordinates span 0..width-1 and 0..height-1. The scale can
    # be a fitted drawing size with offsets when preserving image aspect ratio.
    simplified_paths: list[list[Vec2]] = []
    epsilon_scale = 1.0
    step_count = 0
    while True:
        candidates: list[tuple[list[Vec2], float, float, int, float]] = []
        step_count = 0
        path_min_length = max(
            1.05 * min_scale,
            min_path_length_mm * (1.0 + max(0.0, epsilon_scale - 1.0) * 0.35),
        )
        for path in paths:
            if len(path) < 2:
                continue
            coords = [
                Vec2(offset_x + x * x_factor, offset_y + (height - 1 - y) * y_factor)
                for x, y in path
            ]
            if smooth_before_simplify:
                coords = _smooth_between_sharp_turns(coords, iterations=smooth_iterations)
            # Preserve the central eye/eyeglass region in portraits. These short
            # curves are identity-critical; other areas still absorb the cap.
            path_x = [point[0] for point in path]
            path_y = [point[1] for point in path]
            # Use the path centre, rather than any overlap. This protects the
            # eyes and glasses while leaving the face outline and hair available
            # for budget compression.
            path_center_x = (min(path_x) + max(path_x)) / 2.0
            path_center_y = (min(path_y) + max(path_y)) / 2.0
            in_feature_region = (
                portrait_feature_protection
                and width * 0.16 <= path_center_x <= width * 0.84
                and height * 0.22 <= path_center_y <= height * 0.56
            )
            local_epsilon_scale = min(epsilon_scale, 2.5) if in_feature_region else epsilon_scale
            coords = _rdp_simplify(
                coords,
                epsilon=max(simplify_epsilon_px * local_epsilon_scale * min(x_factor, y_factor), 0.0),
            )
            if smooth_before_simplify and post_smooth_iterations > 0:
                coords = _smooth_between_sharp_turns(coords, iterations=post_smooth_iterations)
            path_len = _polyline_length(coords)
            if path_len < path_min_length:
                continue
            if not smooth_before_simplify and not _has_sharp_turn(coords):
                coords = _chaikin_smooth(coords, iterations=smooth_iterations)
                coords = _rdp_simplify(
                    coords,
                    epsilon=max(simplify_epsilon_px * local_epsilon_scale * min(x_factor, y_factor), 0.0),
                )
                path_len = _polyline_length(coords)
                if path_len < path_min_length:
                    continue
            span = _path_span(coords)
            if entity_mode == "line_arc":
                primitive_count = len(_fit_line_arc_primitives(coords))
            elif entity_mode == "line":
                primitive_count = max(0, len(coords) - 1)
            elif entity_mode == "spline":
                primitive_count = 1
            else:
                primitive_count = 1
            if primitive_count <= 0:
                continue
            keep_priority = _path_keep_priority(
                coords,
                path_len,
                span,
                primitive_count,
                scale_x,
                scale_y,
                portrait_hair_suppression=portrait_hair_suppression,
            )
            candidates.append((coords, path_len, span, primitive_count, keep_priority))
            step_count += primitive_count

        if entity_mode == "line_arc" and step_count > centerline_max_steps:
            if fit_box_width and fit_box_height and candidates:
                fitted_for_priority = _fit_vec2_paths_to_box(
                    [coords for coords, _, _, _, _ in candidates],
                    fit_box_width,
                    fit_box_height,
                )
                candidates = [
                    (
                        coords,
                        path_len,
                        span,
                        primitive_count,
                        _path_keep_priority(
                            fitted_coords,
                            _polyline_length(fitted_coords),
                            _path_span(fitted_coords),
                            primitive_count,
                            fit_box_width,
                            fit_box_height,
                            portrait_hair_suppression=portrait_hair_suppression,
                        ),
                    )
                    for (coords, path_len, span, primitive_count, _), fitted_coords in zip(candidates, fitted_for_priority)
                ]
            kept = sorted(candidates, key=lambda item: (item[4], item[1], item[2], item[3]))
            while step_count > centerline_max_steps and len(kept) > 1:
                _, _, _, removed_steps, _ = kept.pop(0)
                step_count -= removed_steps
            candidates = kept

        simplified_paths = [coords for coords, _, _, _, _ in candidates]
        # With portrait protection enabled, keep the eye/eyeglass region at its
        # local cap and continue simplifying only the remaining image until the
        # shared controller budget is met.
        epsilon_limit = 40.0 if portrait_feature_protection and entity_mode == "line" else 14.0
        if entity_mode not in {"line_arc", "line"} or step_count <= centerline_max_steps or epsilon_scale >= epsilon_limit:
            break
        epsilon_scale *= 1.35

    fill_vec_paths = [
        [
            Vec2(offset_x + x * x_factor, offset_y + (height - 1 - y) * y_factor)
            for x, y in fill_path
        ]
        for fill_path in fill_paths
    ]
    if fit_box_width and fit_box_height and (candidates or fill_vec_paths):
        centerline_count = len(candidates)
        fitted_paths = _fit_vec2_paths_to_box(
            [coords for coords, _, _, _, _ in candidates] + fill_vec_paths,
            fit_box_width,
            fit_box_height,
        )
        fitted_centerlines = fitted_paths[:centerline_count]
        fill_vec_paths = fitted_paths[centerline_count:]
        candidates = [
            (
                coords,
                _polyline_length(coords),
                _path_span(coords),
                primitive_count,
                _path_keep_priority(
                    coords,
                    _polyline_length(coords),
                    _path_span(coords),
                    primitive_count,
                    fit_box_width,
                    fit_box_height,
                    portrait_hair_suppression=portrait_hair_suppression,
                ),
            )
            for coords, (_, _, _, primitive_count, _) in zip(fitted_centerlines, candidates)
        ]
        simplified_paths = [coords for coords, _, _, _, _ in candidates]

    if entity_mode == "line_arc":
        primitive_groups: list[tuple[list[tuple], float]] = []
        for coords, path_len, span, _, keep_priority in candidates:
            primitives = _fit_line_arc_primitives(coords)
            if not primitives:
                continue
            primitive_groups.append((primitives, keep_priority))

        final_count = sum(len(primitives) for primitives, _ in primitive_groups)
        if final_count > centerline_max_steps:
            kept_groups = sorted(primitive_groups, key=lambda item: (item[1], len(item[0])))
            while final_count > centerline_max_steps and len(kept_groups) > 1:
                primitives, _ = kept_groups.pop(0)
                final_count -= len(primitives)
            primitive_groups = kept_groups

        for primitives, _ in primitive_groups:
            for prim in primitives:
                if prim[0] == "LINE":
                    _, p0, p1 = prim
                    if p0.distance(p1) <= 1e-9:
                        continue
                    msp.add_point((p0.x, p0.y), dxfattribs={"color": 3})
                    path_count += 1
                    msp.add_line((p0.x, p0.y), (p1.x, p1.y), dxfattribs={"color": 7})
                    path_count += 1
                else:
                    _, p0, pm, p1, center, radius, sa, ea = prim
                    msp.add_arc((center.x, center.y), radius, sa, ea, dxfattribs={"color": 7})
                    path_count += 1
                    msp.add_point((p0.x, p0.y), dxfattribs={"color": 3})
                    msp.add_point((pm.x, pm.y), dxfattribs={"color": 4})
                    msp.add_point((p1.x, p1.y), dxfattribs={"color": 1})
                    path_count += 3
    else:
        if entity_mode == "line":
            total_segments = sum(item[3] for item in candidates)
            if total_segments > centerline_max_steps:
                raise RuntimeError(
                    f"line segment count {total_segments} exceeds remaining max_steps "
                    f"{centerline_max_steps}; "
                    "increase DXF step limit or simplify the source image"
                )
            simplified_paths = [coords for coords, _, _, _, _ in candidates]

        for coords in simplified_paths:
            if entity_mode == "line":
                segment_count = 0
                for p0, p1 in zip(coords[:-1], coords[1:]):
                    if p0.distance(p1) <= 1e-9:
                        continue
                    msp.add_line((p0.x, p0.y), (p1.x, p1.y), dxfattribs={"color": 7})
                    segment_count += 1
                if segment_count > 0:
                    path_count += segment_count
            elif entity_mode == "spline":
                fit_points = [(p.x, p.y) for p in coords]
                if len(fit_points) == 2:
                    msp.add_line(fit_points[0], fit_points[1], dxfattribs={"color": 7})
                else:
                    msp.add_spline(fit_points=fit_points)
                path_count += 1
            else:
                msp.add_lwpolyline(coords, close=False)
                path_count += 1

    # Each serpentine path is emitted as exactly connected LINE entities on the
    # FILL layer. The downstream planner joins their shared endpoints, producing
    # one pen-down/pen-up pair per filled branch instead of one pair per scan row.
    for mapped in fill_vec_paths:
        for p0, p1 in zip(mapped, mapped[1:]):
            if p0.distance(p1) <= 1e-9:
                continue
            msp.add_line(
                (p0.x, p0.y),
                (p1.x, p1.y),
                dxfattribs={"layer": "FILL", "color": 7},
            )
            path_count += 1

    if path_count > 0 and dxf_path is not None:
        doc.saveas(str(dxf_path))
        _normalize_dxf_text_for_controller(dxf_path)
        _write_dxf_stats_txt(dxf_path)

    return (path_count, doc) if return_document else path_count


def _trace_with_potrace(pbm_path: Path) -> Path:
    svg_path = pbm_path.with_suffix(".svg")
    cmd = ["potrace", str(pbm_path), "-s", "-o", str(svg_path)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return svg_path


def _svg_to_dxf(
    svg_path: Path,
    dxf_path: Path,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    fit_box_width: float | None = None,
    fit_box_height: float | None = None,
    source_width: float | None = None,
    source_height: float | None = None,
    samples_per_curve: int = 40,
    entity_mode: str = "polyline",
) -> int:
    paths, _, _ = svg2paths2(str(svg_path))
    if not paths:
        return 0

    doc = _new_compatible_dxf()
    msp = doc.modelspace()
    path_count = 0
    x_factor = scale_x / max(source_width or 1.0, 1.0)
    y_factor = scale_y / max(source_height or 1.0, 1.0)
    simplified_paths: list[tuple[list[Vec2], bool]] = []

    for path in paths:
        coords = []
        for segment in path:
            for i in range(samples_per_curve + 1):
                t = i / samples_per_curve
                point = segment.point(t)
                coords.append((offset_x + point.real * x_factor, offset_y + point.imag * y_factor))

        if not coords:
            continue

        simplified = [Vec2(*coords[0])]
        for pt in coords[1:]:
            if Vec2(*pt).distance(simplified[-1]) > 0.1:
                simplified.append(Vec2(*pt))

        if len(simplified) >= 2:
            is_closed = simplified[0].distance(simplified[-1]) <= 0.5
            simplified_paths.append((simplified, is_closed))

    if fit_box_width and fit_box_height and simplified_paths:
        fitted_paths = _fit_vec2_paths_to_box(
            [coords for coords, _ in simplified_paths],
            fit_box_width,
            fit_box_height,
        )
        simplified_paths = [
            (coords, is_closed)
            for coords, (_, is_closed) in zip(fitted_paths, simplified_paths)
        ]

    for simplified, is_closed in simplified_paths:
        if entity_mode == "line":
            segment_count = 0
            pts = simplified + ([simplified[0]] if is_closed else [])
            for p0, p1 in zip(pts[:-1], pts[1:]):
                if p0.distance(p1) <= 1e-9:
                    continue
                msp.add_line((p0.x, p0.y), (p1.x, p1.y), dxfattribs={"color": 7})
                segment_count += 1
            if segment_count > 0:
                path_count += segment_count
        elif entity_mode == "spline":
            fit_points = [(p.x, p.y) for p in simplified]
            if is_closed and simplified[0].distance(simplified[-1]) > 1e-9:
                fit_points.append((simplified[0].x, simplified[0].y))
            if len(fit_points) == 2:
                msp.add_line(fit_points[0], fit_points[1], dxfattribs={"color": 7})
            else:
                msp.add_spline(fit_points=fit_points)
            path_count += 1
        else:
            msp.add_lwpolyline(simplified, close=is_closed)
            path_count += 1

    if path_count > 0:
        doc.saveas(str(dxf_path))
        _normalize_dxf_text_for_controller(dxf_path)
        _write_dxf_stats_txt(dxf_path)
    return path_count


def convert_image_to_dxf(
    image_path: str | Path,
    output_path: str | Path | None = None,
    keep_intermediate: bool = False,
    target_width_mm: float | None = None,
    target_height_mm: float | None = None,
    dpi: float | None = None,
    centerline: bool = False,
    centerline_threshold: int = 128,
    centerline_smooth_iterations: int = 5,
    centerline_simplify_epsilon_px: float = 1.2,
    centerline_min_path_length_mm: float = 0.12,
    centerline_prune_spurs_px: int = 5,
    centerline_min_path_px: int = 14,
    dxf_entity_mode: str = "polyline",
    max_steps: int = 800,
    portrait_hair_suppression: bool = False,
    portrait_feature_protection: bool = False,
    preserve_junction_branches: bool = False,
    trace_mode: str = "centerline",
    junction_outline_fallback: bool = False,
    hybrid_fill_mode: str | None = None,
    fill_spacing_mm: float = 0.25,
    fill_wide_threshold_mm: float = 0.8,
    return_document: bool = False,
) -> tuple[bool, Path | None] | tuple[bool, Path | None, object | None]:
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    if output_path is None and not return_document:
        output_path = image_path.with_suffix(".dxf")
    elif output_path is not None:
        output_path = Path(output_path)

    try:
        scale_x = 1.0
        scale_y = 1.0
        offset_x = 0.0
        offset_y = 0.0
        width_px = None
        height_px = None
        if target_width_mm and target_height_mm:
            img = Image.open(image_path)
            width_px, height_px = img.size
            if width_px <= 0 or height_px <= 0:
                raise ValueError("invalid image size for mapping")
            # Fit the full raster into the requested DXF box without changing
            # image aspect ratio. This avoids compressing square AI outputs into
            # rectangular robot work ranges.
            source_span_x = max(width_px - 1, 1)
            source_span_y = max(height_px - 1, 1)
            fit_factor = min(float(target_width_mm) / source_span_x, float(target_height_mm) / source_span_y)
            scale_x = source_span_x * fit_factor
            scale_y = source_span_y * fit_factor
            offset_x = (float(target_width_mm) - scale_x) / 2.0
            offset_y = (float(target_height_mm) - scale_y) / 2.0

        if centerline:
            centerline_result = _centerline_to_dxf(
                image_path,
                output_path,
                scale_x=scale_x,
                scale_y=scale_y,
                offset_x=offset_x,
                offset_y=offset_y,
                fit_box_width=target_width_mm,
                fit_box_height=target_height_mm,
                threshold=centerline_threshold,
                smooth_iterations=centerline_smooth_iterations,
                simplify_epsilon_px=centerline_simplify_epsilon_px,
                min_path_length_mm=centerline_min_path_length_mm,
                entity_mode=dxf_entity_mode,
                max_steps=max_steps,
                prune_spurs_px=centerline_prune_spurs_px,
                min_path_px=centerline_min_path_px,
                portrait_hair_suppression=portrait_hair_suppression,
                portrait_feature_protection=portrait_feature_protection,
                preserve_junction_branches=preserve_junction_branches,
                trace_mode=trace_mode,
                junction_outline_fallback=junction_outline_fallback,
                hybrid_fill_mode=hybrid_fill_mode,
                fill_spacing_mm=fill_spacing_mm,
                fill_wide_threshold_mm=fill_wide_threshold_mm,
                return_document=return_document,
            )
            if return_document:
                path_count, document = centerline_result
            else:
                path_count = centerline_result
                document = None
        else:
            if shutil.which("potrace") is None:
                raise RuntimeError("potrace not found in PATH")
            pbm_path = _convert_to_pbm(image_path)
            svg_path = _trace_with_potrace(pbm_path)
            try:
                path_count = _svg_to_dxf(
                    svg_path,
                    output_path,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    fit_box_width=target_width_mm,
                    fit_box_height=target_height_mm,
                    source_width=width_px,
                    source_height=height_px,
                    entity_mode=dxf_entity_mode,
                )
            finally:
                if not keep_intermediate:
                    pbm_path.unlink(missing_ok=True)
                    svg_path.unlink(missing_ok=True)
        ok = path_count > 0
    finally:
        if output_path is not None:
            _cleanup_stale_dxf_variants(output_path)

    if return_document:
        return ok, output_path if ok else None, document if ok else None
    return ok, output_path if ok else None
