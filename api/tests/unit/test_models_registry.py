import pytest

from app.core.models_registry import HAIKU, NODES, OPUS, spec_for


def test_pinned_ids_are_exact_current_models() -> None:
    assert OPUS == "claude-opus-5-5"
    assert HAIKU == "claude-haiku-5-5"


def test_hybrid_routing_d12() -> None:
    assert spec_for("agent_simple").model == HAIKU
    assert spec_for("agent_complex").model == OPUS


@pytest.mark.parametrize("node", NODES)
def test_every_node_has_explicit_effort_and_sane_max_tokens(node: str) -> None:
    spec = spec_for(node)  # type: ignore[arg-type]
    assert spec.model in {OPUS, HAIKU}
    assert spec.effort in {"low", "medium", "high", "xhigh", "max"}
    assert 1_000 <= spec.max_tokens <= 64_000


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAABTA_MODEL_AGENT_SIMPLE", "claude-sonnet-5-5")
    assert spec_for("agent_simple").model == "claude-sonnet-5-5"
    assert spec_for("agent_simple").effort == "low"  # only the model is overridden
