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


def configure(apis_available=None, meta_base_url=None):
    """Injeta a config do app na lib. Idempotente; chame no bootstrap antes
    do primeiro envio. Argumentos omitidos (None) preservam o valor atual."""
    global META_BASE_URL, APIS_AVAILABLE
    if apis_available is not None:
        APIS_AVAILABLE = apis_available
    if meta_base_url is not None:
        META_BASE_URL = meta_base_url
