# OpenCode gateway in Docker

The OpenAI-compatible gateway is included in the SAFi image and can be started
as an optional Compose service. It is not enabled by the normal `docker compose
up` command.

## Start the gateway

Create its private environment file with the API key for the policy that should
govern OpenCode requests:

```bash
cp gateways/opencode-gateway.env.example gateways/opencode-gateway.env
chmod 600 gateways/opencode-gateway.env
```

Set `SAFI_POLICY_API_KEY` in `gateways/opencode-gateway.env`, then start the
service:

```bash
docker compose --profile opencode up -d opencode-gateway
```

The gateway calls SAFi over the private Compose network at
`http://app:5000/api/harness/process_prompt`. OpenCode on the same host connects
to `http://127.0.0.1:5002/v1`. The published port is loopback-only by default;
set `OPENCODE_GATEWAY_PORT` if port 5002 is already in use and use that same port
in OpenCode's `baseURL`. If the host systemd
gateway is already using 5002, stop that service or select another Compose host
port before starting the container gateway.

For OpenCode on another machine, put a TLS reverse proxy in front of the
gateway and use that HTTPS URL as `baseURL`. Do not expose the gateway's plain
HTTP port directly to an untrusted network.

## Configure OpenCode

Add the provider to the project's `opencode.json` or your user-level OpenCode
configuration. Use the same policy API key in OpenCode's environment; do not put
it in a shared or committed configuration file.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "safi/coding_harness",
  "provider": {
    "safi": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "SAFi (governed)",
      "options": {
        "baseURL": "http://127.0.0.1:5002/v1",
        "apiKey": "{env:SAFI_POLICY_API_KEY}"
      },
      "models": {
        "coding_harness": {
          "name": "SAFi Coding Harness",
          "tool_call": true,
          "reasoning": true,
          "interleaved": "reasoning_content"
        },
        "safi": {
          "name": "SAFi",
          "tool_call": true,
          "reasoning": true,
          "interleaved": "reasoning_content"
        }
      }
    }
  }
}
```

Set `SAFI_POLICY_API_KEY` in the environment used to launch OpenCode, then
restart OpenCode after changing its configuration. `coding_harness` selects the
software-engineering profile; `safi` selects the general SAFi persona. Tool
calls execute in OpenCode and are checked by SAFi before the gateway returns
them for execution.

The Docker gateway can target another SAFi deployment by changing its
`SAFI_OPENAI_API_URL` and `SAFI_OPENAI_PROGRESS_URL` service environment to that
deployment's harness and progress endpoints. OpenCode's `baseURL` still points
to the gateway, and its key must match the policy key configured for that
gateway.
