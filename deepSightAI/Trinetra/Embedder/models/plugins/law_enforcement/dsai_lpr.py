"""
Canonical LPR plugin re-export under law_enforcement namespace (VP-18).
"""

from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_lpr import (
    LPRPlugin,
    dsai_create_sample_plate_image,
)

__all__ = ["LPRPlugin", "dsai_create_sample_plate_image"]
