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
┌─────────┐  ┌──────────┐
│ Terminal │  │ Telegram  │    <- Canales (adaptadores finos)
└────┬─────┘  └─────┬─────┘
     │              │
     ▼              ▼
┌──────────────────────────┐
│       Orchestrator       │  <- Resuelve identidad, mapea a thread_id
│  (access control ->      │
│   resolve identity ->    │
│   resolve thread_id ->   │
│   agent.stream())        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│     Deep Agent (SDK)     │  <- create_deep_agent()
│  - LLM multi-proveedor   │
│  - Historial automático  │
│  - Streaming nativo      │
│  - Planificación (todos) │
│  - Subagentes            │
│  - Auto-summarización    │
│  - Memoria largo plazo   │
└────────────┬─────────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
┌──────────┐   ┌───────────┐
│ LLM APIs │   │ PostgreSQL│
│ (via LC)  │   │ (checkpts │
└──────────┘   │  + store) │
               └───────────┘
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

## Estructura del proyecto

```
deepmax/
├── pyproject.toml
├── config.example.toml
├── AGENTS.md                 # Memoria persistente del agente (convenciones, preferencias)
├── skills/                   # Skills opcionales del agente
│   └── .gitkeep
├── src/
│   └── deepmax/
│       ├── __init__.py
│       ├── main.py           # Entry point, arranca canales + orchestrator
│       ├── config.py         # Carga config desde TOML + env vars (pydantic)
│       │
│       ├── agent.py          # Crea y configura el Deep Agent
│       │
│       ├── core/
│       │   ├── orchestrator.py  # Recibe mensajes de canales, resuelve identidad, llama agent
│       │   └── identity.py      # Resolución de identidad cross-canal + tabla conversations
│       │
│       ├── channels/
│       │   ├── base.py          # Protocolo abstracto de canal
│       │   ├── terminal.py      # Adaptador stdin/stdout con prompt_toolkit
│       │   └── telegram.py      # Adaptador aiogram
│       │
│       └── storage/
│           └── db.py            # Pool asyncpg para identidades/conversations (ligero)
```

## Creación del Deep Agent

```python
# agent.py
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

async def create_bot_agent(config):
    """Create the Deep Agent with PostgreSQL persistence."""
    checkpointer = AsyncPostgresSaver.from_conn_string(config.database.url)
    await checkpointer.setup()

    store = AsyncPostgresStore.from_conn_string(config.database.url)
    await store.setup()

    agent = create_deep_agent(
        model=config.provider.model,  # e.g. "anthropic:claude-sonnet-4-5-20250929"
        system_prompt=config.provider.system_prompt,
        backend=lambda rt: CompositeBackend(
            default=StateBackend(rt),
            routes={"/memories/": StoreBackend(rt)},
        ),
        store=store,
        checkpointer=checkpointer,
        tools=[],
    )

    return agent, checkpointer, store
```

## Schema PostgreSQL

LangGraph crea sus propias tablas para checkpoints y store. Nosotros solo mantenemos 3 tablas ligeras:

```sql
-- Usuarios canónicos
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Identidades por canal
CREATE TABLE channel_identities (
    id          SERIAL PRIMARY KEY,
    user_id     INT REFERENCES users(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,
    channel_uid TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    UNIQUE(channel, channel_uid)
);

-- Conversaciones: mapea user -> thread_id de LangGraph + metadata
CREATE TABLE conversations (
    id            SERIAL PRIMARY KEY,
    user_id       INT REFERENCES users(id) ON DELETE CASCADE,
    thread_id     TEXT NOT NULL UNIQUE,     -- UUID para LangGraph
    title         TEXT,
    model         TEXT NOT NULL,            -- 'anthropic:claude-sonnet-4-5-20250929'
    system_prompt TEXT,
    is_active     BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Auto-actualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Solo una conversación activa por usuario
CREATE UNIQUE INDEX idx_one_active_conv
    ON conversations(user_id) WHERE is_active = true;

CREATE INDEX idx_channel_identities_lookup ON channel_identities(channel, channel_uid);
```

**No hay tabla `messages`** — LangGraph almacena todo el historial en sus tablas de checkpoints, accesible vía `thread_id`.

## Flujo de un mensaje

