from taskplane import agent_hub
from taskplane import models


def test_models_export_stored_agent_config_with_backward_compatible_alias():
    assert hasattr(models, "StoredAgentConfig")
    assert models.AgentConfig is models.StoredAgentConfig


def test_agent_hub_exports_runtime_agent_spec_with_backward_compatible_alias():
    assert hasattr(agent_hub, "RuntimeAgentSpec")
    assert agent_hub.AgentConfig is agent_hub.RuntimeAgentSpec


def test_create_default_agent_hub_registers_runtime_agent_specs():
    hub = agent_hub.create_default_agent_hub(workdir=".")

    registered = hub.list_agents()

    assert registered
    assert all(isinstance(item, agent_hub.RuntimeAgentSpec) for item in registered)
