# kapso-spoky-bot

Spoky Bot de WhatsApp sobre **Kapso** (capa de transporte) + **AWS** (cerebro),
con inferencia **multiagente en LangGraph**.

## Flujo

Usuario WhatsApp -> Meta -> Kapso --webhook--> API Gateway -> Lambda receiver
-> SQS -> Lambda worker -> runtime de agentes (LangGraph) -> Bedrock
-> respuesta vía API REST de Kapso.

## Estructura

- `src/receiver/` Lambda que recibe el webhook: valida firma, idempotencia, encola y devuelve 200.
- `src/worker/` Lambda que consume SQS e invoca el grafo de agentes, y responde por Kapso.
- `src/agents/` Grafo LangGraph (supervisor + agentes + tools). Se empaqueta como contenedor.
- `src/shared/` Cliente Kapso, verificación HMAC, carga de config/secretos.
- `infra/` AWS SAM (API GW, Lambdas, SQS, DynamoDB, Secrets, IAM).
- `.github/` CI (lint+test) y CD (deploy con OIDC).

## Puesta en marcha (resumen)

1. `make install`
