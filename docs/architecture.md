# Architecture and reliability contract

## Delivery lifecycle

1. A provider sends to a stable Webhook Relay input.
2. Webhook Relay stores a delivery record and streams it to the authenticated local
   relay process. If the process is offline, the event remains visible and replayable.
3. The plugin verifies the original body and headers with the route's provider secret.
4. The ledger atomically admits the provider event ID. Completed duplicates return
   `200` without starting another run.
5. A concurrency slot is acquired and Hermes receives a prompt with the payload
   fenced as untrusted data.
6. The plugin waits for Hermes's processing-complete callback.
7. Success returns `200`; failure returns `500`. The relay process retries `5xx`
   responses and reports delivery status to Webhook Relay.

If a run exceeds `run_timeout_seconds`, the adapter returns `202` because the run is
still active and retrying could duplicate side effects. Its eventual completion is
recorded in the ledger; a late failure needs operator review and replay.

## Crash behavior

If the gateway dies before responding, the local HTTP connection fails and the relay
process reports a failed attempt. A ledger row can remain `running`; after 1.5 times
the configured run timeout it is considered stale and may be admitted again. This
provides at-least-once recovery. If the agent completed a side effect immediately
before the crash, that action can happen twice, so route actions still need their own
idempotency keys.

## Backpressure

At capacity the adapter returns `503 Retry-After`, without creating a ledger row.
The sender can therefore retry without being mistaken for a duplicate. Webhook Relay
then redelivers instead of allowing a burst to start unlimited agent runs.

## Current limitations

- One supervised `relay forward` process is started per distinct configured bucket.
- Provider verifiers currently cover generic/GitHub HMAC-SHA256, Stripe, Shopify,
  Slack, and GitLab. More schemes should be added with official test vectors.
- The CLI reset command does not initiate a remote replay; the operator replays the
  delivery from Webhook Relay after clearing the local guard.
- Text and non-JSON bodies are represented as `{ "raw": "..." }` in the prompt.
- The body-hash event ID fallback treats byte-identical events on the same route as
  duplicates. Configure `id_path` for sources where identical bodies are separate work.
- The plugin depends on Hermes's current external platform and completion-hook APIs;
  CI tests the local contract, and an upstream compatibility job should be added before
  the first stable release.
