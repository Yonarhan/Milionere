"""Guia visual: as reprovações do juiz visual viram regras nos próximos prompts de imagem.

Cada imagem reprovada fica em <PRODUCAO>/midia/_reprovadas/reprovadas.jsonl com o motivo (pipeline.guardar_reprovada).
Aqui os motivos são agrupados por tipo de defeito; os tipos mais frequentes entram como regra fixa no texto que
orienta quem escreve o prompt (roteirista e juiz, via roteirista.regras_imagem()). Regra fixa por tipo, e não o
motivo cru, porque o motivo cita o defeito ("relógio") e citar o defeito no prompt atrai o defeito.

Uso:
    python guia_visual.py        # mostra a contagem por tipo e o bloco que entra no prompt
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402

ARQ = caminhos.PRODUCAO / "midia" / "_reprovadas" / "reprovadas.jsonl"
MIN_OCORRENCIAS = 2
MAX_REGRAS = 5

# tipo -> (padrão no motivo, regra escrita só com o que DEVE aparecer)
TIPOS = {
    "pes": (r"\bp[ée]s?\b|dedos do p[ée]|sola|cal[çc]ad|sapato|chinelo|sand[áa]lia|t[êe]nis|bota",
            "pessoa sentada ou ajoelhada em plano da cintura para cima (waist-up), sem os pés na imagem"),
    "pulso": (r"rel[óo]gio|pulseira|pulso",
              "mangas longas de lã cobrindo os braços até as mãos"),
    "objeto": (r"modern|met[áa]lic|metal|pl[áa]stic|ferramenta|anacron",
               "só objetos da época (jarro de barro, odre de couro, pão, cajado de madeira) e chão descrito como areia lisa ou rocha"),
    "maos": (r"\bm[ãa]os?\b|\bdedos?\b(?! do p)|bra[çc]o",
             "mãos junto ao corpo, em plano médio ou aberto, nunca em destaque"),
    "fundo": (r"fundo|p[áa]ssaro|criatura|animal|sobrando|pessoa a mais|pessoa extra",
              "no máximo 2 figuras em primeiro plano, multidão só ao fundo e desfocada"),
    "fusao": (r"fundid|brotando|chifre|cocar|grudad",
              "céu limpo ou parede de rocha atrás da cabeça, árvores e galhos afastados do personagem"),
}


def contagem(arq: Path = ARQ) -> Counter:
    c: Counter = Counter()
    if not arq.exists():
        return c
    for linha in arq.read_text(encoding="utf-8").splitlines():
        try:
            motivo = json.loads(linha).get("motivo", "").lower()
        except ValueError:
            continue
        for tipo, (padrao, _) in TIPOS.items():
            if re.search(padrao, motivo):
                c[tipo] += 1
    return c


def bloco() -> str:
    """Trecho que vai no fim das regras de imagem (vazio se ainda não há reprovações suficientes)."""
    mais = [(t, n) for t, n in contagem().most_common(MAX_REGRAS) if n >= MIN_OCORRENCIAS]
    if not mais:
        return ""
    return (" Os defeitos que o juiz visual mais reprovou nos vídeos anteriores pedem, em ordem: "
            + "; ".join(TIPOS[t][1] for t, _ in mais) + ".")


if __name__ == "__main__":
    for t, n in contagem().most_common():
        print(f"{n:>3}  {t}")
    print("\nbloco no prompt:" + (bloco() or " (vazio)"))
