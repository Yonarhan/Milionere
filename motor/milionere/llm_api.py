"""Camada de LLM pela API direta da Anthropic (MILIONERE_LLM=api): sem o overhead do Claude Code CLI.

Mesma interface do llm.chamar: prompt + JSON schema -> dict validado. Usa saída estruturada
(output_config.format), cache de prompt automático e registra tokens e custo no medidor.
Credencial: ANTHROPIC_API_KEY no ambiente ou no .env da raiz (nunca no git).
"""

import base64
import copy
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import medidor  # noqa: E402

MODELOS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}
# US$ por milhão de tokens (entrada, saída). Cache: leitura ~0,1x e escrita ~1,25x da entrada.
PRECOS = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5": (2.0, 10.0), "claude-opus-5": (5.0, 25.0),
          "claude-sonnet-4-6": (3.0, 15.0)}
SEM_ESFORCO = {"claude-haiku-4-5"}  # Haiku 4.5 não aceita output_config.effort
# palavras-chave de JSON Schema que a saída estruturada não aceita: a validação delas fica no nosso código
NAO_SUPORTADO = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "maxItems", "multipleOf"}

_cliente = None


class ErroAPI(RuntimeError):
    pass


def _cli():
    global _cliente
    if _cliente is None:
        import anthropic
        _cliente = anthropic.Anthropic()
    return _cliente


def _limpar_schema(s):
    """Remove restrições não suportadas; minItems só pode ser 0 ou 1."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k in NAO_SUPORTADO or (k == "minItems" and isinstance(v, int) and v > 1):
                continue
            out[k] = _limpar_schema(v)
        return out
    if isinstance(s, list):
        return [_limpar_schema(x) for x in s]
    return s


def modelo_id(nome: str | None) -> str:
    nome = (nome or "sonnet").strip()
    return MODELOS.get(nome, nome)


def custo_usd(modelo: str, uso) -> float:
    ent, sai = PRECOS.get(modelo, (3.0, 15.0))
    base = getattr(uso, "input_tokens", 0) or 0
    lido = getattr(uso, "cache_read_input_tokens", 0) or 0
    escrito = getattr(uso, "cache_creation_input_tokens", 0) or 0
    return (base * ent + lido * ent * 0.1 + escrito * ent * 1.25 + (getattr(uso, "output_tokens", 0) or 0) * sai) / 1e6


def _imagens(prompt: str, pasta: Path | None) -> list[dict]:
    """O juiz visual cita arquivos pelo caminho: aqui eles viram blocos de imagem de verdade."""
    if not pasta:
        return []
    blocos = []
    for caminho in dict.fromkeys(re.findall(r"[A-Za-z]:[\\/][^\s]+?\.(?:jpg|jpeg|png|webp)|/[^\s]+?\.(?:jpg|jpeg|png|webp)", prompt)):
        p = Path(caminho)
        if p.exists():
            mime = {"png": "image/png", "webp": "image/webp"}.get(p.suffix.lower().lstrip("."), "image/jpeg")
            blocos += [{"type": "text", "text": f"Arquivo {p.name}:"},
                       {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(p.read_bytes()).decode()}}]
    return blocos


def chamar(prompt: str, schema: dict, ler_arquivos_em: Path | None = None, modelo: str | None = None,
           papel: str = "roteirista", esforco: str | None = None) -> dict:
    mid = modelo_id(modelo or (caminhos.MODELO_JUIZ if papel == "juiz" else caminhos.MODELO_ROTEIRO))
    esforco = esforco or (caminhos.ESFORCO_JUIZ if papel == "juiz" else caminhos.ESFORCO_ROTEIRO)
    conteudo = _imagens(prompt, ler_arquivos_em) + [{"type": "text", "text": prompt}]
    pedido = {"model": mid, "max_tokens": 16000, "cache_control": {"type": "ephemeral"},
              "messages": [{"role": "user", "content": conteudo}],
              "output_config": {"format": {"type": "json_schema", "schema": _limpar_schema(copy.deepcopy(schema))}}}
    if mid not in SEM_ESFORCO and esforco:
        pedido["output_config"]["effort"] = esforco
    inicio = time.time()
    resp = _cli().messages.create(**pedido)
    medidor.anotar_llm(mid, resp.usage, custo_usd(mid, resp.usage), time.time() - inicio)
    if resp.stop_reason == "refusal":
        raise ErroAPI(f"{mid} recusou o pedido")
    if resp.stop_reason == "max_tokens":
        raise ErroAPI(f"{mid} parou no limite de tokens")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(texto)
