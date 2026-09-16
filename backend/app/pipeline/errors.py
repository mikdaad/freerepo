"""Pipeline error type — carries the phase number so the orchestrator can
report exactly which step failed to the dashboard."""


class PipelineError(RuntimeError):
    """Fatal, user-facing error raised inside a pipeline phase."""

    def __init__(self, phase: int, message: str) -> None:
        super().__init__(message)
        self.phase = phase
        self.message = message
