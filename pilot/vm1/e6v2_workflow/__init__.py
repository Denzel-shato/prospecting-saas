"""Engine #6 V2 offline workflow: saved snapshots -> evidence prep -> MockProvider -> verification.

Offline only: the provider must be the MockProvider (anything else is refused before it is called), nothing
crawls, and nothing in the existing Engine #6 imports this package.
"""

from .workflow import WorkflowResult, load_snapshots, run_offline

__all__ = ["WorkflowResult", "load_snapshots", "run_offline"]
