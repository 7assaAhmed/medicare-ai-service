"""
Basic image quality gate — runs BEFORE the (expensive) AI call.
Rejects images that are too blurry, too dark, or too small to be worth
sending to the model at all. This saves API cost and gives the user a
faster, more specific error than "the model couldn't read it".
"""
from __future__ import annotations
import io
import numpy as np
from PIL import Image
import cv2

from app.models.schemas import ImageQuality


def assess_image_quality(image_bytes: bytes) -> ImageQuality:
    issues: list[str] = []

    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ImageQuality(score=0.0, issues=["unreadable_file"])

    width, height = pil_img.size
    shortest_side = min(width, height)
    if shortest_side < 600:
        issues.append("resolution_too_low")

    np_img = np.array(pil_img)
    gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)

    # Blur detection: variance of the Laplacian. Low variance = blurry.
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = min(laplacian_var / 500.0, 1.0)  # 500 chosen empirically; tune with real samples
    if blur_score < 0.3:
        issues.append("blurry")

    # Brightness / contrast check.
    mean_brightness = gray.mean()
    if mean_brightness < 40:
        issues.append("too_dark")
    elif mean_brightness > 235:
        issues.append("overexposed")

    std_contrast = gray.std()
    contrast_score = min(std_contrast / 60.0, 1.0)
    if contrast_score < 0.3:
        issues.append("low_contrast")

    resolution_score = min(shortest_side / 1080.0, 1.0)

    # Combine into a single 0-1 score.
    overall = round(0.4 * blur_score + 0.3 * contrast_score + 0.3 * resolution_score, 2)

    return ImageQuality(score=overall, issues=issues)
