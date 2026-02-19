"""Message orchestration: identity resolution, command dispatch, and streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from deepmax.channels.base import (
    Channel,
    Conversation,
    IncomingMessage,
    User,
    parse_slash_command,
)
from deepmax.core.identity import IdentityService

if TYPE_CHECKING:
    from deepmax.agent import AgentManager
    from deepmax.config import AppConfig

logger = logging.getLogger(__name__)


class Orchestrator:
    """Receives messages from channels, resolves identity, and streams responses."""

    def __init__(
        self,
        agent_manager: AgentManager,
        identity: IdentityService,
        config: AppConfig,
        shutdown_event: asyncio.Event,
    ) -> None:
        self.agent_manager = agent_manager
        self.identity = identity
        self.config = config
        self.shutdown_event = shutdown_event
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: set[asyncio.Task] = set()

    def _get_lock(self, user_name: str) -> asyncio.Lock:
        if user_name not in self._user_locks:
            self._user_locks[user_name] = asyncio.Lock()
        return self._user_locks[user_name]

    async def handle_message(self, msg: IncomingMessage, channel: Channel) -> None:
        """Main entry point for all incoming messages."""
        if self.shutdown_event.is_set():
            await channel.send_text(msg.channel_uid, "Bot is shutting down, please try again later.")
            return

        user = self.identity.resolve(msg.channel, msg.channel_uid)
        if user is None:
            logger.warning("Access denied: %s/%s", msg.channel, msg.channel_uid)
            await channel.send_text(msg.channel_uid, "Access denied.")
            return

        lock = self._get_lock(user.name)
        async with lock:
            task = asyncio.current_task()
            if task:
                self._active_tasks.add(task)
            try:
                parsed = parse_slash_command(msg.text)
                if parsed is not None:
                    await self._handle_command(parsed[0], parsed[1], user, channel, msg.channel_uid)
                else:
                    await self._handle_chat(msg, user, channel)
            finally:
                if task:
                    self._active_tasks.discard(task)

    async def _handle_command(
        self, command: str, args: str, user: User, channel: Channel, channel_uid: str
    ) -> None:
        match command:
            case "/new":
                conv = await self.identity.create_conversation(
                    self.config.provider.model, self.config.provider.system_prompt
                )
                await channel.send_text(
                    channel_uid,
                    f"New conversation created. Thread: {conv.thread_id[:8]}...",
                )

            case "/history":
                convs = await self.identity.list_conversations()
                if not convs:
                    await channel.send_text(channel_uid, "No conversations yet.")
                    return
                lines = []
                for c in convs:
                    active = " *" if c.is_active else ""
                    title = c.title or "(untitled)"
                    lines.append(f"  [{c.thread_id[:8]}] {title} — {c.model}{active}")
                await channel.send_text(channel_uid, "Conversations:\n" + "\n".join(lines))

            case "/switch":
                if not args.strip():
                    await channel.send_text(channel_uid, "Usage: /switch <thread_id_prefix>")
                    return
                prefix = args.strip()
                conv = await self.identity.switch_conversation(prefix)
                if conv is None:
                    await channel.send_text(channel_uid, "Conversation not found.")
                else:
                    title = conv.title or "(untitled)"
                    await channel.send_text(channel_uid, f"Switched to [{conv.thread_id[:8]}] {title}")

            case "/title":
                if not args.strip():
                    await channel.send_text(channel_uid, "Usage: /title <text>")
                    return
                conv = await self.identity.get_active_conversation()
                if conv is None:
                    await channel.send_text(channel_uid, "No active conversation.")
                    return
                await self.identity.update_conversation_title(conv.thread_id, args.strip())
                await channel.send_text(channel_uid, f"Title set: {args.strip()}")

            case "/model":
                if not args.strip():
                    conv = await self.identity.get_active_conversation()
                    current = conv.model if conv else self.config.provider.model
                    await channel.send_text(channel_uid, f"Current model: {current}")
                    return
                new_model = args.strip()
                conv = await self.identity.get_active_conversation()
                if conv is None:
                    await channel.send_text(channel_uid, "No active conversation.")
                    return
                await self.identity.update_conversation_model(conv.thread_id, new_model)
                await channel.send_text(channel_uid, f"Model changed to: {new_model}")

            case "/system":
                if not args.strip():
                    await channel.send_text(channel_uid, "Usage: /system <prompt>")
                    return
                conv = await self.identity.get_active_conversation()
                if conv is None:
                    await channel.send_text(channel_uid, "No active conversation.")
                    return
                await self.identity.update_conversation_system_prompt(conv.thread_id, args.strip())
                await channel.send_text(channel_uid, "System prompt updated.")

            case "/help":
                help_text = (
                    "Commands:\n"
                    "  /new — New conversation\n"
                    "  /history — List conversations\n"
                    "  /switch <prefix> — Switch conversation by thread_id prefix\n"
                    "  /title <text> — Set title\n"
                    "  /model [provider:model] — Show/change model\n"
                    "  /system <prompt> — Change system prompt\n"
                    "  /help — This help"
                )
                await channel.send_text(channel_uid, help_text)

            case _:
                await channel.send_text(channel_uid, f"Unknown command: {command}")

    async def _handle_chat(
        self, msg: IncomingMessage, user: User, channel: Channel
    ) -> None:
        conv = await self.identity.get_or_create_active_conversation(
            self.config.provider.model, self.config.provider.system_prompt
        )
        await self._stream_response(msg, user, channel, conv)

    async def _stream_response(
        self,
        msg: IncomingMessage,
        user: User,
        channel: Channel,
        conv: Conversation,
    ) -> None:
        agent = self.agent_manager.get_agent(model=conv.model)
        config = {"configurable": {"thread_id": conv.thread_id}}
        input_msg = {"messages": [{"role": "user", "content": msg.text}]}

        typing_task = asyncio.create_task(self._typing_loop(channel, msg.channel_uid))

        try:
            async for namespace, chunk in agent.astream(
                input_msg, config=config, stream_mode="messages", subgraphs=True
            ):
                token, metadata = chunk
                # Only stream content from the main agent (not subagents), skip tool call chunks
                if not namespace and token.content and not getattr(token, "tool_call_chunks", None):
                    content = token.content
                    # content can be a list of blocks (e.g. [{"type": "text", "text": "..."}])
                    if isinstance(content, list):
                        content = "".join(
                            block.get("text", "") if isinstance(block, dict) else str(block)
                            for block in content
                        )
                    if content:
                        await channel.send_token(msg.channel_uid, content)
        except Exception:
            logger.exception("Error streaming response for user %s", user.name)
            await channel.send_text(msg.channel_uid, "An error occurred processing your message.")
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
            await channel.flush(msg.channel_uid)

    async def _typing_loop(self, channel: Channel, channel_uid: str) -> None:
        """Send typing indicators periodically until cancelled."""
        try:
            while True:
                await channel.send_typing(channel_uid)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def wait_for_active_tasks(self, timeout: float) -> None:
        """Wait for in-flight message handlers to finish."""
        if not self._active_tasks:
            return
        logger.info("Waiting for %d active tasks to finish...", len(self._active_tasks))
        done, pending = await asyncio.wait(self._active_tasks, timeout=timeout)
        if pending:
            logger.warning("Timed out waiting for %d tasks", len(pending))
            for task in pending:
                task.cancel()
