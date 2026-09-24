"""O guia da IA: o bloco que entra em TODO prompt de roteiro, montado a partir da memória do nicho.

    guia.bloco(nicho, formato, tema) -> texto com:
      1. exemplos aprovados do nicho, os mais parecidos com o tema e mais bem avaliados (estilo, não conteúdo)
      2. os erros que o juiz mais apontou neste nicho (lista de "não faça")
      3. o que já funcionou com o público (producao/aprendizados.md)
    guia.checar(cenas, preset) -> problemas encontrados por CÓDIGO (grátis): tamanho, gancho, CTA, cara de IA...

Quanto mais vídeos o nicho tem, mais específico fica o guia. Se o banco estiver vazio, o bloco sai vazio.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402

VOCAB_IA = ["fascinante", "incrível jornada", "desvendar", "crucial", "notável", "intrigante", "vasto universo",
            "mistérios do", "não apenas", "não é só", "e sabe o que", "realmente", "cientistas acreditam", "jornada",
            "tapeçaria", "mergulhar", "inspirador", "poderosa lição", "nos ensina que"]
CTA = re.compile(r"\b(amém|amem|comenta|comente|manda|escreve|compartilha|salva|segue|qual|inscrev\w*)\b", re.I)


def _palavras(t: str) -> int:
    return len(re.findall(r"[\wÀ-ÿ]+", t))


def bloco(nicho: str, formato: str, tema: str) -> str:
    partes = []
    try:
        import banco_roteiros
        exemplos = banco_roteiros.buscar_exemplos(nicho, tema, k=3, excluir_tema=tema)
        if exemplos:
            linhas = [f"## {e['titulo']}\n" + "\n".join(f"- {f}" for f in e["falas"]) for e in exemplos]
            partes.append("# Exemplos aprovados deste nicho\nCopie o RITMO, o tamanho das frases e o tipo de gancho e de final. "
                          "NÃO copie o conteúdo nem as frases.\n\n" + "\n\n".join(linhas))
        erros = banco_roteiros.erros_comuns(nicho, n=8)
        if erros:
            partes.append("# Erros que o revisor mais reprovou neste nicho (não repita)\n"
                          + "\n".join(f"- {t} ({c}x)" for t, c in erros))
    except Exception as e:  # o guia ajuda, mas nunca derruba a geração
        partes.append(f"<!-- guia indisponível: {e} -->")
    aprend = caminhos.RAIZ / "producao" / "aprendizados.md"
    if aprend.exists():
        partes.append("# O que já funcionou com o público\n" + aprend.read_text(encoding="utf-8")[-3000:])
    return "\n\n".join(p for p in partes if p)


def checar(cenas: list[dict], preset: dict) -> list[str]:
    """Camada 1 genérica (código, grátis). Devolve a lista de problemas; vazia = passou."""
    erros = []
    falas = [c["fala"].strip() for c in cenas if c.get("fala", "").strip()]
    if not falas:
        return ["roteiro vazio"]
    total = sum(_palavras(f) for f in falas)
    lo, hi = preset.get("palavras_min", 45), preset.get("palavras_max", 90)
    if not lo <= total <= hi:
        erros.append(f"roteiro com {total} palavras; o nicho pede {lo} a {hi}")
    if not 6 <= len(falas) <= 15:
        erros.append(f"{len(falas)} cenas; use de 6 a 15")
    if _palavras(falas[0]) > 8:
        erros.append(f"gancho com {_palavras(falas[0])} palavras (máx. 8): «{falas[0]}»")
    if not CTA.search(falas[-1]):
        erros.append(f"a última cena não é uma chamada (comenta, manda, escreve...): «{falas[-1]}»")
    for i, f in enumerate(falas, 1):
        if _palavras(f) > 16:
            erros.append(f"cena {i} com {_palavras(f)} palavras (máx. 16), divida: «{f}»")
        if re.search(r"[—–;]", f):
            erros.append(f"cena {i} tem travessão ou ponto e vírgula (a voz lê mal): «{f}»")
        for v in VOCAB_IA:
            if v in f.lower():
                erros.append(f"cena {i} usa '{v}' (linguagem de IA)")
    return erros