1. **Canal recibe mensaje** (terminal input / Telegram update)
2. **Access control** — verifica que el usuario está autorizado
3. Canal normaliza a `IncomingMessage(channel, channel_uid, text)`
4. **Orchestrator** recibe el `IncomingMessage`:
   a. `identity.resolve(channel, channel_uid)` -> busca/crea `User`
   b. `identity.get_active_conversation(user_id)` -> obtiene `Conversation` activa (con thread_id y model)
   c. Prepara config de LangGraph: `{"configurable": {"thread_id": conv.thread_id}}`
   d. **Streaming**: itera sobre `agent.astream(input, config, stream_mode="messages", subgraphs=True)`
   e. **Canal muestra progreso** en tiempo real:
      - Terminal: imprime tokens directamente
      - Telegram: edita mensaje cada ~1s + typing indicator
5. Canal envía respuesta final

```python
# orchestrator.py (simplificado)
async def handle_message(self, msg: IncomingMessage, channel: Channel):
    user = await self.identity.resolve(msg.channel, msg.channel_uid)
    conv = await self.identity.get_active_conversation(user.id)

    config = {"configurable": {"thread_id": conv.thread_id}}
    input_msg = {"messages": [{"role": "user", "content": msg.text}]}

    # Stream tokens al canal
    async for namespace, chunk in self.agent.astream(
        input_msg, config=config, stream_mode="messages", subgraphs=True
    ):
        token, metadata = chunk
        if not namespace and token.content:  # Solo main agent, no subagents
            await channel.send_token(msg.channel_uid, token.content)

    await channel.flush(msg.channel_uid)  # Enviar respuesta final
```

## Continuidad cross-canal

```
Terminal: "Hola, estoy diseñando una API REST"
  -> identity.resolve("terminal", "local") -> User(id=1)
  -> get_active_conversation(1) -> Conversation(thread_id="abc-123")
  -> agent.astream(input, config={"thread_id": "abc-123"})
  -> LangGraph persiste el mensaje y respuesta en el checkpoint de "abc-123"

Telegram: "Continúa con lo de la API"
  -> identity.resolve("telegram", "123456") -> User(id=1)  <- MISMO USER
  -> get_active_conversation(1) -> Conversation(thread_id="abc-123")  <- MISMO THREAD
  -> agent.astream(input, config={"thread_id": "abc-123"})
  -> LangGraph carga automáticamente el historial previo del checkpoint
  -> El LLM tiene todo el contexto (incluido lo dicho por terminal)
```

## Interfaz abstracta de canal

```python
class Channel(Protocol):
    name: str

    async def start(self, orchestrator: Orchestrator) -> None: ...
    async def stop(self) -> None: ...
    async def send_token(self, channel_uid: str, token: str) -> None: ...
    async def flush(self, channel_uid: str) -> None: ...
    async def send_typing(self, channel_uid: str) -> None: ...

    @property
    def max_message_length(self) -> int: ...
```

Cada canal implementa streaming de forma diferente:
- **Terminal**: `sys.stdout.write(token)` + flush por cada token. `flush()` es solo newline.
- **Telegram**: acumula tokens en buffer, edita mensaje cada ~1s (rate limit API), envía typing indicator cada 4s. `flush()` envía el mensaje final completo. Chunking a ~3500 chars respetando code fences.

## Configuración (config.toml)

```toml
[database]
url = "postgresql://user:pass@localhost:5432/deepmax"

[provider]
model = "anthropic:claude-sonnet-4-5-20250929"  # formato provider:model
system_prompt = "Eres un asistente personal útil y conciso."
# API keys via env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY

[channels.terminal]
enabled = true
user_name = "maximo"

[channels.telegram]
enabled = true
# Token via env var: TELEGRAM_BOT_TOKEN
allowed_users = [123456]

[identity.links.maximo]
terminal = "local"
telegram = "123456"

[limits]
shutdown_drain = 30
```

## Comandos del bot

Funcionan igual en terminal y en Telegram:

- `/new` — Nueva conversación (crea nuevo thread_id)
- `/history` — Ver conversaciones anteriores
- `/switch <id>` — Cambiar a otra conversación (cambia thread_id activo)
- `/title <texto>` — Poner título a la conversación actual
- `/model <provider:model>` — Cambiar modelo (e.g. `/model openai:gpt-4.1`)
- `/system <prompt>` — Cambiar system prompt
- `/memory` — Ver/editar memoria persistente del agente
- `/help` — Ayuda

### Cómo funciona `/model` en runtime

