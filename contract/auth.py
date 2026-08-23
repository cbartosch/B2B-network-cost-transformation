"""The API/UI authentication contract.

This file is copied into both images. It exists because C2-04 was two halves
that never met: the API enforced a header the Streamlit client never sent, and
each side was entirely plausible on its own. A test could have caught the
mismatch, but a single definition means there is nothing to mismatch.

Nothing secret lives here - only the shape of the agreement.
"""

# Header carrying the shared secret.
AUTH_HEADER = "X-API-Token"

# Routes reachable without a token. Both are probes carrying no engagement data:
#
#   /v1/health   liveness. The UI also reads auth_required from it to tell the
#                operator when the two sides are misconfigured.
#   /v1/ready    readiness. The container healthcheck polls it and cannot send
#                a header, so requiring one would mark the container unhealthy
#                forever the moment a token was configured.
#
# Nothing else belongs here - an earlier version also exempted /docs and
# /openapi.json, which published the API surface while a token was configured.
AUTH_EXEMPT_PATHS = frozenset({"/v1/health", "/v1/ready"})
