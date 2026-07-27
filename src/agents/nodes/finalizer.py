"""Nodo Finalizador: sintetiza la respuesta final para el usuario -> END."""


# TODO: cuando este nodo llame al endpoint de Hugging Face por httpx (no
# LangChain, así que LangSmith no lo traza automáticamente), decorar la
# función de la llamada con @traceable de langsmith, p.ej.:
#
#   from langsmith import traceable
#
#   @traceable(run_type="llm", name="finalizer-hf-endpoint")
#   def _call_hf_endpoint(prompt: str) -> str:
#       ...
def finalizer(state):
    # TODO: componer la respuesta final a partir de state y devolverla
    raise NotImplementedError("Implementar finalizador")
