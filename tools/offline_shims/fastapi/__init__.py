"""A FastAPI subset with a TestClient that really routes.

Scope: `APIRouter`, `FastAPI`, `HTTPException`, `Body`, `Response`, `Depends`,
middleware, lifespan, and a `TestClient` that performs genuine path matching,
path/query parameter binding, JSON body -> pydantic model validation, and
middleware traversal. Handlers are called exactly as the server would call
them, so an auth middleware that rejects a request rejects it here too.

Not implemented, and refused rather than approximated: streaming, websockets,
background tasks, `response_model` coercion, dependency caching, sub-apps,
and file uploads. Anything unhandled raises rather than returning a plausible
response - a TestClient that silently returns 200 for a route it failed to
match would make every wiring test meaningless.

Verified by `tools/verify_shim.py`.
"""
import inspect
import json as _json
import re
import typing

from pydantic import BaseModel, ValidationError


class _Unsupported(RuntimeError):
    pass


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(f"{status_code}: {detail}")


class Response:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None):
        self.body = content
        self.status_code = status_code
        self.headers = headers or {}
        self.media_type = media_type


class JSONResponse(Response):
    def __init__(self, content=None, status_code=200, **kw):
        super().__init__(content=content, status_code=status_code, **kw)
        self._payload = content


def Body(default=..., **kw):                             # noqa: N802
    return default


def Query(default=..., **kw):                            # noqa: N802
    return default


def Depends(dependency=None):                            # noqa: N802
    raise _Unsupported(
        "Depends() is not implemented by this shim; the application does not "
        "use it, and approximating dependency injection would be guesswork")


class _Route:
    def __init__(self, method, path, fn):
        self.method, self.path, self.fn = method.upper(), path, fn
        # /v1/cases/{case_id}/x -> regex with a named group per parameter
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path)
        self.regex = re.compile(f"^{pattern}$")
        self.params = re.findall(r"\{(\w+)\}", path)


class APIRouter:
    def __init__(self, **kw):
        self.routes: list[_Route] = []

    def _add(self, method, path):
        def deco(fn):
            self.routes.append(_Route(method, path, fn))
            return fn
        return deco

    def get(self, path, **kw): return self._add("GET", path)
    def post(self, path, **kw): return self._add("POST", path)
    def put(self, path, **kw): return self._add("PUT", path)
    def delete(self, path, **kw): return self._add("DELETE", path)
    def patch(self, path, **kw): return self._add("PATCH", path)


class FastAPI:
    def __init__(self, **kw):
        self.routes: list[_Route] = []
        self.user_middleware = []
        self._lifespan = kw.get("lifespan")
        self._exception_handlers = {}
        self.state = type("State", (), {})()

    def include_router(self, router, **kw):
        self.routes.extend(router.routes)

    def middleware(self, kind):
        def deco(fn):
            self.user_middleware.append(fn)
            return fn
        return deco

    def exception_handler(self, exc_class):
        def deco(fn):
            self._exception_handlers[exc_class] = fn
            return fn
        return deco

    def add_middleware(self, cls, **kw):
        raise _Unsupported(
            "class-based middleware is not implemented; this application uses "
            "the @app.middleware('http') form")

    def get(self, path, **kw): return APIRouter._add(self, "GET", path)
    def post(self, path, **kw): return APIRouter._add(self, "POST", path)

    def _add(self, method, path):
        def deco(fn):
            self.routes.append(_Route(method, path, fn))
            return fn
        return deco


Request = None   # rebound below, after the class is defined


class _CaseInsensitive(dict):
    def __init__(self, data):
        super().__init__({k.lower(): v for k, v in data.items()})
    def get(self, key, default=None):
        return super().get(key.lower(), default)
    def __getitem__(self, key):
        return super().__getitem__(key.lower())
    def __contains__(self, key):
        return super().__contains__(key.lower())


class _Request:
    def __init__(self, method, path, query, headers, body):
        self.method = method
        self.url = type("U", (), {"path": path, "query": query})()
        # Case-INSENSITIVE, as Starlette's Headers are. Storing lowercased keys
        # in a plain dict looked equivalent and was not: the auth middleware
        # looks up config.AUTH_HEADER ("X-API-Token") with its original case, so
        # every lookup missed, every token compared against "", and three auth
        # tests failed for a reason that had nothing to do with auth.
        self.headers = _CaseInsensitive(headers or {})
        self._body = body
        self.state = type("S", (), {})()
        self.scope = {"path": path, "method": method}

    async def json(self):
        return _json.loads(self._body) if self._body else None

    async def body(self):
        return (self._body or "").encode()


Request = _Request


class _TestResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    @property
    def text(self):
        return _json.dumps(self._payload) if self._payload is not None else ""


def _coerce_scalar(value, ann):
    if ann is int:
        return int(value)
    if ann is bool:
        return value in (True, "true", "True", "1", 1)
    if ann is float:
        return float(value)
    if ann is str or ann is inspect.Parameter.empty:
        return value
    origin = typing.get_origin(ann)
    if origin is typing.Union:
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if value is None:
            return None
        return _coerce_scalar(value, args[0]) if args else value
    return value


