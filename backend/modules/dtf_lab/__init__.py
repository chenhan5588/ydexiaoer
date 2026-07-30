"""DTF single-image prototype.

The lab intentionally uses a conservative pipeline: preserve source colours,
remove only border-connected flat backgrounds, standardise the output, and
flag risky work for a human instead of inventing text or logo details.
"""

from .pipeline import run_pipeline

__all__ = ["run_pipeline"]
