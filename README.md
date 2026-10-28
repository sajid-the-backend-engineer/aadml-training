# aadml-training

The Python SDK for [AADML](https://aadml.com) Training: call the photo and chat models you trained and deployed in
AADML from your own code.

```bash
pip install aadml-training
```

Python 3.9 or newer. One dependency: [httpx](https://www.python-httpx.org/).

## Your key

Make an app key on your project's **Deploy** page (Connected apps), and allow it the environment you will call
(staging or production). Keep it secret: anyone with the key can call your model, and calls may be charged.

```bash
export AADML_API_KEY="your app key"
```

## Photo models

```python
from aadml_training import Client

client = Client()                                    # reads AADML_API_KEY; or Client(api_key="...")

result = client.predict(project_id=22, image="room.jpg")          # production by default
for wall in result["walls"]:
    print(wall["id"], wall["corners"])
for opening in result["openings"]:
    print(opening["type"], opening["polygon"])       # windows and doors
```

`image` can be a file path, bytes, an open binary file, a URL or a Pillow image: JPEG, PNG or WebP, at most 15 MB.
Coordinates are in the photo's own pixels. Pass `environment="staging"` to call the staging model, and your own
`request_id` / `capture_id` to find a call again later.

## AADML's ready-to-use models

Models AADML runs for you, listed on the Models page ("Ready-to-use models"); you train nothing. Name the model by its
key, shown in its "Use model" dialog:

```python
result = client.run("segformer-b0", "room.jpg")
```

Calls to ready-to-use models open when AADML's per-call charging is connected. Until then AADML answers 503, and
`run` raises `ModelUnavailableError` with the reason.

## Chat models

A chat model's project answers in OpenAI's chat completions format.

```python
messages = [{"role": "user", "content": "How do I return an order?"}]

print(client.chat_text(project_id=31, messages=messages))

for piece in client.chat_stream(project_id=31, messages=messages):     # as the model writes it
    print(piece, end="", flush=True)

answer = client.chat(project_id=31, messages=messages, max_tokens=200)  # the whole completion
print(client.models(project_id=31))                                      # the models it answers with
```

## Errors

Every error is an `aadml_training.AADMLError`. An error answer from AADML is an `APIError` with `status_code`,
`message` and, when AADML names one, `field`:

| Error | When |
|---|---|
| `AuthenticationError` (401) | The key is missing, unknown or revoked |
| `PermissionDeniedError` (403) | The key has no access to that project and environment |
| `BadRequestError` (400) | The request was refused, for example a file that is not a photo |
| `PayloadTooLargeError` (413) | The photo is larger than 15 MB |
| `RateLimitError` (429) | Too many requests for this key; `retry_after` says how long to wait |
| `ModelUnavailableError` (503) | No model is deployed to that environment yet, or it is starting |
| `ServerError` (5xx) | AADML or the model failed to answer |
| `ConnectionError` | AADML could not be reached |

```python
from aadml_training import ModelUnavailableError

try:
    result = client.predict(project_id=22, image="room.jpg")
except ModelUnavailableError as error:
    print("Not ready yet:", error.message, "try again in", error.retry_after, "seconds")
```

## Retries

A request AADML refused **without processing it** (429, 503) or that never reached AADML is sent again, waiting as
AADML asks (at most 30 seconds), up to `max_retries` times (2 by default). A request that may have been processed is
never sent twice, so you are never charged twice for one call.

```python
client = Client(timeout=30, max_retries=0)
```

## Settings

| Setting | Argument | Environment variable | Default |
|---|---|---|---|
| API key | `api_key` | `AADML_API_KEY` | none: required |
| AADML's address | `api_url` | `AADML_API_URL` | `https://aadml.com` |
| Seconds to wait for an answer | `timeout` | | 60 |
| Times a request is sent again | `max_retries` | | 2 |

## About this package

`aadml-training` covers AADML Training. It will become part of the general `aadml` SDK; this package will then point
to it.

Licence: Apache 2.0. Report a security problem privately (see [SECURITY.md](SECURITY.md)).