class TestClient:
    """Drives the app the way the server does: middleware, then the matched
    handler, with parameters bound from the path, the query string and the
    JSON body."""

    def __init__(self, app, raise_server_exceptions=True):
        self.app = app
        self._raise = raise_server_exceptions

    def __enter__(self):
        lifespan = getattr(self.app, "_lifespan", None)
        if lifespan is not None:
            self._cm = lifespan(self.app)
            # The application's lifespan is an async generator; drive it to the
            # first yield so startup work really runs.
            import asyncio
            self._loop = asyncio.new_event_loop()
            self._agen = self._cm.__aenter__()
            self._loop.run_until_complete(self._agen)
        return self

    def __exit__(self, *exc):
        cm = getattr(self, "_cm", None)
        if cm is not None:
            try:
                self._loop.run_until_complete(cm.__aexit__(None, None, None))
            except Exception:                            # noqa: BLE001
                pass
            self._loop.close()
        return False

    # -- verbs
    def get(self, path, **kw): return self.request("GET", path, **kw)
    def post(self, path, **kw): return self.request("POST", path, **kw)
    def put(self, path, **kw): return self.request("PUT", path, **kw)
    def delete(self, path, **kw): return self.request("DELETE", path, **kw)

    def request(self, method, path, json=None, headers=None, params=None):
        query = params or {}
        if "?" in path:
            path, _, qs = path.partition("?")
            for pair in qs.split("&"):
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    query[k] = v
        body = _json.dumps(json) if json is not None else None
        request = _Request(method, path, query, headers, body)

        def _call_endpoint(req):
            return self._dispatch(method, path, query, json)

        handler = _call_endpoint
        for mw in reversed(self.app.user_middleware):
            handler = _wrap_middleware(mw, handler)
        result = handler(request)
        return result


def _wrap_middleware(mw, nxt):
    import asyncio

    def call(request):
        async def call_next(req):
            return _as_response(nxt(req))
        out = mw(request, call_next)
        if inspect.iscoroutine(out):
            loop = asyncio.new_event_loop()
            try:
                out = loop.run_until_complete(out)
            finally:
                loop.close()
        return _as_test_response(out)
    return call


def _as_response(result):
    """A middleware's call_next must receive something with .status_code."""
    if isinstance(result, _TestResponse):
        r = Response(status_code=result.status_code)
        r._payload = result._payload
        r.headers = result.headers
        return r
    return result


def _as_test_response(out):
    if isinstance(out, _TestResponse):
        return out
    if isinstance(out, Response):
        payload = getattr(out, "_payload", None)
        if payload is None and isinstance(out.body, (dict, list)):
            payload = out.body
        elif payload is None and isinstance(out.body, (str, bytes)):
            try:
                payload = _json.loads(out.body)
            except Exception:                            # noqa: BLE001
                payload = {"detail": out.body if isinstance(out.body, str)
                           else out.body.decode()}
        return _TestResponse(out.status_code, payload, out.headers)
    raise _Unsupported(f"middleware returned {type(out).__name__}")


def _dispatch_impl(app, method, path, query, json_body, raise_server_exceptions):
    for route in app.routes:
        if route.method != method:
            continue
        m = route.regex.match(path)
        if not m:
            continue
        sig = inspect.signature(route.fn)
        kwargs, injected = {}, None
        for name, param in sig.parameters.items():
            ann = param.annotation
            if ann is Response:
                # FastAPI injects a mutable Response for handlers that declare
                # one, so a handler can set status_code itself. /v1/ready does
                # exactly that to return 503 on a database outage.
                kwargs[name] = injected = Response()
                continue
            if name in m.groupdict():
                kwargs[name] = _coerce_scalar(m.group(name), ann)
            elif isinstance(ann, type) and issubclass(ann, BaseModel):
                try:
                    kwargs[name] = ann(**(json_body or {}))
                except ValidationError as e:
                    return _TestResponse(422, {"detail": str(e)})
            elif (typing.get_origin(ann) is list
                  and typing.get_args(ann)
                  and isinstance(typing.get_args(ann)[0], type)
                  and issubclass(typing.get_args(ann)[0], BaseModel)):
                inner = typing.get_args(ann)[0]
                try:
                    kwargs[name] = [inner(**row) for row in (json_body or [])]
                except ValidationError as e:
                    return _TestResponse(422, {"detail": str(e)})
            elif name in query:
                kwargs[name] = _coerce_scalar(query[name], ann)
            elif param.default is not inspect.Parameter.empty:
                kwargs[name] = param.default
            elif ann is not inspect.Parameter.empty and json_body is not None:
                kwargs[name] = json_body
            else:
                return _TestResponse(422, {"detail": f"missing parameter {name}"})
        try:
            out = route.fn(**kwargs)
        except HTTPException as e:
            return _TestResponse(e.status_code, {"detail": e.detail})
        except Exception:
            if raise_server_exceptions:
                raise
            return _TestResponse(500, {"detail": "internal server error"})
        if isinstance(out, Response):
            return _TestResponse(out.status_code, getattr(out, "_payload", None)
                                 or getattr(out, "body", None))
        # A handler that mutated an injected Response sets the status that way.
        status = injected.status_code if injected is not None else 200
        return _TestResponse(status, out)
    return _TestResponse(404, {"detail": "Not Found"})


TestClient._dispatch = lambda self, method, path, query, json_body: _dispatch_impl(
    self.app, method, path, query, json_body, self._raise)
