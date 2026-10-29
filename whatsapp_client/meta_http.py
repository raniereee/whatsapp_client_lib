"""Chamadas HTTP à Graph API da Meta, com timeout curto e novas tentativas.

Cópia do `facilita/services/meta_http.py` (commit 21756d3 do backend_facilita).
Em 29/10/2026 a rede da Hostinger passou a perder de 25% a 75% das conexões
TCP de SAÍDA (os três VPS, para a Meta, a Cloudflare e a Anthropic; ICMP
limpo). Aqui, sem timeout nenhum, cada conexão perdida prendia um processo do
worker do WhatsApp por ~2 min em SYN-SENT: com os 8 presos ao mesmo tempo, o
bot parou de responder e 5 das 28 mensagens da bússola do cloro livre não
saíram. Três tentativas de 5 s transformam 25% de perda em ~1,5%.

O que se repete depende do que a falha garante:

- `post` (envio de mensagem): só falha de CONEXÃO — o pedido nem chegou à
  Meta. Se a conexão abriu e a resposta é que demorou, a mensagem pode já ter
  saído; repetir mandaria duas vezes para o produtor.
- `post_idempotente` e `get` (marcar como lida, "digitando", upload e
  download de mídia): qualquer falha de rede. Repetir não muda nada do lado de
  lá (um upload repetido só gera outro media_id).
"""

import requests
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)
from urllib3.exceptions import NewConnectionError

log = structlog.get_logger()

TIMEOUT_S = 5
TENTATIVAS = 3
_ESPERA_S = 0.5


def _nao_chegou_a_meta(e: BaseException) -> bool:
    """A conexão nem abriu: timeout de connect, recusa ou rota inexistente.

    O requests embrulha o `NewConnectionError` do urllib3 num ConnectionError
    genérico — o mesmo tipo de quando a conexão cai DEPOIS do envio — e por
    isso a causa é lida no `reason`, não no tipo."""
    if isinstance(e, requests.ConnectTimeout):
        return True
    if isinstance(e, requests.ConnectionError) and e.args:
        return isinstance(getattr(e.args[0], "reason", None), NewConnectionError)
    return False


def _avisar(estado) -> None:
    log.warning(
        "meta_http.nova_tentativa",
        tentativa=estado.attempt_number,
        erro=str(estado.outcome.exception()),
    )


_so_conexao = retry(
    retry=retry_if_exception(_nao_chegou_a_meta),
    stop=stop_after_attempt(TENTATIVAS),
    wait=wait_fixed(_ESPERA_S),
    before_sleep=_avisar,
    reraise=True,
)

_qualquer_falha_de_rede = retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(TENTATIVAS),
    wait=wait_fixed(_ESPERA_S),
    before_sleep=_avisar,
    reraise=True,
)


@_so_conexao
def post(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT_S)
    return requests.post(url, **kwargs)


@_qualquer_falha_de_rede
def post_idempotente(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT_S)
    return requests.post(url, **kwargs)


@_qualquer_falha_de_rede
def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT_S)
    return requests.get(url, **kwargs)


@_so_conexao
def delete(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT_S)
    return requests.delete(url, **kwargs)
