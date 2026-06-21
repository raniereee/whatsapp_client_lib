import requests
import uuid
import structlog
from whatsapp_client import config
from z1monitoring_models.models.messages import MessageWpp
from z1monitoring_models.models.waid_messageid_rel import TemplateMessageIdRel

# from monitoring.utils.miscs import generate_string_id

log = structlog.get_logger()


class Message:
    msisdn = "(48) 98833-1991"
    text = "1"
    chat_id = "(48) 98833-1991"
    channel = ""
    unique_id = None
    msg_type = None
    flow_token = None
    flow_response_json = None
    bsuid = None
    image_id = None
    document_id = None
    file_name = None
    audio_id = None


def decode_msg(infos):
    m = Message()
    m.msisdn = infos.get("from")
    # BSUID (Business-Scoped User ID da Meta): identidade resiliente quando
    # o número (`from`) vier ausente ou como BSUID. Fase 1.
    m.bsuid = infos.get("from_user_id")
    m.msg_type = infos.get("type")
    waid = infos.get("id")
    if m.msg_type == "text":
        m.text = infos.get("text").get("body")

    elif m.msg_type == "interactive":
        interactive = infos.get("interactive")

        if interactive.get("type") == "list_reply":
            # {'type': 'list_reply', 'list_reply': {'id': '3437712b9441402687e95abb9cfb3a51', 'title': 'Alarmes ocorridos'}
            list_reply = interactive.get("list_reply")
            m.text = list_reply.get("title")
            unique_id = list_reply.get("id", "")
            m.unique_id = unique_id.split("+")[0]

        elif interactive.get("type") == "button_reply":
            # {'type': 'button_reply', 'button_reply': {'id': 'nao', 'title': 'Não'}}

            button_reply = interactive.get("button_reply")
            m.text = button_reply.get("title")
            unique_id = button_reply.get("id", "")
            m.unique_id = unique_id.split("+")[0]

        elif interactive.get("type") == "nfm_reply":
            # Resposta de WhatsApp Flow (mensagem interactive type=flow).
            # {
            #   "type": "nfm_reply",
            #   "nfm_reply": {
            #     "response_json": "{\"plano\":\"anual\",\"dia_vencimento\":\"10\",\"flow_token\":\"...\"}",
            #     "body": "Form submitted",
            #     "name": "flow"
            #   }
            # }
            nfm_reply = interactive.get("nfm_reply") or {}
            m.text = nfm_reply.get("body") or "Flow submitted"
            m.flow_response_json = nfm_reply.get("response_json")
            # flow_token vem dentro do response_json (echoed pelo Meta a partir do envio).
            try:
                import json as _json

                parsed = _json.loads(nfm_reply.get("response_json") or "{}")
                m.flow_token = parsed.get("flow_token")
            except (ValueError, TypeError):
                m.flow_token = None

    elif m.msg_type == "button":
        # Resposta de botão de template - extrair texto e payload
        button_info = infos.get("button", {})
        m.text = button_info.get("text", "")
        m.unique_id = TemplateMessageIdRel.load(waid)

    elif m.msg_type == "image":
        image_info = infos.get("image", {})
        m.image_id = image_info.get("id")
        m.text = image_info.get("caption", "")

    elif m.msg_type == "document":
        doc_info = infos.get("document", {})
        m.document_id = doc_info.get("id")
        m.text = doc_info.get("caption", "")
        m.file_name = doc_info.get("filename", "")

    elif m.msg_type == "video":
        m.text = infos.get("caption")

    elif m.msg_type == "audio":
        m.audio_id = infos.get("audio", {}).get("id")

    m.chat_id = m.msisdn
    m.channel = infos.get("phone_number_channel")

    return m


