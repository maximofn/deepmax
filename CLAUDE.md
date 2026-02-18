# CLAUDE.md

## Proyecto

**deepmax** es un bot personal multi-canal (Terminal + Telegram) que permite conversar por terminal y continuar la misma conversación por Telegram (y viceversa). Construido sobre **Deep Agents SDK** (LangChain/LangGraph).

El plan de implementación completo está en `PLAN.md`.

## Idioma

El usuario habla español. Todo el código (variables, funciones, docstrings) debe estar en inglés, los mensajes de commit deben estar en inglés, comentarios explicativos del código deben estar en inglés, pero la comunicación deben ser en español.

## Python

- Python 3.12+, gestor de paquetes: `uv`
- Antes de ejecutar código python: `source .venv/bin/activate`
- Ejecutar scripts: `uv run python -m deepmax`
- Ejecutar tests: `uv run pytest`
- Ejecutar un test específico: `uv run pytest tests/test_foo.py::test_name -v`

## Arquitectura

```
Canal (Terminal/Telegram)
  -> Orchestrator (resuelve identidad, mapea a thread_id)
    -> Deep Agent (create_deep_agent() - maneja LLM, historial, streaming, memoria)
      -> PostgreSQL (checkpoints + store de LangGraph)
```

**Flujo de un mensaje:**
1. Canal recibe texto, normaliza a `IncomingMessage(channel, channel_uid, text)`
2. Orchestrator resuelve identidad cross-canal -> obtiene `User` canónico
3. Obtiene conversación activa del usuario -> obtiene `thread_id` de LangGraph
4. Llama `agent.astream(input, config={"thread_id": ...}, stream_mode="messages")`
5. Itera tokens del stream, los envía al canal en tiempo real
6. LangGraph persiste automáticamente el historial en PostgreSQL

**Continuidad cross-canal:** ambos canales resuelven al mismo `User` vía `channel_identities`. El mismo `thread_id` se usa independientemente del canal, así el LLM ve todo el historial.

## Deep Agents SDK

La documentación del framework Deep Agents está en `../deepagents/` (directorio hermano). Archivos clave:

| Archivo | Contenido |
|---------|-----------|
| `01-get-started.md` | Overview: qué es, cuándo usarlo, capacidades core |
| `02-quickstart.md` | Primer agente con `create_deep_agent()` |
| `03-customization.md` | Model, tools, system_prompt, middleware, subagents, backends, skills, memory, structured output |
| `04-harness.md` | Capacidades built-in: planning (write_todos), filesystem virtual, subagents, auto-summarización, context management |
| `05-backends.md` | StateBackend, FilesystemBackend, StoreBackend, CompositeBackend, protocolo custom |
| `06-subagents.md` | Spawning de subagentes, aislamiento de contexto, subagentes custom con tools/modelos específicos |
| `07-human-in-the-loop.md` | `interrupt_on` config, decisiones approve/edit/reject, manejo de interrupts con `Command(resume=)` |
| `08-long-term-memory.md` | CompositeBackend con `/memories/` para persistencia cross-thread, PostgresStore |
| `09-skills.md` | Formato SKILL.md con frontmatter, progressive disclosure, skills vs memory, skills para subagentes |
| `10-sandboxes.md` | Sandbox backends (Modal, Daytona, Runloop), execute tool, file transfer, seguridad |
| `11-streaming-overview.md` | Streaming de tokens, subagent progress, tool calls, custom events, stream modes |
| `12-streaming-frontend.md` | React `useStream` hook, SubagentStream, thread persistence, subagent cards |
| `13-agent-client-protocol-acp.md` | Protocolo ACP para integración con IDEs (Zed, JetBrains, VSCode), AgentServerACP |
| `14-cli-overview.md` | Deep Agents CLI: tools built-in (ls, read_file, write_file, shell, grep, etc.), memory, skills, slash commands |
| `15-cli-providers.md` | Referencia de 20+ proveedores, config.toml, model resolution order, providers arbitrarios via `class_path` |

**Formato modelo multi-proveedor:** `"provider:model"` (e.g. `"anthropic:claude-sonnet-4-5-20250929"`, `"openai:gpt-4.1"`, `"google_genai:gemini-2.5-flash-lite"`).

## Proyectos de referencia

Hay dos bots existentes en carpetas hermanas que sirven como referencia de arquitectura y patrones. Consultar su código cuando necesites resolver problemas concretos.

### aipal (`../aipal/`)

Bot de Telegram en Node.js que actúa como gateway a agentes CLI locales (Codex, Claude, Gemini). Patrones relevantes:

- **Cola por topic** (`src/index.js`): `Map<topicKey, Promise>` serializa mensajes del mismo chat/topic para evitar race conditions. Patrón clave a replicar.
- **Typing indicator** (`src/index.js`): envía `sendChatAction("typing")` cada 4 segundos mientras espera al agente.
- **Chunking** (`src/message-utils.js`): divide respuestas en chunks de ~3000 chars respetando code fences para Telegram.
- **Graceful shutdown** (`src/index.js`): drain queue con timeout de 120s, espera a que persistan threads/memory, force exit.
- **Thread store** (`src/thread-store.js`): mapeo `{chatId}:{topicId}:{agentId}` -> threadId con migración de formatos legacy.
- **Memory** (`src/memory-store.js`, `src/memory-retrieval.js`): JSONL por thread + FTS5 search + curation automática. Scoring por scope + lexical + recency.
- **Bootstrap context** (`src/index.js`): inyecta soul.md + memory.md + historial reciente solo en el primer turno de un thread nuevo.

### openclaw (`../openclaw/`)

Bot multi-canal en TypeScript (Telegram, WhatsApp, Discord, IRC, Slack, Signal, iMessage). Patrones relevantes:

- **Session key** (`src/routing/session-key.ts`): formato `agent:{agentId}:{rest}` con 4 dmScope modes (`main`, `per-peer`, `per-channel-peer`, `per-account-channel-peer`).
- **Identity links** (`src/routing/session-key-utils.ts`): vinculación cross-canal configurable (canonical -> aliases).
- **Channel registry** (`src/channels/registry.ts`): registro de plugins de canal con capabilities (streaming, media, edit, threads, etc.).
- **Delivery queue** (`src/infra/outbound/delivery-queue.ts`): write-ahead queue para crash recovery, retry con exponential backoff (5s, 25s, 2m, 10m), failed entries en directorio separado.
- **Streaming coalescing** (`src/gateway/server-chat.ts`): rate-limit de 150ms entre delta sends para no spamear mensajes.
- **Agent routing** (`src/routing/resolve-route.ts`): resolución por tiers (peer -> guild+roles -> channel -> default) con cache de bindings.

## PostgreSQL

LangGraph crea sus propias tablas para checkpoints y store. Nosotros solo mantenemos 3 tablas ligeras:
- `users` — usuarios canónicos
- `channel_identities` — mapeo canal+uid -> user (con unique constraint)
- `conversations` — mapeo user -> thread_id de LangGraph + metadata (título, modelo, active)

El schema completo está en `PLAN.md`.

## Secretos

API keys exclusivamente via env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `TELEGRAM_BOT_TOKEN`. Nunca en config.toml ni en código.
