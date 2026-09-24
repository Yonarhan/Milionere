"""Medidor de custo e uso: cada chamada de IA, cada imagem e cada etapa do pipeline anotam aqui.

    with medidor.medir() as m:          # abre a medição de um job (uma por thread/contexto)
        with medidor.etapa("roteiro"):  # rótulo das chamadas feitas dentro
            ...llm.chamar(...)           # llm.py registra tokens e custo sozinho
        m.resumo()                       # -> totais por etapa, em US$ e R$

Custo das chamadas do Claude: o `total_cost_usd` que o próprio Claude CLI devolve (valor equivalente de API,
mesmo quando roda pela assinatura). Imagens: tabela de preços oficiais abaixo (atualizar quando mudar).
"""

import contextlib
import contextvars
import os
import time

DOLAR = float(os.environ.get("MILIONERE_DOLAR", "5.5"))
PRECO_IMAGEM_USD = {  # por imagem 1K (ai.google.dev/gemini-api/docs/pricing, 09/2026)
    "gemini-3.1-flash-image": 0.067, "gemini-3.1-flash-lite-image": 0.0336, "gemini-2.5-flash-image": 0.039,
    "gemini-3-pro-image": 0.134, "cloudflare-flux2-klein": 0.0,  # dentro da cota grátis diária
    "comfy": 0.0, "banco": 0.0, "pexels": 0.0, "upload": 0.0,
}

_medicao: contextvars.ContextVar = contextvars.ContextVar("medicao", default=None)
_etapa: contextvars.ContextVar = contextvars.ContextVar("etapa", default="")


class Medicao:
    def __init__(self):
        self.itens: list[dict] = []
        self.inicio = time.time()

    def resumo(self) -> dict:
        por_etapa: dict[str, dict] = {}
        for i in self.itens:
            e = por_etapa.setdefault(i["etapa"] or "geral", {"chamadas": 0, "imagens": 0, "tokens_entrada": 0,
                                                              "tokens_saida": 0, "usd": 0.0, "segundos": 0.0})
            e["chamadas"] += i["tipo"] == "llm"
            e["imagens"] += i["tipo"] == "imagem"
            e["tokens_entrada"] += i.get("entrada", 0)
            e["tokens_saida"] += i.get("saida", 0)
            e["usd"] += i.get("usd", 0.0)
            e["segundos"] += i.get("segundos", 0.0)
        usd = sum(e["usd"] for e in por_etapa.values())
        return {"usd": round(usd, 4), "brl": round(usd * DOLAR, 2), "segundos": round(time.time() - self.inicio, 1),
                "por_etapa": {k: {**v, "usd": round(v["usd"], 4), "brl": round(v["usd"] * DOLAR, 2),
                                  "segundos": round(v["segundos"], 1)} for k, v in por_etapa.items()},
                "modelos": sorted({i["modelo"] for i in self.itens if i.get("modelo")})}


@contextlib.contextmanager
def medir():
    m = Medicao()
    tok = _medicao.set(m)
    try:
        yield m
    finally:
        _medicao.reset(tok)


@contextlib.contextmanager
def etapa(nome: str):
    tok = _etapa.set(nome)
    try:
        yield
    finally:
        _etapa.reset(tok)


def etapa_atual() -> str:
    return _etapa.get()


def _anotar(item: dict) -> None:
    m = _medicao.get()
    if m is not None:
        m.itens.append({"etapa": _etapa.get(), **item})


def llm(saida_cli: dict, segundos: float) -> None:
    """Recebe o JSON do `claude -p --output-format json` e anota tokens, modelo e custo."""
    u = saida_cli.get("usage") or {}
    modelos = list((saida_cli.get("modelUsage") or {}).keys())
    _anotar({"tipo": "llm", "modelo": ",".join(modelos),
             "entrada": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
             "saida": u.get("output_tokens", 0), "usd": float(saida_cli.get("total_cost_usd") or 0.0), "segundos": segundos})


def imagem(provedor: str, segundos: float = 0.0, quantidade: int = 1) -> None:
    _anotar({"tipo": "imagem", "modelo": provedor, "usd": PRECO_IMAGEM_USD.get(provedor, 0.0) * quantidade,
             "segundos": segundos})


def anotar_llm(modelo: str, uso, usd: float, segundos: float) -> None:
    """Chamada pela API direta (llm_api.py): o custo vem calculado dos tokens reais."""
    _anotar({"tipo": "llm", "modelo": modelo,
             "entrada": (getattr(uso, "input_tokens", 0) or 0) + (getattr(uso, "cache_read_input_tokens", 0) or 0)
                        + (getattr(uso, "cache_creation_input_tokens", 0) or 0),
             "saida": getattr(uso, "output_tokens", 0) or 0, "usd": usd, "segundos": segundos})
