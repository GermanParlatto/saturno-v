import boto3

bedrock = boto3.client("bedrock-runtime")

MODEL_ID = "eu.amazon.nova-2-lite-v1:0"
SYSTEM_PROMPT = "Eres un asistente de WhatsApp. Responde breve y claro, en español."


def pensar(texto: str) -> str:
    resp = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": texto}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={"maxTokens": 500},
    )
    return resp["output"]["message"]["content"][0]["text"]
