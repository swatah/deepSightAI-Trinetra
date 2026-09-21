"""
T2.1.3 / VP-18: License Plate Recognition plugin (law_enf).

Canonical implementation is in deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_lpr.
"""

from deepSightAI.Trinetra.Embedder.models.plugins.law_enforcement.dsai_lpr import (
    LPRPlugin,
    dsai_create_sample_plate_image,
)

__all__ = ["LPRPlugin", "dsai_create_sample_plate_image"]