def send_typing_indicator(message_id, channel):
    """
    Envia indicador de 'digitando' para o usuário.
    O typing indicator dura até 25 segundos ou até enviar a resposta.
    Também marca a mensagem como lida automaticamente.
    """
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    HEADERS = {
        "Authorization": f"Bearer {META_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
    except Exception as e:
        log.error("typing_indicator_failed", error=str(e), message_id=message_id)


def mark_message_read(message_id, channel):
    """Marca a mensagem como lida no WhatsApp"""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    HEADERS = {
        "Authorization": f"Bearer {META_API_KEY}",
        "Content-Type": "application/json",
    }
    # Salva com wamid extraído do message_id
    MessageWpp(data, channel, channel, wamid=message_id, status="read")
    try:
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
    except Exception as e:
        log.error("mark_read_failed", error=str(e), message_id=message_id)


def send_location(channel, phone_number, latitude, longitude, name, address):
    """Envia uma localização para o WhatsApp"""
    WAPP_NUMBER_ID = channel
    url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
        },
    }
    HEADERS = {
        "Authorization": f"Bearer {META_API_KEY}",
        "Content-Type": "application/json",
    }
    wamid = None
    try:
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_location_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def retrieve_media(channel, media_id):
    """Retorna o media do WhatsApp"""
    WAPP_NUMBER_ID = channel
    url = f"{config.META_BASE_URL}/{media_id}?phone_number_id={WAPP_NUMBER_ID}"
    log.info(f"url: {url}")
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    HEADERS = {
        "Authorization": f"Bearer {META_API_KEY}",
    }
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(
            "retrieve_media_error",
            error=str(e),
            media_id=media_id,
            response=getattr(getattr(e, "response", None), "text", ""),
        )


def media_download(channel, url):
    """Retorna o media do WhatsApp"""
    # WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    HEADERS = {
        "Authorization": f"Bearer {META_API_KEY}",
    }

    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.content
    except Exception as e:
        log.error("media_download_error", error=str(e), response=getattr(getattr(e, "response", None), "text", ""))


