# whatsapp-client

Cliente WhatsApp Business (Graph API da Meta) — **transport puro**, extraído do
`backend_whatsapp_z1monitoramento`. Só envia/recebe pela Graph API; não conhece
idioma, regras de parceiro nem roteamento de negócio (isso fica no app).

## Instalação

Via pip + SSH do GitHub (mesmo padrão de `z1monitoring-models`):

```bash
pip install --no-deps "whatsapp-client @ git+ssh://git@github.com/raniereee/whatsapp_client_lib.git@main"
```

`--no-deps` porque `requests`/`structlog` já vêm do app e a **peer dependency**
`z1monitoring-models` é instalada separadamente (a lib usa `MessageWpp` e
`TemplateMessageIdRel` para persistir/correlacionar mensagens).

## Uso

A lib não lê env vars. O app injeta a config **uma vez** no bootstrap (ex.: no
boot do worker Celery), antes do primeiro envio:

```python
import whatsapp_client
from monitoring.config import APIS_AVAILABLE, META_BASE_URL

whatsapp_client.configure(apis_available=APIS_AVAILABLE, meta_base_url=META_BASE_URL)
```

Depois, importe `official` e use normalmente:

```python
from whatsapp_client import official as whatsapp_official

whatsapp_official.send_text_message(phone_number, channel, message)
whatsapp_official.send_buttons(channel, phone_number, message, buttons)
```

As funções referenciam a config em runtime, então `configure()` pode rodar
depois do import sem problema.

## API

`official` expõe: `send_text_message`, `send_buttons`, `send_list`, `send_image`,
`send_image_upload`, `send_audio`, `send_document`, `send_contacts`,
`send_template`, `send_flow_template`, `send_location`, `location_request`,
`send_typing_indicator`, `mark_message_read`, `retrieve_media`, `media_download`,
`decode_msg`.

## Config injetável

- `META_BASE_URL` — base da Graph API (ex.: `https://graph.facebook.com/v21.0`).
- `APIS_AVAILABLE` — `dict` `phone_number_id (channel) -> token` por parceiro.

> Persistência (`MessageWpp`/`TemplateMessageIdRel`) ainda acopla a lib ao schema
> Z1. Evolução futura: hook de persistência injetável para tornar a lib agnóstica
> de banco.
