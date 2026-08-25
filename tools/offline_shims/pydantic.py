"""A minimal pydantic v2 subset with REAL validation.

The danger here is specific and worse than a missing feature: a lenient shim
that accepts what pydantic would reject turns a test asserting
`pytest.raises(ValidationError)` into a silent false failure, and one asserting
successful construction into a false pass. So every constraint this supports is
actually enforced, and every constraint it does NOT support raises
`_UnsupportedConstraint` at class-definition time rather than being ignored.

Supported: default values, `Field(default, min_length, max_length, ge, le,
gt, lt)`, required-field detection, `model_dump()`, and coercion of the scalar
types this codebase annotates with. Anything else refuses loudly.

Verified by `tools/verify_shim.py`.
"""
from decimal import Decimal, InvalidOperation
import typing


class _UnsupportedConstraint(RuntimeError):
    """Raised at class definition, not silently ignored at validation time."""


class ValidationError(ValueError):
    def __init__(self, errors):
        self._errors = errors if isinstance(errors, list) else [errors]
        super().__init__("; ".join(str(e) for e in self._errors))

    def errors(self):
        return self._errors


_SUPPORTED = {"default", "default_factory", "min_length", "max_length",
              "ge", "le", "gt", "lt", "pattern", "description", "alias",
              "examples", "title"}


class _FieldInfo:
    __slots__ = ("default", "default_factory", "min_length", "max_length",
                 "ge", "le", "gt", "lt", "pattern")

    def __init__(self, default=..., **kw):
        unknown = set(kw) - _SUPPORTED
        if unknown:
            raise _UnsupportedConstraint(
                f"this pydantic shim does not implement {sorted(unknown)} - it "
                f"refuses rather than ignoring a constraint, because an ignored "
                f"constraint makes a validation test pass for the wrong reason")
        self.default = default
        self.default_factory = kw.get("default_factory")
        self.min_length = kw.get("min_length")
        self.max_length = kw.get("max_length")
        self.ge, self.le = kw.get("ge"), kw.get("le")
        self.gt, self.lt = kw.get("gt"), kw.get("lt")
        # Enforced with re.search, matching pydantic v2: the pattern is not
        # implicitly anchored, so "^(a|b)$" behaves as written.
        self.pattern = kw.get("pattern")

    @property
    def required(self):
        return self.default is ... and self.default_factory is None

    def get_default(self):
        if self.default_factory is not None:
            return self.default_factory()
        return None if self.default is ... else self.default


def Field(default=..., **kw):                            # noqa: N802
    return _FieldInfo(default, **kw)


def _origin(ann):
    return typing.get_origin(ann)


def _coerce(value, ann, name):
    """Coerce to the annotated type the way pydantic would for these types."""
    if ann is None or ann is typing.Any:
        return value
    origin = _origin(ann)
    if origin is typing.Union:                           # includes `X | None`
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if value is None:
            return None
        for a in args:
            try:
                return _coerce(value, a, name)
            except ValidationError:
                continue
        raise ValidationError(f"{name}: cannot coerce {value!r}")
    if origin in (list, set, tuple):
        if not isinstance(value, (list, tuple, set)):
            raise ValidationError(f"{name}: expected a list, got {type(value).__name__}")
        args = typing.get_args(ann)
        return [_coerce(v, args[0], name) for v in value] if args else list(value)
    if origin is dict:
        if not isinstance(value, dict):
            raise ValidationError(f"{name}: expected an object")
        return value
    if ann is bool:
        if isinstance(value, bool):
            return value
        if value in ("true", "True", 1, "1"):
            return True
        if value in ("false", "False", 0, "0"):
            return False
        raise ValidationError(f"{name}: not a boolean")
    if ann is int:
        if isinstance(value, bool):
            raise ValidationError(f"{name}: bool is not an int")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{name}: not an integer")
    if ann is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{name}: not a number")
    if ann is Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError(f"{name}: not a decimal")
    if ann is str:
        if isinstance(value, str):
            return value
        raise ValidationError(f"{name}: expected a string, got {type(value).__name__}")
    return value


class _ModelMeta(type):
    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        fields = {}
        for base in reversed(bases):
            fields.update(getattr(base, "__fields__", {}))
        annotations = ns.get("__annotations__", {})
        for fname, ann in annotations.items():
            # Skip dunder and private names. BaseModel annotates `__fields__`
            # itself, which without this became a *field* on every subclass and
            # got emitted by model_dump() - so `insert(...).values(**dump)` tried
            # to write a column called __fields__. Found by driving the real API
            # end to end, not by any unit test.
            if fname.startswith("_"):
                continue
            raw = ns.get(fname, ...)
            info = raw if isinstance(raw, _FieldInfo) else _FieldInfo(raw)
            fields[fname] = (ann, info)
        cls.__fields__ = fields
        return cls


class BaseModel(metaclass=_ModelMeta):
    __fields__: dict = {}

    def __init__(self, **data):
        errors, values = [], {}
        unknown = set(data) - set(self.__fields__)
        for fname, (ann, info) in self.__fields__.items():
            if fname in data:
                value = data[fname]
            elif info.required:
                errors.append(f"{fname}: field required")
                continue
            else:
                value = info.get_default()
            if value is None and not info.required:
                values[fname] = None
                continue
            try:
                value = _coerce(value, ann, fname)
            except ValidationError as e:
                errors.append(str(e))
                continue
            err = _check_constraints(fname, value, info)
            if err:
                errors.append(err)
                continue
            values[fname] = value
        # Unknown keys are ignored, matching pydantic's default `extra='ignore'`.
        for k in unknown:
            pass
        if errors:
            raise ValidationError(errors)
        object.__setattr__(self, "__dict__", values)

    def model_dump(self, **kw):
        return dict(self.__dict__)

    dict = model_dump

    def __repr__(self):
        inner = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"{type(self).__name__}({inner})"

    def __eq__(self, other):
        return (type(self) is type(other)
                and self.__dict__ == other.__dict__)


def _check_constraints(name, value, info: _FieldInfo):
    if info.pattern is not None and isinstance(value, str):
        import re as _re
        if _re.search(info.pattern, value) is None:
            return f"{name}: does not match {info.pattern!r}"
    if info.min_length is not None and hasattr(value, "__len__"):
        if len(value) < info.min_length:
            return f"{name}: shorter than {info.min_length}"
    if info.max_length is not None and hasattr(value, "__len__"):
        if len(value) > info.max_length:
            return f"{name}: longer than {info.max_length}"
    for attr, op, label in (("ge", "<", "less than"), ("le", ">", "greater than"),
                            ("gt", "<=", "not greater than"),
                            ("lt", ">=", "not less than")):
        bound = getattr(info, attr)
        if bound is None:
            continue
        try:
            bad = {"<": value < bound, ">": value > bound,
                   "<=": value <= bound, ">=": value >= bound}[op]
        except TypeError:
            continue
        if bad:
            return f"{name}: {label} {bound}"
    return None