def location_request(channel, phone_number, msg):
    log.info(f"Sending location request to {phone_number}")
    WAPP_NUMBER_ID = channel
    url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    try:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "to": phone_number,
            "interactive": {
                "type": "location_request_message",
                "body": {"text": msg},
                "action": {"name": "send_location"},
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }

        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()

    except Exception as e:
        log.error(
            "location_request_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        # Sempre salva a tentativa de envio no banco
        log.info("""Salvando mensagem no banco de dados""")


def send_buttons(channel, phone_number, message, buttons, footer_text="Escolha uma opção"):
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending buttons message to {phone_number}: {message}")
    log.info(f"buttons: {buttons}")
    buttons_payload = []
    for i, button in enumerate(buttons):
        if isinstance(button, str):
            btn_id = f"btn_{i}"
            btn_title = button[:20]  # limite de 20 chars da API Meta
        else:
            btn_id = button.get("id", f"btn_{i}")
            btn_title = button.get("title", "")[:20]
        buttons_payload.append(
            {
                "type": "reply",
                "reply": {
                    "id": btn_id,
                    "title": btn_title,
                },
            }
        )

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": message},
                "footer": {"text": footer_text},
                "action": {"buttons": buttons_payload},
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_buttons_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_list(
    channel,
    phone_number,
    message,
    rows,
    footer_text="Escolha uma opção",
    button_text="Escolher",
    section_title=None,
):
    # button_text / footer_text / section_title são textos de UI da lista.
    # Defaults em PT por retrocompat; o app (presenter) passa traduzidos por
    # idioma. A lib não decide idioma — só transporta o que recebe.
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending list message to {phone_number}: {message}")
    # Meta limita lista interativa a 10 rows; title máx 24 chars.
    # Defensivo: trunca pra não dar 400 da API. Caller deve idealmente
    # cuidar disso e avisar o user que a lista foi truncada.
    META_LIST_MAX_ROWS = 10
    META_LIST_TITLE_MAX = 24
    if len(rows) > META_LIST_MAX_ROWS:
        log.warning(
            "send_list truncando rows acima do limite Meta",
            total=len(rows),
            cap=META_LIST_MAX_ROWS,
            phone=phone_number,
        )
        rows = rows[:META_LIST_MAX_ROWS]
    buttons_payload = []
    for row in rows:
        title = row if len(row) <= META_LIST_TITLE_MAX else row[: META_LIST_TITLE_MAX - 1] + "…"
        buttons_payload.append({"id": uuid.uuid4().hex, "title": title})

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": message},
                "footer": {"text": footer_text},
                "action": {
                    "button": button_text,
                    "sections": [{"title": section_title or footer_text, "rows": buttons_payload}],
                },
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_list_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_text_message(phone_number, channel, message):

    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending text message to {phone_number}: {message}")
    wamid = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": message,
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_text_message_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_text_message_by_bsuid(bsuid, channel, message):
    """Envia texto usando o BSUID (Business-Scoped User ID) no campo
    `recipient`, em vez do telefone no `to`. Usar quando só houver o BSUID —
    a Meta parou de mandar o número (rollout de usernames). Método separado
    de propósito: não toca o send_text_message por telefone, pra não quebrar
    os fluxos existentes. Ver doc Meta business-scoped-user-ids.

    O BSUID é a chave de identidade gravada em messages_wpp (a correlação
    BSUID<->telefone e a exibição são resolvidas na leitura)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending text message to BSUID {bsuid}: {message}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "text",
            "text": {
                "body": message,
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_text_message_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            # O BSUID é a chave de identidade da conversa.
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_template_by_bsuid(bsuid, channel, template_id, values, messageid=None):
    """Como send_template, mas endereça pelo BSUID (campo `recipient`) em vez
    do telefone (`to`). Usar quando o destinatário só tem BSUID. O BSUID é a
    chave de identidade gravada em messages_wpp."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending template to BSUID {bsuid}: {template_id}")
    values_payload = []
    for value in values:
        values_payload.append({"type": "text", "text": value})

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "template",
            "template": {
                "name": template_id,
                "language": {"code": "pt_BR"},
                "components": [{"type": "body", "parameters": values_payload}],
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

            if messageid:
                TemplateMessageIdRel(messageid, wamid)

    except Exception as e:
        log.error(
            "send_template_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_buttons_by_bsuid(bsuid, channel, message, buttons, footer_text="Escolha uma opção"):
    """Como send_buttons, mas endereça pelo BSUID (campo `recipient`). O BSUID
    é a chave de identidade gravada em messages_wpp."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending buttons to BSUID {bsuid}: {message}")
    buttons_payload = []
    for i, button in enumerate(buttons):
        if isinstance(button, str):
            btn_id = f"btn_{i}"
            btn_title = button[:20]  # limite de 20 chars da API Meta
        else:
            btn_id = button.get("id", f"btn_{i}")
            btn_title = button.get("title", "")[:20]
        buttons_payload.append(
            {
                "type": "reply",
                "reply": {
                    "id": btn_id,
                    "title": btn_title,
                },
            }
        )

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": message},
                "footer": {"text": footer_text},
                "action": {"buttons": buttons_payload},
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_buttons_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_image(channel, phone_number, message, image_url):

    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending image message to {phone_number}: {message} - image_url: {image_url}")
    wamid = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "image",
            "image": {"link": image_url, "caption": message},
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_image_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_image_upload(channel, phone_number, message, file_path):
    """
    Envia imagem via upload direto para Meta (mais confiável que link).

    1. Faz upload do arquivo para Media API
    2. Envia mensagem com o media_id
    """
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Uploading image to Meta: {file_path}")
    wamid = None
    data = {}

    try:
        # 1. Upload do arquivo
        upload_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {META_API_KEY}"}

        with open(file_path, "rb") as f:
            files = {
                "file": (file_path.split("/")[-1], f, "image/png"),
            }
            form_data = {
                "messaging_product": "whatsapp",
                "type": "image/png",
            }
            upload_response = requests.post(upload_url, headers=headers, files=files, data=form_data)
            upload_response.raise_for_status()
            upload_json = upload_response.json()

        media_id = upload_json.get("id")
        if not media_id:
            log.error(f"Falha no upload da imagem: {upload_json}")
            # Fallback para link
            return send_image(
                channel, phone_number, message, f"https://img.monitora.pro/space/{file_path.split('/')[-1]}"
            )

        # 2. Envia mensagem com media_id
        msg_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "image",
            "image": {"id": media_id, "caption": message},
        }
        headers = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(msg_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_image_upload_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )
        # Fallback para link
        return send_image(channel, phone_number, message, f"https://img.monitora.pro/space/{file_path.split('/')[-1]}")

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_audio(channel, phone_number, audio_url):
    """Envia áudio via WhatsApp Business API."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending audio message to {phone_number} - audio_url: {audio_url}")
    wamid = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "audio",
            "audio": {"link": audio_url},
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_audio_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_document(channel, phone_number, message, document_url):
    """Envia documento (XLSX, PDF, etc) via WhatsApp Business API."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    file_name = document_url.split("/")[-1]
    log.info(f"Sending document message to {phone_number}: {message} - url: {document_url}")
    wamid = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "document",
            "document": {
                "link": document_url,
                "caption": message,
                "filename": file_name,
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_document_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_document_upload(channel, phone_number, message, file_path, mime="application/pdf"):
    """Envia documento (PDF, XLSX) via UPLOAD direto para a Meta (media_id).

    Análogo a send_image_upload: o arquivo NÃO precisa estar numa URL pública —
    sobe pra Media API e envia pelo media_id. Use para conteúdo privado (ex.:
    relatório com dados do produtor) que não deve ficar hospedado publicamente.

    1. Upload do arquivo para a Media API -> media_id
    2. Envia a mensagem 'document' com o media_id
    """
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    file_name = file_path.split("/")[-1]
    log.info(f"Uploading document to Meta: {file_path}")
    wamid = None
    data = {}

    try:
        # 1. Upload do arquivo
        upload_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {META_API_KEY}"}

        with open(file_path, "rb") as f:
            files = {
                "file": (file_name, f, mime),
            }
            form_data = {
                "messaging_product": "whatsapp",
                "type": mime,
            }
            upload_response = requests.post(upload_url, headers=headers, files=files, data=form_data)
            upload_response.raise_for_status()
            upload_json = upload_response.json()

        media_id = upload_json.get("id")
        if not media_id:
            log.error(f"Falha no upload do documento: {upload_json}")
            return

        # 2. Envia mensagem com media_id
        msg_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "document",
            "document": {"id": media_id, "caption": message, "filename": file_name},
        }
        headers = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(msg_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_document_upload_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


def send_contacts(channel, phone_number, contacts):
    """
    Envia contatos via WhatsApp Business API.

    Args:
        channel: ID do número WhatsApp Business
        phone_number: Número do destinatário
        contacts: Lista de contatos no formato:
            [{"name": {"formatted_name": "Nome"}, "phones": [{"phone": "+5548988331991"}]}]
    """
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending contacts to {phone_number}: {contacts}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "contacts",
            "contacts": contacts,
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_contacts_error",
            error=str(e),
            phone=phone_number,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, phone_number, channel, wamid=wamid, status="sent")


# --- Variantes por BSUID das mensagens de conteúdo. Endereçam pelo campo
# `recipient` (BSUID) em vez de `to` (telefone) e gravam a conversa pelo BSUID
# (chave de identidade). Migração BSUID: abandonar o endereçamento por telefone.


def send_list_by_bsuid(
    bsuid,
    channel,
    message,
    rows,
    footer_text="Escolha uma opção",
    button_text="Escolher",
    section_title=None,
):
    """Como send_list, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending list to BSUID {bsuid}: {message}")
    META_LIST_MAX_ROWS = 10
    META_LIST_TITLE_MAX = 24
    if len(rows) > META_LIST_MAX_ROWS:
        log.warning(
            "send_list_by_bsuid truncando rows acima do limite Meta",
            total=len(rows),
            cap=META_LIST_MAX_ROWS,
            bsuid=bsuid,
        )
        rows = rows[:META_LIST_MAX_ROWS]
    buttons_payload = []
    for row in rows:
        title = row if len(row) <= META_LIST_TITLE_MAX else row[: META_LIST_TITLE_MAX - 1] + "…"
        buttons_payload.append({"id": uuid.uuid4().hex, "title": title})

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": message},
                "footer": {"text": footer_text},
                "action": {
                    "button": button_text,
                    "sections": [{"title": section_title or footer_text, "rows": buttons_payload}],
                },
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_list_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_image_by_bsuid(bsuid, channel, message, image_url):
    """Como send_image, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending image to BSUID {bsuid}: {message} - image_url: {image_url}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "image",
            "image": {"link": image_url, "caption": message},
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_image_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_image_upload_by_bsuid(bsuid, channel, message, file_path):
    """Como send_image_upload, mas endereça pelo BSUID. Fallback pro link via
    send_image_by_bsuid."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Uploading image to Meta (BSUID {bsuid}): {file_path}")
    wamid = None
    data = {}
    try:
        upload_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {META_API_KEY}"}
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f, "image/png")}
            form_data = {"messaging_product": "whatsapp", "type": "image/png"}
            upload_response = requests.post(upload_url, headers=headers, files=files, data=form_data)
            upload_response.raise_for_status()
            upload_json = upload_response.json()

        media_id = upload_json.get("id")
        if not media_id:
            log.error(f"Falha no upload da imagem: {upload_json}")
            return send_image_by_bsuid(
                bsuid, channel, message, f"https://img.monitora.pro/space/{file_path.split('/')[-1]}"
            )

        msg_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "image",
            "image": {"id": media_id, "caption": message},
        }
        headers = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(msg_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_image_upload_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )
        return send_image_by_bsuid(
            bsuid, channel, message, f"https://img.monitora.pro/space/{file_path.split('/')[-1]}"
        )

    finally:
        MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_audio_by_bsuid(bsuid, channel, audio_url):
    """Como send_audio, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending audio to BSUID {bsuid} - audio_url: {audio_url}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "audio",
            "audio": {"link": audio_url},
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_audio_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_document_by_bsuid(bsuid, channel, message, document_url):
    """Como send_document, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    file_name = document_url.split("/")[-1]
    log.info(f"Sending document to BSUID {bsuid}: {message} - url: {document_url}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "document",
            "document": {
                "link": document_url,
                "caption": message,
                "filename": file_name,
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_document_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_document_upload_by_bsuid(bsuid, channel, message, file_path, mime="application/pdf"):
    """Como send_document_upload, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    file_name = file_path.split("/")[-1]
    log.info(f"Uploading document to Meta (BSUID {bsuid}): {file_path}")
    wamid = None
    data = {}
    try:
        upload_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {META_API_KEY}"}
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, mime)}
            form_data = {"messaging_product": "whatsapp", "type": mime}
            upload_response = requests.post(upload_url, headers=headers, files=files, data=form_data)
            upload_response.raise_for_status()
            upload_json = upload_response.json()

        media_id = upload_json.get("id")
        if not media_id:
            log.error(f"Falha no upload do documento: {upload_json}")
            return

        msg_url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "document",
            "document": {"id": media_id, "caption": message, "filename": file_name},
        }
        headers = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(msg_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_document_upload_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_contacts_by_bsuid(bsuid, channel, contacts):
    """Como send_contacts, mas endereça pelo BSUID (campo `recipient`)."""
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending contacts to BSUID {bsuid}: {contacts}")
    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": bsuid,
            "type": "contacts",
            "contacts": contacts,
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

    except Exception as e:
        log.error(
            "send_contacts_by_bsuid_error",
            error=str(e),
            bsuid=bsuid,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, bsuid, channel, wamid=wamid, status="sent")


def send_flow_template(
    channel,
    msisdn,
    template_name,
    body_values,
    flow_token,
    flow_action_data=None,
    language_code="pt_BR",
    header_image_url=None,
):
    """Envia template com botão CTA do tipo Flow (uso típico: mensagem fria
    pra abrir um Flow de onboarding em quem ainda não está na janela 24h).

    Args:
        channel: phone_number_id da Meta (WAPP_NUMBER_ID)
        msisdn: telefone destinatário no formato internacional (ex: 5548...)
        template_name: nome do template aprovado na Meta (ex: "billing_setup_invitation")
        body_values: lista de strings p/ {{1}}, {{2}}, ... do body do template
        flow_token: identificador único da sessão — volta no nfm_reply pra correlação
        flow_action_data: dict opcional com dados iniciais passados ao Flow
            (acessíveis no JSON via ${data.<key>}). Ex: {"eta_name": "Schneider", "client_name": "João"}
        language_code: locale do template aprovado, default pt_BR

    Importante:
        - Template precisa estar APPROVED na Meta com botão tipo FLOW.
        - flow_action_data pode ser omitido se o Flow não declara `data` no WELCOME.
    """
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending flow template '{template_name}' to {msisdn}, token={flow_token}")

    # Meta recusa template parameter com texto vazio (#131008). Caller deve
    # garantir valores não-vazios; aqui fica fallback "—" pra evitar 400.
    body_params = [{"type": "text", "text": (str(v).strip() or "—")} for v in body_values]
    flow_action = {"flow_token": flow_token}
    if flow_action_data:
        flow_action["flow_action_data"] = flow_action_data

    components = []
    if header_image_url:
        components.append(
            {
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": header_image_url}}],
            }
        )
    components.append({"type": "body", "parameters": body_params})
    components.append(
        {
            "type": "button",
            "sub_type": "flow",
            "index": "0",
            "parameters": [{"type": "action", "action": flow_action}],
        }
    )

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msisdn,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()
        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid
    except Exception as e:
        log.error(
            "send_flow_template_error",
            error=str(e),
            phone=msisdn,
            template=template_name,
            flow_token=flow_token,
            response=getattr(getattr(e, "response", None), "text", ""),
        )
        return None
    finally:
        if data:
            MessageWpp(data, msisdn, channel, wamid=wamid, status="sent")
    return wamid


def send_template(channel, msisdn, template_id, values, messageid=None):
    WAPP_NUMBER_ID = channel
    META_API_KEY = config.APIS_AVAILABLE.get(channel, "")
    log.info(f"Sending template message to {msisdn}: {values}")
    values_payload = []
    for value in values:
        values_payload.append({"type": "text", "text": value})

    wamid = None
    data = None
    try:
        url = f"{config.META_BASE_URL}/{WAPP_NUMBER_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msisdn,
            "type": "template",
            "template": {
                "name": template_id,
                "language": {"code": "pt_BR"},
                "components": [{"type": "body", "parameters": values_payload}],
            },
        }
        HEADERS = {
            "Authorization": f"Bearer {META_API_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        response_json = response.json()

        if "messages" in response_json and len(response_json["messages"]) > 0:
            wamid = response_json["messages"][0].get("id")
            data["id"] = wamid

            if messageid:
                TemplateMessageIdRel(messageid, wamid)

    except Exception as e:
        log.error(
            "send_template_error",
            error=str(e),
            phone=msisdn,
            response=getattr(getattr(e, "response", None), "text", ""),
        )

    finally:
        if data:
            MessageWpp(data, msisdn, channel, wamid=wamid, status="sent")
