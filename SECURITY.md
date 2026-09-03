# Security

## Reporting

Found a security issue in this SDK? Open a
[GitHub issue](https://github.com/AICAllenZhou/allens-h3-python/issues)
with the details. Do not include any API key or endpoint URL in the report.

## What this repository contains

This repository holds **only the client SDK**. The API server, its
configuration, model weights and deployment scripts are not published here.

## How the SDK handles credentials

- The API key and endpoint URL are read from `ALLENS_H3_API_KEY` and
  `ALLENS_H3_BASE_URL`. **Nothing is compiled into the package.**
- The key is sent in the `Authorization` header, never in a URL. The server
  rejects any request carrying a credential in a query string.
- The SDK never writes the key to disk or to a log.
- Exception messages are scrubbed of anything credential-shaped before they
  are raised, so a stack trace cannot leak a token.
- TLS certificate verification is always enabled. There is deliberately **no**
  parameter to disable it, and a unit test enforces that.
- `base_url` is validated: embedded credentials, query strings and plain
  `http://` to a remote host are all rejected.
- Generation requests are never retried automatically, so a network hiccup
  cannot silently bill you for two videos.
- The CLI refuses to accept a key as a command-line flag, which would leave it
  in shell history and in process listings.

## Handling your own key

- Treat it like a password. It is personal to you and independently revocable.
- Do not commit it, paste it into chat or an issue, or send it through any
  third-party tool.
- Use environment variables, or a `.env` file that is listed in `.gitignore`.
- If you think it has leaked, ask for a rotation — replacing one key does not
  affect any other user.
