"""Application entry point and lifecycle management."""

import asyncio
import logging
import signal

from dotenv import load_dotenv

load_dotenv()

from deepmax.agent import create_agent_manager
from deepmax.channels.telegram import TelegramChannel
from deepmax.channels.terminal import TerminalChannel
from deepmax.config import load_config
from deepmax.core.identity import IdentityService
from deepmax.core.orchestrator import Orchestrator
from deepmax.storage.db import close_pool, init_pool

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("deepmax starting")

    config = load_config()

    # --- Database ---
    pool = await init_pool(config.database.url)

    # --- Agent ---
    agent_manager, checkpointer_pool, store_pool = await create_agent_manager(config)

    # --- Identity ---
    identity = IdentityService(pool, config)
    await identity.bootstrap_from_config()

    # --- Shutdown coordination ---
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # --- Orchestrator ---
    orchestrator = Orchestrator(agent_manager, identity, config, shutdown_event)

    # --- Launch channels ---
    channel_tasks: list[asyncio.Task] = []
    channels = []

    if config.channels.terminal.enabled:
        terminal = TerminalChannel(user_name=config.channels.terminal.user_name)
        channels.append(terminal)
        channel_tasks.append(
            asyncio.create_task(terminal.start(orchestrator, shutdown_event), name="terminal")
        )

    if config.channels.telegram.enabled:
        telegram = TelegramChannel(allowed_users=config.channels.telegram.allowed_users)
        channels.append(telegram)
        channel_tasks.append(
            asyncio.create_task(telegram.start(orchestrator, shutdown_event), name="telegram")
        )

    if not channel_tasks:
        logger.error("No channels enabled, exiting")
        await close_pool(pool)
        return

    logger.info("deepmax ready (%d channel(s))", len(channel_tasks))

    # --- Wait for shutdown ---
    await shutdown_event.wait()
    logger.info("Shutting down...")

    # 1. Drain active message handlers
    await orchestrator.wait_for_active_tasks(timeout=config.limits.shutdown_drain)

    # 2. Stop channels
    for ch in channels:
        try:
            await ch.stop()
        except Exception:
            logger.exception("Error stopping channel %s", ch.name)

    # 3. Cancel channel tasks
    for task in channel_tasks:
        task.cancel()
    await asyncio.gather(*channel_tasks, return_exceptions=True)

    # 4. Close database pool
    await close_pool(pool)

    # 5. Close checkpointer and store connection pools
    await checkpointer_pool.close()
    await store_pool.close()

    logger.info("deepmax stopped")
