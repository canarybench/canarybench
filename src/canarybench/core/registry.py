"""Engine and Domain Pack discovery via importlib entry points and built-in fallbacks."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from typing import Any

from canarybench.core.base import BaseEngine, BasePack, EngineMetadata, PackMetadata
from canarybench.core.schemas import EngineId, PackId

ENGINE_ENTRYPOINT_GROUP = "canarybench.engines"
PACK_ENTRYPOINT_GROUP = "canarybench.packs"

_BUILTIN_ENGINE_FALLBACKS: dict[str, str] = {
    EngineId.LEDGER_MATH.value: "canarybench.engines.ledger_math:LedgerMathEngine",
    EngineId.DOC_RECONCILE.value: "canarybench.engines.doc_reconcile:DocReconcileEngine",
    EngineId.RULE_TRIAGE.value: "canarybench.engines.rule_triage:RuleTriageEngine",
    EngineId.WIRE_PROTOCOL.value: "canarybench.engines.wire_protocol:WireProtocolEngine",
}

_BUILTIN_PACK_FALLBACKS: dict[str, str] = {
    PackId.EU_VAT_2027.value: "canarybench.packs.eu_vat_2027.pack:EuVat2027Pack",
    PackId.CRE_LEASE.value: "canarybench.packs.cre_lease.pack:CreLeasePack",
    PackId.CUSTOMS_CBAM.value: "canarybench.packs.customs_cbam.pack:CustomsCbamPack",
    PackId.MED_CODING.value: "canarybench.packs.med_coding.pack:MedCodingPack",
    PackId.CLAIMS_ADJUDICATION.value: (
        "canarybench.packs.claims_adjudication.pack:ClaimsAdjudicationPack"
    ),
}


class EngineNotFoundError(KeyError):
    """Raised when a requested engine_id is not registered."""


class EngineRegistrationError(ValueError):
    """Raised when an engine plugin violates the BaseEngine registration contract."""


class PackNotFoundError(KeyError):
    """Raised when a requested pack_id is not registered."""


class PackRegistrationError(ValueError):
    """Raised when a pack plugin violates the BasePack registration contract."""


class EngineRegistry:
    """Registry discovering built-in and entry-point failure-archetype engines."""

    def __init__(self) -> None:
        self._factories: dict[str, type[BaseEngine]] = {}
        self._discovered = False

    def register(
        self,
        engine_cls: type[BaseEngine],
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(engine_cls, type) or not issubclass(engine_cls, BaseEngine):
            raise EngineRegistrationError(f"{engine_cls!r} must subclass BaseEngine")
        engine_id = engine_cls.metadata.engine_id.value
        if engine_id in self._factories and not replace:
            if self._factories[engine_id] is engine_cls:
                return
            raise EngineRegistrationError(
                f"Duplicate engine_id '{engine_id}': "
                f"{self._factories[engine_id]!r} vs {engine_cls!r}"
            )
        self._factories[engine_id] = engine_cls

    def discover(self, *, force: bool = False) -> None:
        if self._discovered and not force:
            return

        for ep in entry_points(group=ENGINE_ENTRYPOINT_GROUP):
            loaded = ep.load()
            self._validate_and_register(ep.name, loaded)

        for engine_id, target in _BUILTIN_ENGINE_FALLBACKS.items():
            if engine_id not in self._factories:
                mod_path, cls_name = target.split(":", maxsplit=1)
                loaded = getattr(import_module(mod_path), cls_name)
                self._validate_and_register(engine_id, loaded)

        self._discovered = True

    def _validate_and_register(self, expected_id: str, loaded: Any) -> None:
        if not isinstance(loaded, type) or not issubclass(loaded, BaseEngine):
            raise EngineRegistrationError(
                f"Entry point '{expected_id}' did not resolve to a BaseEngine subclass"
            )
        if loaded.metadata.engine_id.value != expected_id:
            raise EngineRegistrationError(
                f"Entry point '{expected_id}' != engine metadata.engine_id "
                f"'{loaded.metadata.engine_id.value}'"
            )
        self.register(loaded)

    def get(self, engine_id: EngineId | str) -> BaseEngine:
        self.discover()
        key = engine_id.value if isinstance(engine_id, EngineId) else engine_id
        if key not in self._factories:
            available = ", ".join(sorted(self._factories)) or "<none>"
            raise EngineNotFoundError(f"Unknown engine '{key}'. Available: {available}")
        return self._factories[key]()

    def list_engines(self) -> list[EngineMetadata]:
        self.discover()
        return [cls.metadata for _, cls in sorted(self._factories.items())]


class PackRegistry:
    """Registry discovering built-in and external entry-point domain packs."""

    def __init__(self) -> None:
        self._factories: dict[str, type[BasePack[Any, Any, Any]]] = {}
        self._discovered = False

    def register(
        self,
        pack_cls: type[BasePack[Any, Any, Any]],
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(pack_cls, type) or not issubclass(pack_cls, BasePack):
            raise PackRegistrationError(f"{pack_cls!r} must subclass BasePack")
        pack_id = pack_cls.metadata.pack_id.value
        if pack_id in self._factories and not replace:
            if self._factories[pack_id] is pack_cls:
                return
            raise PackRegistrationError(
                f"Duplicate pack_id '{pack_id}': "
                f"{self._factories[pack_id]!r} vs {pack_cls!r}"
            )
        self._factories[pack_id] = pack_cls

    def discover(self, *, force: bool = False) -> None:
        if self._discovered and not force:
            return

        for ep in entry_points(group=PACK_ENTRYPOINT_GROUP):
            loaded = ep.load()
            self._validate_and_register(ep.name, loaded)

        for pack_id, target in _BUILTIN_PACK_FALLBACKS.items():
            if pack_id not in self._factories:
                mod_path, cls_name = target.split(":", maxsplit=1)
                loaded = getattr(import_module(mod_path), cls_name)
                self._validate_and_register(pack_id, loaded)

        self._discovered = True

    def _validate_and_register(self, expected_id: str, loaded: Any) -> None:
        if not isinstance(loaded, type) or not issubclass(loaded, BasePack):
            raise PackRegistrationError(
                f"Entry point '{expected_id}' did not resolve to a BasePack subclass"
            )
        if loaded.metadata.pack_id.value != expected_id:
            raise PackRegistrationError(
                f"Entry point '{expected_id}' != pack metadata.pack_id "
                f"'{loaded.metadata.pack_id.value}'"
            )
        self.register(loaded)

    def get(self, pack_id: PackId | str) -> BasePack[Any, Any, Any]:
        self.discover()
        key = pack_id.value if isinstance(pack_id, PackId) else pack_id
        if key not in self._factories:
            available = ", ".join(sorted(self._factories)) or "<none>"
            raise PackNotFoundError(f"Unknown pack '{key}'. Available: {available}")
        return self._factories[key]()

    def list_packs(self, *, engine_id: EngineId | None = None) -> list[PackMetadata]:
        self.discover()
        metas = [cls.metadata for _, cls in sorted(self._factories.items())]
        if engine_id is not None:
            metas = [m for m in metas if engine_id in m.supported_engines]
        return metas

    def packs_for_engine(self, engine_id: EngineId) -> list[BasePack[Any, Any, Any]]:
        self.discover()
        return [
            cls()
            for _, cls in sorted(self._factories.items())
            if engine_id in cls.metadata.supported_engines
        ]


default_engine_registry = EngineRegistry()
default_pack_registry = PackRegistry()

SuiteNotFoundError = PackNotFoundError
SuiteRegistrationError = PackRegistrationError
SuiteRegistry = PackRegistry
default_registry = default_pack_registry
