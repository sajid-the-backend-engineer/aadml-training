# Changelog

## 0.3.0

- `EdgeModel(url)` (and `Client.edge(url)`): a model AADML runs on one of your own machines, called on your
  network with no key: `predict(image)` and `ping()`.
- `dedicated(name, image)`: a photo to a Dedicated Deployment of your workspace, named as you named it. One still
  starting is sent again when AADML says when.

## 0.2.0

- `run(model, image)`: a photo to one of AADML's ready-to-use models, named by its key.
- A 503 is sent again only when AADML says when to try again (a model that is starting); a model closed until
  charging is connected is reported at once.

## 0.1.0

- `Client`: AADML's address and your app key (`AADML_API_KEY`, `AADML_API_URL`), timeouts and retries that never send
  a request twice when it may have been processed.
- Photo models: `predict` (a file path, bytes, an open file, a URL or a Pillow image).
- Chat models: `chat`, `chat_text`, `chat_stream`, `models`, in OpenAI's chat completions format.
- One error kind per answer: `AuthenticationError`, `PermissionDeniedError`, `BadRequestError`,
  `PayloadTooLargeError`, `RateLimitError`, `ModelUnavailableError`, `ServerError`, `ConnectionError`.
