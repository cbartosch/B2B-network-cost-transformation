from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from network_cost_workbench.domain.enums import ExecutionMode


class AgentExecutionError(RuntimeError):
    pass


class ProviderAdapter(Protocol):
    def invoke(self, *, agent_id: str, payload: dict[str, Any]) -> "ProviderResponse": ...


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider: str
    model: str
    provider_response_id: str
    output: dict[str, Any]
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    permitted_execution_modes: frozenset[ExecutionMode]
    promotable_output: bool = False


@dataclass(slots=True)
class AgentRunRecord:
    agent_id: str
    execution_mode: ExecutionMode
    agent_run_id: UUID = field(default_factory=uuid4)
    status: str = "QUEUED"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    provider: str | None = None
    model: str | None = None
    provider_response_id: str | None = None
    output: dict[str, Any] | None = None
    promotable: bool = False


class AgentRuntime:
    """Bounded agent runtime with explicit anti-fake execution controls."""

    def __init__(
        self,
        *,
        environment: str,
        definitions: dict[str, AgentDefinition],
        provider_adapters: dict[str, ProviderAdapter] | None = None,
    ) -> None:
        self.environment = environment.lower()
        self.definitions = definitions
        self.provider_adapters = provider_adapters or {}

    def execute(
        self,
        *,
        agent_id: str,
        mode: ExecutionMode,
        payload: dict[str, Any],
        provider_name: str | None = None,
        replay_response: ProviderResponse | None = None,
    ) -> AgentRunRecord:
        definition = self.definitions.get(agent_id)
        if definition is None:
            raise AgentExecutionError(f"unknown agent: {agent_id}")
        if mode not in definition.permitted_execution_modes:
            raise AgentExecutionError(f"{agent_id} does not permit execution mode {mode.value}")
        if mode is ExecutionMode.MOCK and self.environment == "production":
            raise AgentExecutionError("MOCK agent runs are disabled in production")

        record = AgentRunRecord(agent_id=agent_id, execution_mode=mode, status="RUNNING")

        if mode is ExecutionMode.LIVE:
            if not provider_name or provider_name not in self.provider_adapters:
                raise AgentExecutionError("LIVE run requires a configured provider adapter")
            response = self.provider_adapters[provider_name].invoke(agent_id=agent_id, payload=payload)
            if not response.provider_response_id:
                raise AgentExecutionError("LIVE run missing provider response ID")
            return self._complete(record, response, promotable=definition.promotable_output)

        if mode is ExecutionMode.REPLAY:
            if replay_response is None or not replay_response.provider_response_id:
                raise AgentExecutionError("REPLAY requires a captured provider response")
            return self._complete(record, replay_response, promotable=False)

        if mode is ExecutionMode.DETERMINISTIC_ONLY:
            record.status = "COMPLETED"
            record.output = {"status": "no_llm_call", "input": payload}
            record.promotable = definition.promotable_output
            return record

        record.status = "COMPLETED"
        record.output = {"status": "mock_test_fixture", "input": payload}
        record.promotable = False
        return record

    @staticmethod
    def _complete(
        record: AgentRunRecord,
        response: ProviderResponse,
        *,
        promotable: bool,
    ) -> AgentRunRecord:
        record.status = "COMPLETED"
        record.provider = response.provider
        record.model = response.model
        record.provider_response_id = response.provider_response_id
        record.output = response.output
        record.promotable = promotable
        return record
