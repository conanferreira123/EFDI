"""
Adaptive Preprocessing Engine.

Analyzes image quality metrics (resolution, brightness, contrast, sharpness, skew)
and applies targeted preprocessing operations ONLY when objectively justified.
Avoids destructive transformations or unnecessary operations on clean digital documents.
"""
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


@dataclass
class ImageQualityMetrics:
    """Quantitative image quality metrics."""
    width: int
    height: int
    mean_brightness: float       # Grayscale mean [0.0 - 255.0]
    contrast_std: float          # Grayscale standard deviation [0.0 - 128.0]
    sharpness_laplacian: float   # Laplacian variance (higher = sharper)
    estimated_skew_angle: float  # Degrees from horizontal [-45.0 to 45.0]
    is_low_contrast: bool
    is_blurry: bool
    is_skewed: bool
    is_clean_digital: bool       # High sharpness, optimal contrast, zero skew

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PreprocessingDecision:
    """Record of preprocessing actions performed and justification."""
    strategy_name: str
    operations_applied: List[str]
    metrics: ImageQualityMetrics
    rationale: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "operations_applied": self.operations_applied,
            "metrics": self.metrics.to_dict(),
            "rationale": self.rationale,
        }


class ImageQualityAnalyzer:
    """Analyzes raw image quality without modifying the image."""

    @staticmethod
    def estimate_skew(gray: np.ndarray) -> float:
        """Estimate document skew angle using Hough line transform."""
        try:
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
            if lines is None:
                return 0.0

            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if x2 - x1 == 0:
                    continue
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                if abs(angle) < 45.0:
                    angles.append(angle)

            if not angles:
                return 0.0
            return float(np.median(angles))
        except Exception:
            return 0.0

    @classmethod
    def analyze(cls, image: np.ndarray) -> ImageQualityMetrics:
        h, w = image.shape[:2]
        if len(image.shape) == 3 and image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        skew_angle = cls.estimate_skew(gray)

        is_low_contrast = contrast < 35.0
        is_blurry = laplacian_var < 80.0
        is_skewed = abs(skew_angle) > 0.8
        is_clean_digital = (laplacian_var > 200.0 and contrast > 45.0 and abs(skew_angle) < 0.5)

        return ImageQualityMetrics(
            width=w,
            height=h,
            mean_brightness=round(brightness, 2),
            contrast_std=round(contrast, 2),
            sharpness_laplacian=round(laplacian_var, 2),
            estimated_skew_angle=round(skew_angle, 2),
            is_low_contrast=is_low_contrast,
            is_blurry=is_blurry,
            is_skewed=is_skewed,
            is_clean_digital=is_clean_digital,
        )


class AdaptivePreprocessor:
    """Applies selective preprocessing based on measured quality metrics."""

    @staticmethod
    def rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    @classmethod
    def process(cls, image: np.ndarray) -> Tuple[np.ndarray, PreprocessingDecision]:
        metrics = ImageQualityAnalyzer.analyze(image)
        operations: List[str] = []
        rationale: List[str] = []
        processed = image.copy()

        # 1. Clean digital born documents (e.g. vector rendered PDFs)
        if metrics.is_clean_digital:
            return processed, PreprocessingDecision(
                strategy_name="PASS_THROUGH_CLEAN_DIGITAL",
                operations_applied=[],
                metrics=metrics,
                rationale=["Image is high-contrast, sharp, un-skewed digital render; no filter needed."],
            )

        # 2. Deskew if measured skew exceeds tolerance
        if metrics.is_skewed:
            processed = cls.rotate_image(processed, -metrics.estimated_skew_angle)
            operations.append(f"DESKEW({-metrics.estimated_skew_angle:.1f}deg)")
            rationale.append(f"Corrected document tilt of {metrics.estimated_skew_angle:.1f} degrees.")

        # 3. Contrast adjustment for faded/low-contrast scans
        if metrics.is_low_contrast:
            if len(processed.shape) == 3:
                lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                processed = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
            else:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                processed = clahe.apply(processed)
            operations.append("CLAHE_CONTRAST_ENHANCEMENT")
            rationale.append(f"Enhanced low contrast (std={metrics.contrast_std:.1f} < 35.0).")

        strategy = "ADAPTIVE_ENHANCED" if operations else "STANDARD_PASSTHROUGH"

        return processed, PreprocessingDecision(
            strategy_name=strategy,
            operations_applied=operations,
            metrics=metrics,
            rationale=rationale,
        )
