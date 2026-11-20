# Provider fixtures

Response shapes for the mock provider and for adapter contract tests (PRD v1.4 Section 2.7). They follow the OpenAI-compatible chat completion shape and were written by hand from its public description. None was recorded from a real provider, and no real credential was used.

| File | Used for |
|---|---|
| `chat_completion.json` | A successful answer with a usage block. The mock provider server uses it as its template. |
| `chat_completion_no_usage.json` | An answer with no usage block: the gateway must settle at the reserved amount. |
| `error_500.json` | A provider failure: the gateway must release the reservation. |

Vendors and models are fictional (`vendor-a`, `vendor-a/model-1`).
