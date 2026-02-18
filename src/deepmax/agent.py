"""Deep Agent creation and management."""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore

from deepmax.config import AppConfig

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages Deep Agent instances, caching by model string."""

    def __init__(
        self,
        checkpointer: AsyncPostgresSaver,
        store: AsyncPostgresStore,
        default_model: str,
        default_system_prompt: str,
    ) -> None:
        self.checkpointer = checkpointer
        self.store = store
        self.default_model = default_model
        self.default_system_prompt = default_system_prompt
        self._cache: dict[str, CompiledStateGraph] = {}

    def get_agent(self, model: str | None = None) -> CompiledStateGraph:
        """Get or create an agent for the given model."""
        model = model or self.default_model
        if model not in self._cache:
            self._cache[model] = self._create_agent(model)
            logger.info("Created agent for model %s", model)
        return self._cache[model]

    def _create_agent(self, model: str) -> CompiledStateGraph:
        return create_deep_agent(
            model=model,
            system_prompt=self.default_system_prompt,
            backend=lambda rt: CompositeBackend(
                default=StateBackend(rt),
                routes={"/memories/": StoreBackend(rt)},
            ),
            store=self.store,
            checkpointer=self.checkpointer,
            memory=["/memories/AGENTS.md"],
        )


async def create_agent_manager(
    config: AppConfig,
) -> tuple[AgentManager, AsyncPostgresSaver, AsyncPostgresStore]:
    """Initialize PostgreSQL persistence and create the agent manager."""
    checkpointer = AsyncPostgresSaver.from_conn_string(config.database.url)
    await checkpointer.setup()

    store = AsyncPostgresStore.from_conn_string(config.database.url)
    await store.setup()

    manager = AgentManager(
        checkpointer=checkpointer,
        store=store,
        default_model=config.provider.model,
        default_system_prompt=config.provider.system_prompt,
    )

    # Pre-create the default agent
    manager.get_agent()

    logger.info("Agent manager initialized (default model: %s)", config.provider.model)
    return manager, checkpointer, store
