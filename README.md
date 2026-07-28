# kapso-spoky-bot

Spoky Bot de WhatsApp sobre **Kapso** (capa de transporte) + **AWS** (cerebro),
con inferencia **multiagente en LangGraph**.

## Flujo

Usuario WhatsApp -> Meta -> Kapso --webhook--> API Gateway -> Lambda receiver
-> SQS -> Lambda worker -> LangGraph (Bedrock: tutor de Python) -> endpoint de
Spoky (voz del personaje) -> respuesta vía API REST de Kapso.

## Estructura

- `src/receiver/` Lambda que recibe el webhook: valida firma, idempotencia, encola y devuelve 200.
- `src/worker/` Lambda que consume SQS e invoca el grafo de agentes, y responde por Kapso.
- `src/agents/` Grafo LangGraph (nodo `llm` tutor + nodo `finalizer` con la voz de Spoky). Incluye `prompts.py` con el system prompt del personaje.
- `src/shared/` Cliente Kapso, cliente del endpoint de Spoky, verificación HMAC, carga de config/secretos.
- `infra/` AWS SAM (API GW, Lambdas, SQS, DynamoDB, Secrets, IAM).
- `.github/` CI (lint+test) y CD (deploy con OIDC).

## Configuración

Ver [docs/08-Configuracion.md](docs/08-Configuracion.md) para la tabla completa de variables de entorno, el checklist al añadir un secreto nuevo y el presupuesto de timeout del finalizador de Spoky.

## Puesta en marcha (resumen)

1. `make install`
