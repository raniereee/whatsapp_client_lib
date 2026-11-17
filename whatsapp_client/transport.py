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


class TemplateResult(NamedTuple):
    """Resposta da Meta ao criar/apagar template."""

    ok: bool
    template_id: Optional[str] = None
    status: Optional[str] = None  # PENDING / APPROVED / REJECTED na criação
    error_code: Optional[int] = None
    error_detail: str = ""


def _template_error(response) -> TemplateResult:
    """A Meta põe a explicação legível em error_user_msg (ex.: "o corpo não
    pode começar com variável"); o `message` é genérico."""
    error = _json(response).get("error") or {}
    code = error.get("code")
    detail = " — ".join(
        p for p in (error.get("error_user_title"), error.get("error_user_msg")) if p
    ) or error.get("message") or response.text[:300]
    return TemplateResult(ok=False, error_code=code if isinstance(code, int) else None, error_detail=detail)


def create_template(channel: str, waba_id: str, template: dict) -> TemplateResult:
    """Submete o template (name, language, category, components) para
    aprovação. Criar NÃO é idempotente: só repete se a conexão nem abriu."""
    try:
        response = meta_http.post(_url(f"{waba_id}/message_templates"), headers=_auth(channel), json=template)
    except requests.RequestException as e:
        log.error("transport.create_template_no_response", name=template.get("name"), error=str(e))
        return TemplateResult(ok=False, error_detail="sem resposta da Meta")
    if not response.ok:
        result = _template_error(response)
        log.warning("transport.create_template_refused", name=template.get("name"), detail=result.error_detail)
        return result
    data = _json(response)
    return TemplateResult(ok=True, template_id=data.get("id"), status=data.get("status"))


def delete_template(channel: str, waba_id: str, name: str, template_id: Optional[str] = None) -> TemplateResult:
    """Apaga o template. Com `template_id`, só aquele idioma; sem, todos os
    idiomas do nome. A Meta bloqueia recriar o mesmo nome por ~4 semanas."""
    params = {"name": name}
    if template_id:
        params["hsm_id"] = template_id
    try:
        response = meta_http.delete(_url(f"{waba_id}/message_templates"), headers=_auth(channel), params=params)
    except requests.RequestException as e:
        log.error("transport.delete_template_no_response", name=name, error=str(e))
        return TemplateResult(ok=False, error_detail="sem resposta da Meta")
    if not response.ok:
        return _template_error(response)
    return TemplateResult(ok=bool(_json(response).get("success")))


def upload_template_example(channel: str, app_id: str, content: bytes, mime: str) -> Optional[str]:
    """Sobe o arquivo de EXEMPLO de um cabeçalho de mídia (Resumable Upload
    API) e devolve o `header_handle`. Serve só para a revisão da Meta: o
    arquivo de verdade vai em cada envio. `app_id` tem de ser o app dono do
    token do canal."""
    token = _token(channel)
    try:
        session = meta_http.post(
            _url(f"{app_id}/uploads"),
            params={"file_length": len(content), "file_type": mime, "access_token": token},
        )
        session.raise_for_status()
        upload = meta_http.post(
            _url(_json(session)["id"]),
            headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
            data=content,
            timeout=(meta_http.TIMEOUT_S, 60),
        )
        upload.raise_for_status()
        return _json(upload).get("h")
    except (requests.RequestException, KeyError) as e:
        log.error("transport.upload_example_failed", app_id=app_id, error=str(e))
        return None