Cambiar modelo requiere recrear el agente con el nuevo modelo. Opciones:
1. **Lazy**: crear un dict de agents por modelo, cachear. Al cambiar, usar el agent correspondiente.
2. **Simple**: `create_deep_agent()` es rápido, recrear on-demand.

El thread_id se mantiene — el historial en LangGraph no depende del modelo.

```python
# Al cambiar modelo:
await identity.update_conversation_model(conv_id, "openai:gpt-4.1")
# El orchestrator usa el nuevo modelo en la siguiente invocación
```

## Memoria a largo plazo

Deep Agents soporta memoria persistente cross-conversación vía `CompositeBackend`:

- **Archivos en `/memories/`** persisten entre threads (vía PostgresStore)
- **Archivos en cualquier otra ruta** son efímeros (solo el thread actual)
- El agente puede escribir preferencias, notas, conocimiento acumulado
- `AGENTS.md` se carga automáticamente como contexto base

El `system_prompt` instruye al agente:
```
Tu memoria persistente está en /memories/. Guarda preferencias del usuario
y patrones que descubras en /memories/user_preferences.txt.
Lee /memories/ al inicio de conversaciones nuevas.
```

## Coexistencia Terminal + Telegram en asyncio

```python
async def main():
    config = load_config()
    agent, checkpointer, store = await create_bot_agent(config)
    db_pool = await asyncpg.create_pool(config.database.url)
    orchestrator = Orchestrator(agent, db_pool, config)

    tasks = []
    if config.channels.terminal.enabled:
        terminal = TerminalChannel()
        tasks.append(asyncio.create_task(terminal.start(orchestrator)))
    if config.channels.telegram.enabled:
        telegram = TelegramChannel(token=os.environ["TELEGRAM_BOT_TOKEN"])
        tasks.append(asyncio.create_task(telegram.start(orchestrator)))

    await asyncio.gather(*tasks)
```

**Terminal**: `prompt_toolkit.PromptSession.prompt_async()` — async-native.
**Telegram**: `aiogram.Dispatcher.start_polling()` — async-native.

## Graceful shutdown

```python
shutdown_event = asyncio.Event()

def _signal_handler():
    shutdown_event.set()

loop = asyncio.get_event_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, _signal_handler)
```

Secuencia:
1. `shutdown_event` se activa -> canales dejan de aceptar mensajes nuevos
2. Esperar a que streams en progreso terminen (timeout 30s)
3. Detener aiogram polling
4. Cerrar prompt_toolkit session
5. Cerrar pool asyncpg
6. Cerrar conexiones de checkpointer y store
7. Exit

## Pasos de implementación

1. **Setup del proyecto**: pyproject.toml con deepagents + langchain + aiogram + prompt_toolkit
2. **Config**: carga de config.toml + env vars (pydantic)
3. **Storage ligero**: pool asyncpg + schema SQL para users/identities/conversations
4. **Agent**: `create_bot_agent()` con Deep Agents SDK, PostgresSaver, PostgresStore
5. **Identity**: resolución cross-canal + CRUD de conversations (thread_id mapping)
6. **Orchestrator**: recibe mensajes, resuelve identidad, hace stream del agent, devuelve a canal
7. **Canal Terminal**: prompt_toolkit con streaming token-a-token y comandos
8. **Canal Telegram**: aiogram con typing indicator, streaming via edit, chunking
9. **Comandos**: /new, /switch, /model, /title, /system, /history, /memory, /help
10. **Main**: entry point con graceful shutdown
11. **AGENTS.md**: configurar memoria base del agente

## Verificación

1. Arrancar PostgreSQL local (Docker o nativo)
2. Crear tablas: ejecutar schema SQL + `checkpointer.setup()` + `store.setup()`
3. Arrancar el bot: `uv run python -m deepmax`
4. Escribir en terminal -> ver tokens aparecer progresivamente (streaming)
5. Escribir en Telegram -> ver typing indicator + respuesta
6. Verificar en terminal que el contexto de Telegram se mantiene y viceversa
7. `/new` -> verificar nueva conversación con thread_id distinto
8. `/switch` -> verificar cambio a conversación anterior con historial intacto
9. `/model openai:gpt-4.1` -> verificar cambio de modelo
10. Verificar que `/memories/` persiste entre conversaciones distintas
11. Enviar mensaje largo -> verificar chunking correcto en Telegram
12. Ctrl+C -> verificar shutdown limpio

## Secretos

API keys exclusivamente via env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `TELEGRAM_BOT_TOKEN`. Nunca en config.toml ni en código.
