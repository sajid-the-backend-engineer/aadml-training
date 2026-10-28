"""The client against a stand-in AADML (httpx.MockTransport): nothing goes over the network."""
import io
import json

import httpx
import pytest

import aadml_training
from aadml_training import Client, errors
from aadml_training import client as client_module

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KEY = "tmd_app_secretkey123"
ANSWER = {"status": "ok", "walls": [{"id": 1, "corners": [[1, 1], [9, 1], [9, 9], [1, 9]]}], "openings": [],
          "request_id": "req_1", "capture_id": None, "model": {"name": "m", "version": 1}, "warnings": [],
          "timing_ms": {"model": 5, "total": 9}}


def make(handler, **kwargs):
    return Client(api_key=KEY, api_url="https://aadml.test", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                  **kwargs)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    return slept


def test_predict_sends_the_photo_with_the_key_to_the_project_environment():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["Authorization"], agent=request.headers["User-Agent"],
                    body=request.read())
        return httpx.Response(200, json=ANSWER)

    result = make(handler).predict(22, JPEG, environment="staging", request_id="r-7")
    assert result["walls"][0]["corners"][0] == [1, 1]
    assert seen["url"] == "https://aadml.test/api/training-data/v1/projects/22/environments/staging/predict/"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["agent"] == f"aadml-training-python/{aadml_training.__version__}"
    assert JPEG in seen["body"] and b'name="file"' in seen["body"]
    assert b'{"request_id": "r-7"}' in seen["body"]


def test_a_photo_can_be_a_path_an_open_file_or_bytes(tmp_path):
    names = []

    def handler(request):
        names.append(request.read().split(b'filename="')[1].split(b'"')[0])
        return httpx.Response(200, json=ANSWER)

    client = make(handler)
    path = tmp_path / "room.png"
    path.write_bytes(PNG)
    client.predict(1, str(path))
    client.predict(1, path)
    client.predict(1, io.BytesIO(JPEG))
    client.predict(1, bytearray(JPEG))
    assert names == [b"room.png", b"room.png", b"image.jpg", b"image.jpg"]


def test_a_photo_that_is_not_an_image_is_refused_before_anything_is_sent():
    def handler(request):
        raise AssertionError("nothing should be sent")

    client = make(handler)
    with pytest.raises(errors.BadRequestError) as refused:
        client.predict(1, b"%PDF-1.4 not a photo")
    assert refused.value.field == "image"
    with pytest.raises(errors.BadRequestError):
        client.predict(1, b"")
    with pytest.raises(errors.BadRequestError):
        client.predict(1, "no/such/file.jpg")


def test_errors_carry_aadmls_message_and_field():
    def handler(request):
        return httpx.Response(400, json={"error": "payload is not valid JSON.", "field": "payload"})

    with pytest.raises(errors.BadRequestError) as refused:
        make(handler).predict(1, JPEG)
    assert (refused.value.status_code, refused.value.message, refused.value.field) == (400, "payload is not valid JSON.",
                                                                                         "payload")


@pytest.mark.parametrize("status, kind", [(401, errors.AuthenticationError), (403, errors.PermissionDeniedError),
                                          (404, errors.NotFoundError), (413, errors.PayloadTooLargeError),
                                          (502, errors.ServerError), (418, errors.APIError)])
def test_each_status_has_its_error(status, kind):
    with pytest.raises(kind):
        make(lambda request: httpx.Response(status, json={"error": "no"})).predict(1, JPEG)


def test_a_request_aadml_did_not_process_is_sent_again_as_it_asks(no_sleep):
    answers = iter([httpx.Response(429, json={"error": "Too many requests."}, headers={"Retry-After": "3"}),
                    httpx.Response(503, json={"error": "starting"}, headers={"Retry-After": "120"}),
                    httpx.Response(200, json=ANSWER)])
    assert make(lambda request: next(answers)).predict(1, JPEG)["status"] == "ok"
    assert no_sleep == [3.0, 30.0]                                   # AADML's wait, never more than 30 seconds


