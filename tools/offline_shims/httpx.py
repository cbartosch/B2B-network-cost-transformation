"""Import-only httpx shim - no network, and never silently succeeds."""
class HTTPError(Exception): pass
class TimeoutException(HTTPError): pass
class Client:
    """Records the configuration the transport tests inspect, and refuses any
    actual request. `follow_redirects`, `trust_env`, `verify` and `proxy` are
    real attributes because _transport.py sets them deliberately and the tests
    assert on them - reporting a default would make those assertions
    meaningless."""

    def __init__(self, *a, **k):
        self.follow_redirects = k.get("follow_redirects", False)
        self.trust_env = k.get("trust_env", True)
        self.verify = k.get("verify", True)
        self.timeout = k.get("timeout")
        self.proxy = k.get("proxy") or k.get("proxies")
        self.transport = k.get("transport")
        self.headers = k.get("headers", {})

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, *a, **k): raise HTTPError("httpx shim: no network")
    def post(self, *a, **k): raise HTTPError("httpx shim: no network")
    def request(self, *a, **k): raise HTTPError("httpx shim: no network")
    def close(self): pass
def get(*a, **k): raise HTTPError("httpx shim: no network")
