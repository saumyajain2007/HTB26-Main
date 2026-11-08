# Vultr

Vultr plays two roles here. Neither is required; the app still runs on Vercel
(`deploy/vercel/`) or locally.

| Role | What | Where |
|---|---|---|
| Model jury juror | Vultr Serverless Inference, an OpenAI-compatible API | `HTB_JURY=providers`, model IDs prefixed `vultr:` |
| Host | A Cloud Compute VM running the API and workers | `setup.sh` |

## Vultr Inference as a juror

1. In the Vultr customer portal, create an inference subscription and copy its API key.
2. Set `VULTR_INFERENCE_API_KEY`, and put a `vultr:<model id>` in `JURY_MODELS`
   (see [.env.example](../../.env.example)). Pick the model ID from Vultr's model list.
3. Set `VULTR_INFERENCE_BASE_URL` only if Vultr gives you a different endpoint than
   `https://api.vultrinference.com/v1`.

Vultr replies go through the same checks as every other juror's, so a model that
does not return the review schema is marked invalid, not trusted. The request asks
for a JSON object rather than a strict JSON schema, because support for the latter
differs between the models Vultr serves. Not yet tried against the live service.

## A VM as the host

`setup.sh` installs `uv`, clones the repo to `/opt/htb`, installs a `htb` systemd
service that runs `deploy/serve.sh` (API, pipeline worker and, with
`HTB_DOCKING=vina`, the docking worker), and leaves you to fill in `.env`. Untested
end to end. Vina publishes Linux x86_64 wheels only, so use an x86_64 plan for docking.

For Postgres use Vultr Managed Databases for PostgreSQL or Tiger Data (see
[the README](../../README.md#sponsor-integrations)); both are plain `DATABASE_URL`s.
