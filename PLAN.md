# Plan: Bot Multi-Canal (Terminal + Telegram) con Deep Agents

## Context

Bot personal con el que pueda conversar por terminal y continuar la misma conversación por Telegram (y viceversa). Construido sobre el framework **Deep Agents SDK** (LangChain/LangGraph), que proporciona gestión de historial, streaming, planificación, subagentes y memoria a largo plazo de forma nativa. Solo necesitamos implementar los adaptadores de canal y la resolución de identidad cross-canal.

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

## Qué aporta Deep Agents vs el plan anterior

| Antes (manual)                      | Ahora (Deep Agents SDK)                          |
|-------------------------------------|--------------------------------------------------|
| litellm + wrapper propio            | `create_deep_agent(model="provider:model")`      |
| asyncpg + SQL crudo para mensajes   | PostgresSaver (checkpoints) + PostgresStore       |
| Historial manual con `get_history`  | LangGraph gestiona historial vía `thread_id`     |
| Streaming manual por canal          | `agent.stream(stream_mode="messages")`            |
| ConversationLocks con asyncio.Lock  | LangGraph serializa por thread_id internamente   |
| Gestión manual de ventana contexto  | Auto-summarización + offloading de tool results  |
| Sin planificación                   | `write_todos` built-in                           |
| Sin subagentes                      | `task` tool para delegar trabajo aislado         |
| Sin memoria cross-conversación      | CompositeBackend con `/memories/` persistente    |

**Lo que seguimos implementando nosotros:**
- Adaptadores de canal (Terminal + Telegram)
- Resolución de identidad cross-canal
- Access control
- Tabla ligera de "conversaciones" (mapea user -> thread_id + metadata)
- Graceful shutdown
- Comandos del bot (/new, /switch, /model, etc.)

## Stack tecnológico

- **Python 3.12+** con `asyncio`
- **deepagents** — Framework de agentes con planificación, subagentes, filesystem y streaming
- **langchain[anthropic,openai,google-genai]** — Integraciones LLM
- **langgraph** — Runtime con checkpointing y store persistente
- **langgraph-checkpoint-postgres** — Persistencia de estado en PostgreSQL
- **langgraph-store-postgres** — Store para memoria a largo plazo
- **aiogram 3** — Telegram bot framework (async-native)
- **prompt_toolkit** — Terminal interactivo con historial
- **asyncpg** — Solo para nuestra tabla ligera de identidades/conversaciones
- **pydantic** — Validación de config

## Estructura del proyecto

```
bots/multibot/
├── pyproject.toml
├── config.example.toml
├── AGENTS.md                 # Memoria persistente del agente (convenciones, preferencias)
├── skills/                   # Skills opcionales del agente
│   └── .gitkeep
├── src/
│   └── multibot/
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
    """Crea el Deep Agent con persistencia PostgreSQL."""
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
        # tools personalizados se pueden añadir aquí
        tools=[],
    )

    return agent, checkpointer, store
```

**Modelo multi-proveedor**: Deep Agents usa el formato `provider:model`:
- `"anthropic:claude-sonnet-4-5-20250929"`
- `"openai:gpt-4.1"`
- `"google_genai:gemini-2.5-flash-lite"`

Cambiable en runtime por conversación con `/model`.

## Schema PostgreSQL (solo identidades + metadata)

LangGraph crea sus propias tablas para checkpoints y store.
Nosotros solo necesitamos:

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

-- Índices
CREATE INDEX idx_channel_identities_lookup ON channel_identities(channel, channel_uid);
```

**No hay tabla `messages`** — LangGraph almacena todo el historial en sus tablas de checkpoints,
accesible vía `thread_id`. Eliminamos ~50% del SQL del plan anterior.

## Flujo de un mensaje

1. **Canal recibe mensaje** (terminal input / Telegram update)
2. **Access control** — verifica que el usuario está autorizado
3. Canal normaliza a `IncomingMessage(channel, channel_uid, text)`
4. **Orchestrator** recibe el `IncomingMessage`:
   a. `identity.resolve(channel, channel_uid)` -> busca/crea `User`
   b. `identity.get_active_conversation(user_id)` -> obtiene `Conversation` activa (con thread_id y model)
   c. Prepara config de LangGraph: `{"configurable": {"thread_id": conv.thread_id}}`
   d. **Streaming**: itera sobre `agent.stream(input, config, stream_mode="messages", subgraphs=True)`
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

## Cómo funciona la continuidad cross-canal

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
url = "postgresql://user:pass@localhost:5432/multibot"

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
3. Arrancar el bot: `uv run python -m multibot`
4. Escribir en terminal -> ver tokens aparecer progresivamente (streaming)
5. Escribir en Telegram -> ver typing indicator + respuesta
6. Verificar en terminal que el contexto de Telegram se mantiene y viceversa
7. `/new` -> verificar nueva conversación con thread_id distinto
8. `/switch` -> verificar cambio a conversación anterior con historial intacto
9. `/model openai:gpt-4.1` -> verificar cambio de modelo
10. Verificar que `/memories/` persiste entre conversaciones distintas
11. Enviar mensaje largo -> verificar chunking correcto en Telegram
12. Ctrl+C -> verificar shutdown limpio
