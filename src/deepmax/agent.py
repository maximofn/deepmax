"""Deep Agent creation and management."""

from __future__ import annotations

import logging
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool

from deepmax.config import AppConfig

logger = logging.getLogger(__name__)

_POOL_KWARGS = {"autocommit": True, "prepare_threshold": 0}


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


_AGENTS_MD_PATH = Path(__file__).parent.parent.parent / "AGENTS.md"


async def _seed_agents_md(store: AsyncPostgresStore) -> None:
    """Seed AGENTS.md from disk into the store so the agent loads it as memory."""
    if not _AGENTS_MD_PATH.exists():
        logger.warning("AGENTS.md not found at %s, skipping memory seed", _AGENTS_MD_PATH)
        return
    content = _AGENTS_MD_PATH.read_text()
    # CompositeBackend strips "/memories/" prefix, so the key in the store is "/AGENTS.md"
    await store.aput(
        namespace=("filesystem",),
        key="/AGENTS.md",
        value=create_file_data(content),
    )
    logger.info("Seeded AGENTS.md into store")


async def create_agent_manager(
    config: AppConfig,
) -> tuple[AgentManager, AsyncConnectionPool, AsyncConnectionPool]:
    """Initialize PostgreSQL persistence and create the agent manager.

    Returns (AgentManager, checkpointer_pool, store_pool) so the caller
    can close the pools on shutdown.
    """
    checkpointer_pool = AsyncConnectionPool(
        conninfo=config.database.url, max_size=5, kwargs=_POOL_KWARGS, open=False
    )
    await checkpointer_pool.open()
    checkpointer = AsyncPostgresSaver(checkpointer_pool)
    await checkpointer.setup()

    store_pool = AsyncConnectionPool(
        conninfo=config.database.url, max_size=5, kwargs=_POOL_KWARGS, open=False
    )
    await store_pool.open()
    store = AsyncPostgresStore(store_pool)
    await store.setup()

    # Seed AGENTS.md into the store so the agent loads it as memory
    await _seed_agents_md(store)

    manager = AgentManager(
        checkpointer=checkpointer,
        store=store,
        default_model=config.provider.model,
        default_system_prompt=config.provider.system_prompt,
    )

    # Pre-create the default agent
    manager.get_agent()

    logger.info("Agent manager initialized (default model: %s)", config.provider.model)
    return manager, checkpointer_pool, store_pool
