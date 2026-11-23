"""Engine #6 V2 building blocks (offline, deterministic, stdlib only).

Currently contains only evidence preparation (``evidence_prep``). Nothing in the existing
deterministic Engine #6 imports this package, importing it performs no I/O, and it contains no
AI extraction, verification, budget or queue logic.
"""

from .evidence_prep import (
    EvidencePassage, EvidencePrepResult, PrepConfig, prepare_evidence, redact_contact_details,
)

__all__ = ["EvidencePassage", "EvidencePrepResult", "PrepConfig", "prepare_evidence",
           "redact_contact_details"]
