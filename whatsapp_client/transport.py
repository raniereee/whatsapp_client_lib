"""Transporte puro da Graph API: só HTTP, sem banco.

Diferente do `official`, aqui nada grava em `messages_wpp` e todo envio
DEVOLVE o que a Meta respondeu — quem chama decide o que guardar e onde.
Existe para consumidor com histórico próprio (o chat do Financeiro, no
backend_billing). O `official` pode passar a usar estas funções por dentro.

Token por canal (phone_number_id) e base da API vêm do `configure()`, como no
resto da lib. O payload de mensagem é montado por quem chama; aqui só entra o
`messaging_product`.
"""

from typing import NamedTuple, Optional

import requests
import structlog

from whatsapp_client import config, meta_http

log = structlog.get_logger()

# Texto/mídia fora da janela de 24h: só template passa.
OUTSIDE_WINDOW = 131047


class SendResult(NamedTuple):
    wamid: Optional[str] = None
    # Número que o WhatsApp usa de verdade para o destinatário (com ou sem o
    # nono dígito). É por ele que a resposta da pessoa vai chegar.
    wa_id: Optional[str] = None
    error_code: Optional[int] = None
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.wamid is not None


class Media(NamedTuple):
    content: bytes
    mime: str


def _token(channel: str) -> str:
    return config.APIS_AVAILABLE.get(channel, "")


def _auth(channel: str) -> dict:
    return {"Authorization": f"Bearer {_token(channel)}"}


def _url(path: str) -> str:
    return f"{config.META_BASE_URL}/{path.lstrip('/')}"


def _json(response) -> dict:
    try:
        return response.json() or {}
    except ValueError:
        return {}


def send_payload(channel: str, payload: dict) -> SendResult:
    """POSTa uma mensagem (`to`, `type`, conteúdo, `context`...) pelo número
    `channel`. Só repete se a conexão nem abriu — ver meta_http.post."""
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
    try:
        response = meta_http.post(_url(f"{channel}/messages"), headers=_auth(channel), json=body)
    except requests.RequestException as e:
        log.error("transport.send_no_response", channel=channel, type=payload.get("type"), error=str(e))
        return SendResult(error_detail="sem resposta da Meta")
    data = _json(response)
    if response.ok and data.get("messages"):
        return SendResult(
            wamid=data["messages"][0].get("id"),
            wa_id=(data.get("contacts") or [{}])[0].get("wa_id"),
        )
    error = data.get("error") or {}
    code = error.get("code")
    result = SendResult(
        error_code=code if isinstance(code, int) else None,
        error_detail=(error.get("error_data") or {}).get("details")
        or error.get("message")
        or response.text[:300],
    )
    log.warning(
        "transport.send_refused",
        channel=channel,
        type=payload.get("type"),
        code=result.error_code,
        detail=result.error_detail,
    )
    return result


def mark_read(channel: str, wamid: str) -> None:
    """Checks azuis no celular da pessoa. Falha só é logada."""
    try:
        meta_http.post_idempotente(
            _url(f"{channel}/messages"),
            headers=_auth(channel),
            json={"messaging_product": "whatsapp", "status": "read", "message_id": wamid},
        )
    except requests.RequestException as e:
        log.warning("transport.mark_read_failed", wamid=wamid, error=str(e))


def upload_media(channel: str, content: bytes, mime: str, filename: str) -> Optional[str]:
    """Sobe bytes para a Meta e devolve o media_id (vale 30 dias, por número).
    Upload repetido só gera outro media_id, então repetir é seguro."""
    try:
        response = meta_http.post_idempotente(
            _url(f"{channel}/media"),
            headers=_auth(channel),
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (filename, content, mime)},
            timeout=(meta_http.TIMEOUT_S, 120),
        )
        response.raise_for_status()
        return _json(response).get("id")
    except requests.RequestException as e:
        log.error("transport.upload_failed", channel=channel, mime=mime, error=str(e))
        return None


def download_media(channel: str, media_id: str) -> Optional[Media]:
    """Baixa uma mídia recebida. Dois passos: os metadados trazem uma URL
    temporária (~5 min), baixada em seguida com o mesmo token."""
    try:
        meta = meta_http.get(_url(f"{media_id}?phone_number_id={channel}"), headers=_auth(channel))
        meta.raise_for_status()
        info = _json(meta)
        if not info.get("url"):
            log.warning("transport.media_without_url", media_id=media_id)
            return None
        file = meta_http.get(info["url"], headers=_auth(channel), timeout=(meta_http.TIMEOUT_S, 60))
        file.raise_for_status()
        return Media(file.content, info.get("mime_type") or "")
    except requests.RequestException as e:
        log.error("transport.download_failed", media_id=media_id, error=str(e))
        return None


_TEMPLATE_FIELDS = "id,name,language,category,status,components,rejected_reason"


def list_templates(channel: str, waba_id: str, name: Optional[str] = None) -> Optional[list]:
    """Templates da WABA (paginando). `name` filtra por PREFIXO, como a Meta
    faz. None se a consulta falhou — diferente de lista vazia."""
    params = {"fields": _TEMPLATE_FIELDS, "limit": 100}
    if name:
        params["name"] = name
    url = _url(f"{waba_id}/message_templates")
    templates = []
    try:
        while url:
            response = meta_http.get(url, headers=_auth(channel), params=params)
            response.raise_for_status()
            data = _json(response)
            templates.extend(data.get("data") or [])
            url = (data.get("paging") or {}).get("next")
            params = None  # o `next` já carrega os parâmetros
    except requests.RequestException as e:
        log.error("transport.list_templates_failed", waba_id=waba_id, error=str(e))
        return None
    return templates


def get_template(channel: str, waba_id: str, name: str, language: str) -> Optional[dict]:
    """O template com este nome EXATO e idioma, ou None."""
    for template in list_templates(channel, waba_id, name=name) or []:
        if template.get("name") == name and template.get("language") == language:
            return template
    return None
