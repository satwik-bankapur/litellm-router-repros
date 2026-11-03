# Results

## #40405: single deployment + fallback, 503 outage (LiteLLM 1.105.1)

| Variant | Router settings | Primary model_info | Attempts on the dead primary, request by request | Average per request | Median latency (s) | Max latency (s) | Served after outage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| default | none | none | 3 3 3 3 3 | 3.0 | 4.49 | 6.77 | primary, primary, primary |
| tuned | allowed_fails=1, cooldown_time=30 | none | 2 0 0 0 0 0 0 0 0 0 2 0 0 | 0.31 | 0.01 | 0.97 | backup, backup, backup |
| explicit_default | allowed_fails=3 | none | 3 3 3 3 3 3 | 3.0 | 4.69 | 5.24 | primary, primary, primary |
| deployment_level | none | allowed_fails=1, cooldown_time=30 | 3 3 3 3 3 3 | 3.0 | 4.6 | 5.22 | primary, primary, primary |
| deployment_policy | none | allowed_fails_policy={"ServiceUnavailableErrorAllowedFails": 1}, cooldown_time=30 | 2 0 0 0 0 0 0 0 0 0 2 0 0 | 0.31 | 0.02 | 0.94 | backup, backup, backup |

## When does a deployment cool down? (LiteLLM 1.105.1, defaults, num_retries=0)

| Check | Requests | Attempts that reached the failing deployment | Cooled down after first failure? |
| --- | --- | --- | --- |
| 429_single | 6 | 6 | no |
| 429_multi | 6 | 1 | yes |
| timeout_multi | 6 | 5 | no |
| 401_single | 6 | 1 | yes |

## #44815: param rejected before sending, fallback configured

| LiteLLM | Setting | Outcome | Served by | Calls to primary | Calls to backup |
| --- | --- | --- | --- | --- | --- |
| 1.105.1 | none (LiteLLM defaults) | 200 OK | backup | 0 | 1 |
| 1.105.1 | fallback_on_unsupported_params=False | setting not accepted by this version | - | - | - |
| 1.107.0.dev3 | none (LiteLLM defaults) | 200 OK | backup | 0 | 1 |
| 1.107.0.dev3 | fallback_on_unsupported_params=False | raised UnsupportedParamsError | - | 0 | 0 |

## Proxy demo (raw)

```text
### stable_default (LiteLLM 1.105.1, proxy/config.yaml)
HTTP/1.1 200 OK
x-litellm-model-api-base: http://127.0.0.1:9102/v1
x-litellm-model-group: backup
x-litellm-attempted-retries: 0
x-litellm-attempted-fallbacks: 1
body: {"id":"chatcmpl-c4efa5b94f6b","created":1793687204,"model":"fake-model","object":"chat.completion","choices":[{"finish_reason":"stop","index":0,"message":{"content":"answered by backup","role":"assistant","provider_specific_fields":{"refusa
calls to primary: 0
calls to backup:  1

### dev_fail_loudly (LiteLLM 1.107.0.dev3, proxy/config_fail_loudly.yaml)
HTTP/1.1 400 Bad Request
body: {"error":{"message":"litellm.UnsupportedParamsError: reasoning_effort=xhigh is not supported for this model.","type":"invalid_request_error","param":null,"code":"400"}}
calls to primary: 0
calls to backup:  0
```
