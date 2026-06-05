"""Cliente WhatsApp Business (Graph API da Meta).

Uso:

    import whatsapp_client
    whatsapp_client.configure(apis_available=APIS_AVAILABLE, meta_base_url=META_BASE_URL)

    from whatsapp_client import official as whatsapp_official
    whatsapp_official.send_text_message(phone, channel, message)

``official`` NÃO é importado aqui de propósito — ele depende de
``z1monitoring_models`` (banco), então um simples ``import whatsapp_client`` para
chamar ``configure`` não deve forçar esse carregamento. Importe ``official``
explicitamente quando for enviar.
"""

from whatsapp_client.config import configure

__all__ = ["configure"]
