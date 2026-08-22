import pytest

from network_cost_workbench.agents.runtime import (
    AgentDefinition,
    AgentExecutionError,
    AgentRuntime,
)
from network_cost_workbench.domain.enums import ExecutionMode


def runtime(environment: str) -> AgentRuntime:
    return AgentRuntime(
        environment=environment,
        definitions={
            "contract_intelligence": AgentDefinition(
                agent_id="contract_intelligence",
                permitted_execution_modes=frozenset(
                    {ExecutionMode.LIVE, ExecutionMode.MOCK, ExecutionMode.REPLAY}
                ),
            )
        },
    )


def test_mock_is_blocked_in_production() -> None:
    with pytest.raises(AgentExecutionError):
        runtime("production").execute(
            agent_id="contract_intelligence",
            mode=ExecutionMode.MOCK,
            payload={},
        )


def test_live_without_provider_fails_closed() -> None:
    with pytest.raises(AgentExecutionError):
        runtime("development").execute(
            agent_id="contract_intelligence",
            mode=ExecutionMode.LIVE,
            payload={},
        )
