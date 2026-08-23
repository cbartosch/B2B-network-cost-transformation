class ProviderUnavailable(RuntimeError):
    """No usable provider. A LIVE run FAILS - it never falls back to canned output."""

class LivenessProofFailed(RuntimeError):
    """The provider record does not prove a real call happened (spec 7.2C)."""

class ModeNotPermitted(RuntimeError):
    """Execution mode rejected for this environment or agent (spec 7.2C)."""

class StructuredOutputInvalid(RuntimeError):
    """Model output did not satisfy the schema. Abstain rather than invent (spec 7.3)."""
