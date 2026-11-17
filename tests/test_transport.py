"""transport: devolve o que a Meta respondeu e não toca banco."""

from unittest.mock import MagicMock, patch

import requests

import whatsapp_client
from whatsapp_client import transport

whatsapp_client.configure(apis_available={"PN": "TOKEN"}, meta_base_url="https://graph.test/v23.0")


def _resposta(status, corpo):
    r = MagicMock()
    r.ok = status < 400
    r.status_code = status
    r.json.return_value = corpo
    r.text = str(corpo)
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


def test_envio_aceito_devolve_wamid_e_wa_id():
    resp = _resposta(200, {"contacts": [{"input": "5549999990000", "wa_id": "554999990000"}], "messages": [{"id": "wamid.1"}]})
    with patch("whatsapp_client.transport.meta_http.post", return_value=resp) as post:
        r = transport.send_payload("PN", {"to": "5549999990000", "type": "text", "text": {"body": "oi"}})
    assert (r.ok, r.wamid, r.wa_id) == (True, "wamid.1", "554999990000")
    url = post.call_args.args[0]
    assert url == "https://graph.test/v23.0/PN/messages"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer TOKEN"}
    assert post.call_args.kwargs["json"]["messaging_product"] == "whatsapp"


def test_envio_recusado_devolve_codigo_e_detalhe():
    resp = _resposta(400, {"error": {"code": 131047, "message": "Re-engagement", "error_data": {"details": "mais de 24h"}}})
    with patch("whatsapp_client.transport.meta_http.post", return_value=resp):
        r = transport.send_payload("PN", {"to": "x", "type": "text", "text": {"body": "oi"}})
    assert not r.ok
    assert (r.error_code, r.error_detail) == (transport.OUTSIDE_WINDOW, "mais de 24h")


def test_envio_sem_resposta_nao_explode():
    with patch("whatsapp_client.transport.meta_http.post", side_effect=requests.ConnectTimeout()):
        r = transport.send_payload("PN", {"to": "x", "type": "text", "text": {"body": "oi"}})
    assert not r.ok and r.error_detail


def test_download_em_dois_passos():
    meta = _resposta(200, {"url": "https://cdn/x", "mime_type": "application/pdf"})
    arquivo = _resposta(200, {})
    arquivo.content = b"%PDF"
    with patch("whatsapp_client.transport.meta_http.get", side_effect=[meta, arquivo]) as get:
        m = transport.download_media("PN", "MID")
    assert m == transport.Media(b"%PDF", "application/pdf")
    assert get.call_args_list[0].args[0] == "https://graph.test/v23.0/MID?phone_number_id=PN"


def test_upload_devolve_media_id():
    with patch("whatsapp_client.transport.meta_http.post_idempotente", return_value=_resposta(200, {"id": "M1"})) as post:
        assert transport.upload_media("PN", b"x", "image/png", "a.png") == "M1"
    assert post.call_args.kwargs["files"]["file"] == ("a.png", b"x", "image/png")


def test_template_pelo_nome_exato_e_idioma_paginando():
    pagina1 = _resposta(200, {"data": [{"name": "cobranca_v2", "language": "pt_BR"}], "paging": {"next": "https://graph.test/next"}})
    pagina2 = _resposta(200, {"data": [{"name": "cobranca", "language": "en"}, {"name": "cobranca", "language": "pt_BR", "status": "APPROVED"}]})
    with patch("whatsapp_client.transport.meta_http.get", side_effect=[pagina1, pagina2]):
        t = transport.get_template("PN", "WABA", "cobranca", "pt_BR")
    assert t["status"] == "APPROVED"


def test_listar_templates_falha_devolve_none():
    with patch("whatsapp_client.transport.meta_http.get", return_value=_resposta(500, {})):
        assert transport.list_templates("PN", "WABA") is None
