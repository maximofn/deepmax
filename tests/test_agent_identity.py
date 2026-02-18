"""Integration test: verify the agent knows its identity from AGENTS.md."""

import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from deepmax.agent import _AGENTS_MD_PATH


@pytest.fixture()
def agent():
    """Create an agent with AGENTS.md seeded in memory (no PostgreSQL needed)."""
    content = _AGENTS_MD_PATH.read_text()
    store = InMemoryStore()
    store.put(namespace=("filesystem",), key="/AGENTS.md", value=create_file_data(content))

    return create_deep_agent(
        model="anthropic:claude-haiku-4-5-20251001",
        system_prompt="You are a helpful and concise personal assistant.",
        backend=lambda rt: CompositeBackend(
            default=StateBackend(rt),
            routes={"/memories/": StoreBackend(rt)},
        ),
        store=store,
        checkpointer=MemorySaver(),
        memory=["/memories/AGENTS.md"],
    )


@pytest.mark.slow
def test_agent_knows_its_name(agent):
    """The agent should identify itself as deepmax, not Claude."""
    thread_id = str(uuid.uuid4())
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "¿Cuál es tu nombre?"}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    last_message = result["messages"][-1].content
    # Handle content being a list of blocks
    if isinstance(last_message, list):
        last_message = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in last_message
        )
    assert "deepmax" in last_message.lower(), (
        f"Agent should identify as 'deepmax' but responded: {last_message[:200]}"
    )
