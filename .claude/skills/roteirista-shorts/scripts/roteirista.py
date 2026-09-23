"""Roteirista automático: tema + texto bíblico exato -> roteiro em cenas (fala + prompt de imagem + personagens).

O texto bíblico vai no prompt como FONTE DA VERDADE. O modelo não escreve de memória: ele recebe os
versículos da Bíblia Portuguesa Mundial e o juiz (validar.py) confere contra o mesmo texto.

Uso direto (teste):
    python roteirista.py --formato historia --tema jonas-peixe
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import llm  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]
RAIZ = Path(__file__).resolve().parents[4]
REFS = SKILL / "references"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ganchos", "titulo", "cenario_en", "personagens", "eventos", "cenas", "versiculo",
                 "descricao", "hashtags", "comentario_fixado", "autoavaliacao"],
    "properties": {
        "ganchos": {"type": "array", "minItems": 5, "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["texto", "choque", "clareza", "imagem"],
            "properties": {"texto": {"type": "string"}, "choque": {"type": "integer"},
                           "clareza": {"type": "integer"}, "imagem": {"type": "integer"}}}},
        "titulo": {"type": "string", "description": "título do post, até 60 caracteres, pode ter 1 emoji"},
        "cenario_en": {"type": "string", "description": "em inglês: época e lugar comuns a todas as cenas (ex.: 'ancient Judea, 1st century, stone houses, dusty roads')"},
        "personagens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "nome", "nome_en", "descricao_visual"],
            "properties": {"id": {"type": "string"}, "nome": {"type": "string"}, "nome_en": {"type": "string"},
                           "descricao_visual": {"type": "string", "description": "em inglês: idade, cabelo, barba, pele, roupa. Fixa."}}}},
        "eventos": {"type": "array", "description": "a linha do tempo dos fatos contados, NA ORDEM em que acontecem", "items": {
            "type": "object", "additionalProperties": False, "required": ["n", "evento", "ref"],
            "properties": {"n": {"type": "integer"}, "evento": {"type": "string"},
                           "ref": {"type": "string", "description": "versículo que sustenta o evento; vazio se for inventado (parábola moderna)"}}}},
        "cenas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["fala", "evento", "personagens", "rosto_visivel", "imagem", "busca"],
            "properties": {
                "fala": {"type": "string"},
                "evento": {"type": "integer", "description": "n do evento narrado; 0 = fora da linha do tempo (gancho, aplicação, CTA)"},
                "personagens": {"type": "array", "items": {"type": "string"}, "description": "ids que APARECEM na imagem, o principal primeiro"},
                "rosto_visivel": {"type": "boolean"},
                "imagem": {"type": "string", "description": "em inglês: o que a imagem mostra, enquadramento, emoção, luz. Sem descrever a aparência dos personagens (ela entra sozinha)."},
                "busca": {"type": "string", "description": "em inglês: termo de vídeo de banco (Pexels) como reserva"}}}},
        "versiculo": {"type": "object", "additionalProperties": False, "required": ["ref", "texto"],
                      "properties": {"ref": {"type": "string"}, "texto": {"type": "string", "description": "copiado EXATAMENTE da fonte"}}},
        "descricao": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "comentario_fixado": {"type": "string"},
        "autoavaliacao": {"type": "object", "additionalProperties": False,
                          "required": ["gancho", "clareza", "ritmo", "payoff", "precisao", "imagem"],
                          "properties": {k: {"type": "integer"} for k in ["gancho", "clareza", "ritmo", "payoff", "precisao", "imagem"]}},
    },
}


REGRAS_IMAGEM = (
    "Prompt de imagem para Stable Diffusion XL, em inglês, no máximo 30 palavras. Comece pelo enquadramento e pela AÇÃO "
    "com emoção ('medium shot of a bearded fisherman sinking in stormy waves, screaming, one arm raised'). Um sujeito "
    "principal fazendo UMA coisa clara. Dois personagens juntos só em plano médio ou aberto com ação simples (abraço, "
    "mão estendida). Contato de mãos = close-up só das mãos. Nada de negação ('no halo'), nada de texto, e não descreva "
    "a aparência dos personagens (ela entra sozinha). Termine com luz e lugar."
)


def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def montar_prompt(formato: dict, tema: dict, correcoes: list[str] | None = None, anterior: dict | None = None) -> str:
    fonte = biblia.trecho(tema["ref"])
    conhecidos = biblia.personagens()
    fichas = "\n".join(f"- id `{k}`: {v['nome']} ({v['nome_en']}) — {v['descricao_visual']}" for k, v in conhecidos.items())
    esperados = ", ".join(tema.get("personagens", [])) or "(defina)"
    lo, hi = formato["palavras"]
    c_lo, c_hi = formato["cenas"]
    partes = [
        "Você é roteirista de Shorts/TikTok cristãos em português do Brasil. Escreva UM roteiro no formato abaixo.",
        f"# Formato: {formato['nome']}\n{formato['receita']}",
        f"# Tema\n{tema['titulo']}\nÂngulo sugerido: {tema['angulo']}",
        f"# FONTE DA VERDADE ({biblia.TRADUCAO})\n{fonte}\n\n"
        "Regras de fidelidade (serão conferidas por um juiz contra este texto):\n"
        "- Todo fato bíblico narrado precisa estar NESTE texto. Não acrescente milagre, fala, número ou detalhe que não está nele.\n"
        "- Dramatização é permitida só como emoção ou ambiente ('imagina o medo'), nunca como fato novo.\n"
        "- Conte os fatos NA ORDEM em que aparecem no texto. Cada cena aponta o evento que narra.\n"
        "- Os personagens têm os nomes do texto e não trocam de nome nem de papel no meio.\n"
        "- Quem ouve nunca leu essa história e não vê a tela: cada fala diz QUEM fez, O QUE fez e, quando importa, POR QUÊ. "
        "Nada de 'ele' sem nome antes, 'lá dentro' sem dizer onde, ou personagem que surge sem apresentação. "
        "Quem age num milagre é Deus: diga isso, não atribua a ação a um objeto ou animal.\n"
        "- É UMA voz narrando: fala de personagem sempre com verbo ('Jesus disse: Venha!'), nunca 'Jesus: Venha!'. "
        "Conclusão sua ('nunca chegou ao fundo') também é fato novo: só diga o que o texto diz.\n"
        "- `versiculo.texto` é copiado letra por letra da fonte (pode cortar com '...'). Na fala pode ser adaptado.",
        f"# Personagens com aparência fixa (reuse o id e NÃO mude a descrição)\n{fichas}\n"
        f"Personagens esperados neste tema: {esperados}. Para quem não está na lista, crie id em minúsculas com hífen "
        "e uma descricao_visual em inglês bem específica (idade, cabelo, barba, pele, roupa), sem nome próprio.\n"
        "Numa cena, `personagens` lista só quem aparece na imagem. Máximo 2 por cena. Rosto de Deus nunca aparece.",
        f"# Tamanho\n{lo} a {hi} palavras no total, {c_lo} a {c_hi} cenas. Uma frase por cena, 3 a 14 palavras. "
        "A primeira cena é o gancho (até 8 palavras). A última é o CTA.",
        f"# Ganchos\n{_ler(REFS / 'ganchos.md')}\nEscreva 5 ganchos, dê nota 1-5 e use o melhor na cena 1.",
        f"# Linguagem\n{_ler(REFS / 'anti-ia.md')}",
        f"# O que já funcionou no canal\n{_ler(REFS / 'persona-gospel.md')}\n{_ler(RAIZ / 'producao' / 'aprendizados.md')}",
        "# Imagens\nCada `imagem` mostra literalmente o que a fala diz. Varie o enquadramento. " + REGRAS_IMAGEM + " "
        f"Época: {'bíblica, sem nenhum objeto moderno' if formato['epoca'] == 'biblica' else 'Brasil atual, pessoas comuns'}.",
        "# Post\nTítulo até 60 caracteres (pergunta ou curiosidade, não repita o gancho). Descrição: o versículo entre aspas "
        "com referência, 2 frases, uma pergunta e 'Leia <livro capítulo>'. 5 hashtags com #shorts. Comentário fixado com "
        "pergunta pessoal. Autoavaliação honesta de 1 a 5.",
    ]
    if anterior and correcoes:
        partes.append("# REESCREVA\nSua versão anterior foi reprovada. Versão anterior:\n"
                      + json.dumps({k: anterior[k] for k in ("cenas", "eventos", "versiculo") if k in anterior}, ensure_ascii=False)
                      + "\nCorrija TODOS estes problemas, sem criar outros:\n" + "\n".join(f"- {c}" for c in correcoes)
                      + f"\n\nLIMITE RÍGIDO: {lo} a {hi} palavras no total (a versão anterior tinha "
                      + f"{sum(len(c['fala'].split()) for c in anterior['cenas'])}). Para cada palavra que acrescentar, corte "
                      "outra: junte cenas, tire adjetivos, troque frase explicativa por uma mais curta. Passar do limite = reprovado.")
    return "\n\n".join(partes)


def escrever(formato: dict, tema: dict, correcoes: list[str] | None = None, anterior: dict | None = None) -> dict:
    r = llm.chamar(montar_prompt(formato, tema, correcoes, anterior), SCHEMA)
    # consistência por construção: personagem que já existe usa SEMPRE a ficha salva
    conhecidos = biblia.personagens()
    for p in r["personagens"]:
        if p["id"] in conhecidos:
            p.update(conhecidos[p["id"]])
    return r


SCHEMA_PROMPTS = {"type": "object", "additionalProperties": False, "required": ["imagens"],
                  "properties": {"imagens": {"type": "array", "items": {"type": "string"}}}}


def reescrever_imagens(r: dict) -> None:
    """Reescreve os prompts de imagem de um roteiro já aprovado nas regras do SDXL (as falas não mudam)."""
    linhas = "\n".join(f"{i}. fala: «{c['fala']}» | personagens na imagem: {', '.join(c['personagens']) or 'nenhum'} | "
                       f"atual: {c['imagem']}" for i, c in enumerate(r["cenas"], 1))
    novo = llm.chamar(f"{REGRAS_IMAGEM}\n\nReescreva o prompt de cada cena abaixo seguindo essas regras, mantendo o que a "
                      f"cena precisa mostrar. Devolva {len(r['cenas'])} prompts, na ordem.\n\n{linhas}", SCHEMA_PROMPTS)
    if len(novo["imagens"]) == len(r["cenas"]):
        for c, t in zip(r["cenas"], novo["imagens"]):
            c["imagem"] = t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formato", required=True)
    ap.add_argument("--tema", required=True)
    ap.add_argument("--prompt", action="store_true", help="só imprime o prompt")
    args = ap.parse_args()
    formatos = json.loads((SKILL / "formatos.json").read_text(encoding="utf-8"))
    formato = formatos[args.formato]
    tema = next(t for t in biblia.temas()[formato["catalogo"]] if t["id"] == args.tema)
    if args.prompt:
        print(montar_prompt(formato, tema))
        return
    print(json.dumps(escrever(formato, tema), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
