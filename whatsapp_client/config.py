"""Config injetável da lib — populada pelo app no bootstrap.

A lib NÃO conhece env vars nem o config do app. O consumidor chama
``configure(apis_available=..., meta_base_url=...)`` uma única vez no startup
(ex.: no boot do worker Celery), antes do primeiro envio.

As funções de ``official`` referenciam ``config.META_BASE_URL`` /
``config.APIS_AVAILABLE`` em runtime (não capturam o valor no import), então
``configure`` pode rodar depois do import do módulo sem problema.
"""

# Base da Graph API da Meta (ex.: "https://graph.facebook.com/v21.0").
META_BASE_URL = ""

# Mapa phone_number_id (channel) -> token da Meta de cada parceiro.
APIS_AVAILABLE = {}

# Aliases de canal -> phone_number_id canônico. Ex.: um número de telefone de
# parceiro ("554932000112") mapeado pro phone_number_id da Meta
# ("741961865659795"). É conhecimento de APLICAÇÃO (quais canais/parceiros a Z1
# tem) — a lib não o hardcoda; o consumidor injeta via configure() (na Z1 vem do
# monitor_settings). Vazio = sem aliases, o channel é usado como veio.
CHANNEL_ALIASES = {}


def configure(apis_available=None, meta_base_url=None, channel_aliases=None):
    """Injeta a config do app na lib. Idempotente; chame no bootstrap antes
    do primeiro envio. Argumentos omitidos (None) preservam o valor atual."""
    global META_BASE_URL, APIS_AVAILABLE, CHANNEL_ALIASES
    if apis_available is not None:
        APIS_AVAILABLE = apis_available
    if meta_base_url is not None:
        META_BASE_URL = meta_base_url
    if channel_aliases is not None:
        CHANNEL_ALIASES = channel_aliases
