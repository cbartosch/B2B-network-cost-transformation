BUILD = "4.27.0"
# Kept in sync with the top-level VERSION file by hand - there is no single
# source of truth between them yet. VERSION isn't copied into the API image
# (see api_service/Dockerfile), so this can't simply read it at import time
# without a Dockerfile change too. This drifted to "4.7.1-scaffold" for many
# builds before anyone noticed /v1/health was reporting it - bump this
# alongside VERSION until that's fixed properly, not patched again.
