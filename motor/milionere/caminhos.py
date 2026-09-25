"""Caminhos e configuração do pipeline, num lugar só.

Tudo pode ser trocado por variável de ambiente ou por um arquivo `.env` na raiz do repositório
(formato CHAVE=valor, uma por linha). Assim o mesmo código roda no Windows, no Linux/WSL, no
worker do Celery e no servidor, sem caminho fixo no código.

Camadas trocáveis (valores aceitos):
    MILIONERE_VOZ     edge (padrão, MVP) | azure (mesma voz, oficial: pedir antes de cobrar)
    MILIONERE_LLM     claude-cli (padrão, dev) | api (API direta da Anthropic; ANTHROPIC_API_KEY no .env)
    MILIONERE_IMAGEM  auto (padrão: manual > comfy) | comfy | gemini | manual
    MILIONERE_PLANO   gratis (padrão) | pago | chave_propria   (pago/chave_propria => gemini com reserva no comfy)
    MILIONERE_MODELO_ROTEIRO / MILIONERE_MODELO_JUIZ   modelo do Claude de cada papel (padrão: sonnet / haiku)
"""

import os
import sys
from pathlib import Path

PACOTE = Path(__file__).resolve().parent            # motor/milionere
DADOS = PACOTE / "dados"                            # presets, formatos, estilos, bíblia, referências
MOTOR_PADRAO = PACOTE.parent                        # motor/
RAIZ_PADRAO = MOTOR_PADRAO.parent                   # raiz do repositório


def _ler_env(arq: Path) -> None:
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_ler_env(RAIZ_PADRAO / ".env")


def _cfg(nome: str, padrao: str) -> str:
    return os.environ.get(nome, padrao)


RAIZ = Path(_cfg("MILIONERE_RAIZ", str(RAIZ_PADRAO)))
MOTOR = Path(_cfg("MILIONERE_MOTOR", str(MOTOR_PADRAO)))
PRODUCAO = Path(_cfg("MILIONERE_PRODUCAO", str(RAIZ / "producao")))
SAIDA = Path(_cfg("MILIONERE_SAIDA", str(RAIZ / "videos_prontos")))
CONFIG_MOTOR = MOTOR / "config.toml"                # chaves de API (fora do git)
COMFY = Path(_cfg("MILIONERE_COMFY", str(Path.home() / "projects" / "milionere" / "ComfyUI")))
_VENV = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv-linux/bin/python"
PYTHON_MOTOR = Path(_cfg("MILIONERE_PYTHON", str(MOTOR / _VENV)))

VOZ = _cfg("MILIONERE_VOZ", "edge")
LLM = _cfg("MILIONERE_LLM", "claude-cli")
IMAGEM = _cfg("MILIONERE_IMAGEM", "auto")
PLANO = _cfg("MILIONERE_PLANO", "gratis")
# versão fixa: o alias "sonnet" virou Sonnet 5 em 25/09 e ele entrega 150-250 palavras num limite de ~110 (ignora o
# total e até orçamento por cena); o 4.6 fica em 99-109. Trocar de modelo só depois de testar tamanho e nota do juiz.
MODELO_ROTEIRO = _cfg("MILIONERE_MODELO_ROTEIRO", "claude-sonnet-4-6")
MODELO_JUIZ = _cfg("MILIONERE_MODELO_JUIZ", "haiku")          # confere contra critérios fixos: o barato basta
# juiz do ROTEIRO separado do visual: o Haiku tratou omissão como erro factual e fez 2 de 9 rodadas desistirem (noite 24/09)
MODELO_JUIZ_ROTEIRO = _cfg("MILIONERE_MODELO_JUIZ_ROTEIRO", MODELO_JUIZ)
JUIZ_ROTEIRO = _cfg("MILIONERE_JUIZ_ROTEIRO", "1") == "1"     # juiz de IA no roteiro genérico (desligar = só código)
ESFORCO_ROTEIRO = _cfg("MILIONERE_ESFORCO_ROTEIRO", "medium")  # API: low | medium | high (ignorado no Haiku)
ESFORCO_JUIZ = _cfg("MILIONERE_ESFORCO_JUIZ", "low")
# raciocínio interno (thinking) no claude -p: 0 = desligado. Medido no roteiro bíblico (24/09): esforço médio passou de
# 10 min; baixo, 225 s e 16,5 mil tokens; com 0, 83 s e 5 mil tokens (quase só o JSON). Suba se a qualidade cair.
PENSAR_TOKENS = _cfg("MILIONERE_PENSAR_TOKENS", "0")