def test_a_request_that_may_have_been_processed_is_never_sent_twice():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502, json={"error": "The model did not answer."})

    with pytest.raises(errors.ServerError):
        make(handler).predict(1, JPEG)
    assert len(calls) == 1                                          # it may have been charged: not sent again


def test_retries_end_with_the_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "No model is deployed to production for this project yet."},
                              headers={"Retry-After": "5"})

    with pytest.raises(errors.ModelUnavailableError) as refused:
        make(handler, max_retries=1).predict(1, JPEG)
    assert (len(calls), refused.value.retry_after) == (2, 5.0)


def test_unreachable_aadml_is_a_connection_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(errors.ConnectionError):
        make(handler, max_retries=1).predict(1, JPEG)


def test_chat_uses_the_openai_format_and_chat_text_returns_the_reply():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.read()))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Use the Returns page."}}]})

    client = make(handler)
    messages = [{"role": "user", "content": "How do I return an order?"}]
    assert client.chat_text(31, messages, max_tokens=50) == "Use the Returns page."
    assert seen["url"] == "https://aadml.test/api/training-data/v1/projects/31/environments/production/v1/chat/completions"
    assert seen["body"] == {"messages": messages, "max_tokens": 50, "stream": False}


def test_chat_stream_yields_the_reply_as_it_is_written():
    events = ('data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
              'data: {"choices":[{"delta":{"content":"Use the "}}]}\n\n'
              ': keep-alive\n\n'
              'data: {"choices":[{"delta":{"content":"Returns page."}}]}\n\n'
              'data: [DONE]\n\n')
    client = make(lambda request: httpx.Response(200, text=events, headers={"Content-Type": "text/event-stream"}))
    assert "".join(client.chat_stream(31, [{"role": "user", "content": "?"}])) == "Use the Returns page."


def test_chat_stream_error_answer_raises():
    client = make(lambda request: httpx.Response(401, json={"error": {"message": "Unknown key", "type": "auth"}}))
    with pytest.raises(errors.AuthenticationError) as refused:
        list(client.chat_stream(31, [{"role": "user", "content": "?"}]))
    assert refused.value.message == "Unknown key"


def test_models_lists_the_environments_chat_models():
    client = make(lambda request: httpx.Response(200, json={"object": "list", "data": [{"id": "chat-v2"}]}))
    assert client.models(31) == [{"id": "chat-v2"}]


def test_the_key_comes_from_the_environment_and_is_never_shown(monkeypatch):
    monkeypatch.setenv("AADML_API_KEY", KEY)
    client = Client()
    assert KEY not in repr(client) and client.api_url == "https://aadml.com"
    monkeypatch.delenv("AADML_API_KEY")
    with pytest.raises(errors.ConfigurationError):
        Client()


def test_bad_settings_are_refused():
    with pytest.raises(errors.ConfigurationError):
        Client(api_key=KEY, api_url="ftp://aadml.com")
    client = make(lambda request: httpx.Response(200, json=ANSWER))
    with pytest.raises(errors.ConfigurationError):
        client.predict(1, JPEG, environment="prod")
    with pytest.raises(errors.ConfigurationError):
        client.predict("../2", JPEG)


def test_run_sends_a_photo_to_a_ready_to_use_model_by_its_key():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["Authorization"])
        return httpx.Response(200, json=ANSWER)

    assert make(handler).run("segformer-b0", JPEG)["status"] == "ok"
    assert seen == {"url": "https://aadml.test/api/training-data/v1/models/segformer-b0/predict", "auth": f"Bearer {KEY}"}
    with pytest.raises(errors.ConfigurationError):
        make(handler).run("../projects", JPEG)


def test_a_model_closed_until_charging_is_said_once_not_retried(no_sleep):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "Calls open when per-call charging is connected.", "field": None})

    with pytest.raises(errors.ModelUnavailableError) as refused:
        make(handler).run("segformer-b0", JPEG)
    assert (len(calls), no_sleep, refused.value.retry_after) == (1, [], None)
    assert "charging" in refused.value.message
