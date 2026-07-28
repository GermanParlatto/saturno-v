"""Logger y Tracer compartidos (AWS Lambda Powertools) para las dos Lambdas.

Centralizado aquí para que ambas emitan logs homogéneos bajo el mismo
`service`, y para que las trazas de X-Ray usen un único nombre de servicio.
"""

from aws_lambda_powertools import Logger, Metrics, Tracer

logger = Logger(service="kapso-bot")
tracer = Tracer(service="kapso-bot")
metrics = Metrics(namespace="kapso-bot", service="kapso-bot")
