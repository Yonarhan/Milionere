"""Camadas de validação do roteiro e das imagens. Nada vai pra render sem passar por todas.

  Camada 1 (código, instantânea): tamanho, gancho, CTA, linguagem de IA, versículo idêntico à fonte,
           eventos dentro do trecho bíblico e em ordem, cenas seguindo a ordem dos eventos, personagens
           declarados e com ficha visual.
  Camada 2 (juiz LLM, conversa nova, só vê a fonte e o roteiro): fidelidade aos fatos, ordem, personagens
           consistentes, compreensão de quem ouve uma vez (nota >= 4 em cada) + gancho, ritmo, linguagem,
           payoff (média >= 3.5, nenhum <= 2). Qualquer erro factual = reprovado, e os problemas voltam pro roteirista reescrever.
  Camada 3 (juiz visual, depois das imagens): uma imagem por vez, em resolução cheia. Primeiro anatomia e
           artefatos (mãos, rostos extras, corpos fundidos, texto, objeto moderno), depois se contradiz a fala.
           Cena reprovada ganha 3 opções novas e fica a primeira aprovada.
  Camada 4 (pipeline.py, depois do render): duração do vídeo e sincronia legenda/cenas.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import llm  # noqa: E402
import medidor  # noqa: E402

VOCAB_IA = ["fascinante", "incrível jornada", "desvendar", "crucial", "notável", "intrigante", "vasto universo",
            "mistérios do", "não apenas", "não é só", "e sabe o que", "realmente", "cientistas acreditam",
            "jornada", "tapeçaria", "mergulhar", "inspirador", "poderosa lição", "nos ensina que"]
CTA = re.compile(r"\b(amém|amem|comenta|manda|escreve|compartilha|salva)\b", re.I)
ORDEM_LIVROS = list(biblia.LIVROS.values())


def _pos(rotulo: str) -> tuple[int, int, int]:
    """'1 Samuel 1:13' -> (8, 1, 13)"""
    livro, cv = rotulo.rsplit(" ", 1)
    c, v = cv.split(":")
    return ORDEM_LIVROS.index(livro), int(c), int(v)


def _palavras(t: str) -> list[str]:
    return re.findall(r"[\wÀ-ÿ]+", t)


# ---------------------------------------------------------------- camada 1

def camada1(r: dict, formato: dict, tema: dict) -> list[str]:
    erros: list[str] = []
    cenas = r["cenas"]
    total = sum(len(_palavras(c["fala"])) for c in cenas)
    lo, hi = formato["palavras"]
    if not lo <= total <= hi:
        erros.append(f"roteiro tem {total} palavras; o formato pede {lo} a {hi}")
    c_lo, c_hi = formato["cenas"]
    if not c_lo <= len(cenas) <= c_hi:
        erros.append(f"{len(cenas)} cenas; o formato pede {c_lo} a {c_hi}")
    if len(_palavras(cenas[0]["fala"])) > 8:
        erros.append(f"gancho com {len(_palavras(cenas[0]['fala']))} palavras (máx. 8): «{cenas[0]['fala']}»")
    if not CTA.search(cenas[-1]["fala"]):
        erros.append(f"última cena não é um CTA: «{cenas[-1]['fala']}»")
    for i, c in enumerate(cenas, 1):
        n = len(_palavras(c["fala"]))
        if n > 16:
            erros.append(f"cena {i} com {n} palavras (máx. 14-16), divida: «{c['fala']}»")
        if "—" in c["fala"] or "–" in c["fala"] or ";" in c["fala"]:
            erros.append(f"cena {i} tem travessão ou ponto e vírgula (o TTS lê mal): «{c['fala']}»")
        baixo = c["fala"].lower()
        for v in VOCAB_IA:
            if v in baixo:
                erros.append(f"cena {i} usa '{v}' (linguagem de IA)")

    # versículo citado = texto exato da fonte, e dentro do trecho do tema
    fonte_tema = {rot for rot, _ in biblia.versiculos(tema["ref"])}
    try:
        citado = biblia.versiculos(r["versiculo"]["ref"])
        fonte_txt = biblia.normalizar(" ".join(t for _, t in citado))
        for pedaco in re.split(r"\.\.\.|…", r["versiculo"]["texto"]):
            p = biblia.normalizar(pedaco)
            if len(p.split()) >= 3 and p not in fonte_txt:
                erros.append(f"versículo citado não bate com a fonte ({r['versiculo']['ref']}): «{pedaco.strip()}»")
        if not fonte_tema & {rot for rot, _ in citado}:
            erros.append(f"versículo {r['versiculo']['ref']} está fora do trecho do tema ({tema['ref']})")
    except biblia.RefInvalida as e:
        erros.append(f"versículo citado inválido: {e}")

    # eventos: dentro do trecho e na ordem do texto
    biblico = formato["epoca"] == "biblica"
    ns = [e["n"] for e in r["eventos"]]
    if ns != sorted(ns) or len(set(ns)) != len(ns):
        erros.append(f"eventos fora de ordem ou repetidos: {ns}")
    ultima = None
    for e in r["eventos"]:
        if not e["ref"].strip():
            if biblico:
                erros.append(f"evento {e['n']} ('{e['evento']}') sem versículo: em história bíblica todo fato precisa de fonte")
            continue
        try:
            rots = [rot for rot, _ in biblia.versiculos(e["ref"])]
        except biblia.RefInvalida as ex:
            erros.append(f"evento {e['n']}: referência inválida ({ex})")
            continue
        if biblico and not set(rots) <= fonte_tema:
            erros.append(f"evento {e['n']} ('{e['evento']}') cita {e['ref']}, fora do trecho fornecido ({tema['ref']})")
        pos = _pos(rots[0])
        if biblico and ultima and pos < ultima:
            erros.append(f"evento {e['n']} ({e['ref']}) vem antes, no texto, do evento anterior: ordem trocada")
        ultima = pos

    validos = set(ns)
    seq = [c["evento"] for c in cenas if c["evento"] != 0]
    if any(b < a for a, b in zip(seq, seq[1:])):
        erros.append(f"as cenas contam os eventos fora de ordem: {[c['evento'] for c in cenas]}")
    for i, c in enumerate(cenas, 1):
        if c["evento"] and c["evento"] not in validos:
            erros.append(f"cena {i} aponta o evento {c['evento']}, que não existe")

    # personagens: declarados, com ficha, no máximo 2 por imagem
    ids = [p["id"] for p in r["personagens"]]
    if len(ids) != len(set(ids)):
        erros.append(f"personagem repetido na lista: {ids}")
    for p in r["personagens"]:
        if len(p["descricao_visual"].split()) < 8:
            erros.append(f"ficha visual de '{p['id']}' vaga demais: «{p['descricao_visual']}»")
    for i, c in enumerate(cenas, 1):
        for pid in c["personagens"]:
            if pid not in ids:
                erros.append(f"cena {i} usa o personagem '{pid}', que não está na lista de personagens")
        if len(c["personagens"]) > 2:
            erros.append(f"cena {i} com {len(c['personagens'])} personagens na imagem (máx. 2, o rosto se mistura)")
    return erros


# ---------------------------------------------------------------- camada 2

CRITERIOS = {
    "fidelidade": "todo fato narrado está na FONTE, sem acréscimo, troca ou exagero apresentado como fato",
    "ordem": "da cena 2 em diante, os fatos aparecem na mesma ordem da fonte (e, na parábola, em ordem cronológica). A cena 1 é o gancho: pode antecipar qualquer momento da história (é pedido do formato) e não conta para a ordem",
    "personagens": "os mesmos personagens do começo ao fim, com os nomes e papéis certos, sem ninguém surgir do nada",
    "compreensao": "quem nunca leu a história entende tudo ouvindo UMA vez, sem ver a tela",
    "gancho": "a primeira frase faz parar de rolar o feed",
    "ritmo": "frases curtas mas LIGADAS (conectivos), soando como uma história contada de uma vez, não uma lista de frases soltas ou telegráficas; nenhuma frase sobrando",
    "linguagem": "soa como gente falando, sem cara de IA nem de livro",
    "payoff": "o final entrega emoção ou virada e responde o gancho",
}
# fatos, ordem, personagens e compreensão: nota >= 4 obrigatória. Os de gosto: média >= 3.5 e nenhum <= 2.
RIGIDOS = ["fidelidade", "ordem", "personagens", "compreensao"]
SUBJETIVOS = ["gancho", "ritmo", "linguagem", "payoff"]
MEDIA_SUBJETIVA = 3.5
SCHEMA_JUIZ = {
    "type": "object", "additionalProperties": False,
    "required": ["entendimento", "erros_factuais", "criterios"],
    "properties": {
        "entendimento": {"type": "string", "description": "em 1 frase, o que um ouvinte entende da história"},
        "erros_factuais": {"type": "array", "items": {"type": "string"},
                           "description": "cada fato que contradiz ou não está na fonte, com o número da cena"},
        "criterios": {"type": "array", "minItems": len(CRITERIOS), "maxItems": len(CRITERIOS), "items": {
            "type": "object", "additionalProperties": False, "required": ["criterio", "nota", "problemas"],
            "properties": {"criterio": {"type": "string", "enum": list(CRITERIOS)},
                           "nota": {"type": "integer", "minimum": 1, "maximum": 5},
                           "problemas": {"type": "array", "items": {"type": "string"}}}}},
    },
}


def camada2(r: dict, formato: dict, tema: dict) -> tuple[list[str], dict]:
    cenas = "\n".join(f"{i}. [evento {c['evento']}] [na imagem: {', '.join(c['personagens']) or 'ninguém'}] {c['fala']}"
                      for i, c in enumerate(r["cenas"], 1))
    eventos = "\n".join(f"{e['n']}. {e['evento']} ({e['ref'] or 'inventado'})" for e in r["eventos"])
    pers = "\n".join(f"- {p['id']}: {p['nome']}" for p in r["personagens"])
    prompt = (
        "Você é um revisor rigoroso de vídeos curtos cristãos. Um roteirista escreveu o roteiro abaixo. Seu trabalho é "
        "achar problemas, não elogiar. Nota 5 só quando não há nada a melhorar. Nota 3 = publicável com defeito visível.\n\n"
        f"# Formato\n{formato['nome']}\n{formato['receita']}\n\n"
        f"# FONTE ({biblia.TRADUCAO})\n{biblia.trecho(tema['ref'])}\n\n"
        f"# Roteiro (cada linha é uma cena falada por uma voz, com uma imagem)\n{cenas}\n\n"
        f"# Linha do tempo declarada pelo roteirista\n{eventos}\n\n# Personagens\n{pers}\n\n"
        f"# Versículo citado\n{r['versiculo']['ref']}: {r['versiculo']['texto']}\n\n"
        "# Como avaliar\n"
        + "\n".join(f"- {k}: {v}" for k, v in CRITERIOS.items()) +
        "\n\nErro factual = algo apresentado como fato que não está na fonte ou a contradiz (fala inventada atribuída a "
        "alguém, número errado, nome trocado, milagre que não houve, ordem invertida). Emoção e ambiente em tom de "
        "hipótese ('imagina o medo') não são erro. Omitir, resumir ou encurtar uma fala ou citação (deixar de fora "
        "uma cláusula, um 'a ti mesmo') NUNCA é erro factual: é omissão, e omissão só vira problema de compreensao se "
        "mudar o sentido. Na parábola moderna a história é inventada de propósito: aí só o "
        "provérbio e o sentido dele precisam ser fiéis.\n"
        "A narrativa não pode ser interrompida: frase falando com o espectador (2ª pessoa, pergunta ao público, "
        "aplicação) no meio da história, antes do clímax, soa como se tivesse pulado um pedaço. Isso é problema de "
        "compreensao (nota <= 3): mande mover a frase para depois do clímax.\n"
        f"O vídeo tem limite de {formato['palavras'][0]} a {formato['palavras'][1]} palavras ({sum(len(_palavras(c['fala'])) for c in r['cenas'])} agora): "
        "não dá pra contar tudo. Omitir um detalhe secundário NÃO é erro; só é erro se a omissão mudar o sentido. "
        "Toda correção que você sugerir precisa caber no limite: se pedir para acrescentar, diga o que cortar.\n"
        "Cada problema deve dizer o número da cena e como corrigir, em 1 frase. Aponte no máximo os 5 problemas mais "
        "graves: o roteirista corrige o que você apontar, e uma lista longa de detalhes faz ele desmontar o que estava bom."
    )
    j = llm.chamar(prompt, SCHEMA_JUIZ, papel="juiz")
    problemas = [f"ERRO FACTUAL: {e}" for e in j["erros_factuais"]]
    notas = {c["criterio"]: c["nota"] for c in j["criterios"]}
    subjetivas = [notas[k] for k in SUBJETIVOS]
    reprova_subj = sum(subjetivas) / len(subjetivas) < MEDIA_SUBJETIVA or min(subjetivas) <= 2
    for c in j["criterios"]:
        ruim = c["nota"] < 4 if c["criterio"] in RIGIDOS else (reprova_subj and c["nota"] < 4)
        if ruim:
            problemas += [f"{c['criterio']} (nota {c['nota']}): {p}" for p in c["problemas"]] or [f"{c['criterio']} com nota {c['nota']}"]
    return problemas, j


# ---------------------------------------------------------------- camada 3

SCHEMA_VISUAL = {
    "type": "object", "additionalProperties": False,
    "required": ["defeitos", "combina", "problema", "imagem_corrigida"],
    "properties": {
        "defeitos": {"type": "array", "items": {"type": "string"},
                     "description": "cada defeito GRAVE achado na checagem de anatomia/artefatos; vazio se nenhum"},
        "combina": {"type": "boolean", "description": "a imagem serve para o momento da fala (não contradiz)"},
        "problema": {"type": "string", "description": "se reprovada: o problema principal em 1 frase; senão vazio"},
        "imagem_corrigida": {"type": "string", "description": "se reprovada: novo prompt em inglês; senão vazio"},
    },
}
JUIZES_EM_PARALELO = 4


def julgar_imagem(r: dict, n: int, arq: Path, epoca: str, juiz: str | None = None) -> dict:
    """Juiz visual de UMA imagem, em resolução cheia. Devolve {cena, ok, problema, imagem_corrigida}.
    juiz: None = padrão (llm.JUIZ_VISUAL, variável MILIONERE_JUIZ_VISUAL); 'claude' ou 'ollama:<modelo>'."""
    juiz = juiz or llm.JUIZ_VISUAL
    local = juiz.startswith("ollama:")
    c = r["cenas"][n - 1]
    pers = {p["id"]: p for p in r["personagens"]}
    # nome + aparência da ficha: sem a aparência o juiz não sabe quem é quem e não pega papéis trocados
    quem = ("; ".join(f"{pers[p]['nome']} ({pers[p]['descricao_visual']})" for p in c["personagens"] if p in pers)
            or "nenhum personagem da história (pessoa anônima pode aparecer, se combinar com a fala)")
    prompt = (
        ("A imagem está anexada." if local else f"Abra a imagem {arq} com a ferramenta Read.")
        + " Ela vai num vídeo cristão realista; defeito de IA derruba o vídeo.\n\n"
        "PASSO 1, anatomia e artefatos (o mais importante). Olhe devagar, parte por parte:\n"
        "- cada MÃO: conte os dedos, veja se o tamanho bate com o corpo, se está presa a um braço, se não há mão sobrando;\n"
        "- cada ROSTO: olhos, boca e proporção normais; nenhum rosto extra, cortado, fundido ou surgindo no meio da cena;\n"
        "- CORPOS: braços e pernas na quantidade e posição possíveis, nenhum membro saindo de lugar errado, pessoas não "
        "fundidas entre si ou com objetos;\n"
        "- texto, letras, assinatura ou marca d'água em qualquer canto;\n"
        + ("- objeto moderno (roupa atual, óculos, relógio, prédio, luz elétrica), auréola, símbolo de outra religião;\n"
           if epoca == "biblica" else "- símbolo de outra religião ou algo constrangedor;\n") +
        "Liste em `defeitos` só o que um espectador comum perceberia num celular. Mão em silhueta ou borrada pelo "
        "movimento não é defeito.\n\n"
        f"PASSO 2, história. Fala narrada nesta cena: «{c['fala']}». Quem deve aparecer: {quem}.\n"
        f"O que a cena deveria mostrar (prompt usado): {c.get('imagem', '')}\n"
        "Use esse prompt só para saber quem é quem e onde cada um está; cenário, luz ou fundo diferentes do prompt NÃO "
        "reprovam (só reprova fundo com defeito do passo 1).\n"
        "`combina` = false só se a imagem CONTRADIZ a fala (pessoa errada, emoção oposta, ação oposta) ou não tem nada "
        "a ver. Confira também QUEM FAZ O QUÊ: cada personagem citado aparece uma única vez (o mesmo rosto e roupa "
        "repetido na cena é defeito) e no papel que a fala descreve (quem está em cima e quem está embaixo, quem chama e "
        "quem é chamado); papéis trocados = `combina` false. Imagem evocativa que não mostra a ação ao pé da letra combina. Cor de roupa, expressão exata e "
        "enquadramento NÃO são motivo de reprovação.\n\n"
        "Se houver defeito ou não combinar, escreva o problema e um prompt novo que evite o problema. O prompt novo "
        "descreve só enquadramento, ação, chão, luz e lugar; NUNCA a aparência de um personagem (idade, cabelo, barba, "
        "roupa, asas), que vem da ficha fixa e entra sozinha. Em inglês, até 35 palavras, sem negação ('no people' "
        "atrai gente), com o chão e o fundo descritos."
    )
    if local:
        v = llm.chamar_ollama(prompt, SCHEMA_VISUAL, juiz.split(":", 1)[1], imagens=[arq])
    else:
        with medidor.etapa("juiz_visual"):
            v = llm.chamar(prompt, SCHEMA_VISUAL, ler_arquivos_em=arq.parent)
    ok = not v["defeitos"] and v["combina"]
    problema = v["problema"] or "; ".join(v["defeitos"])
    return {"cena": n, "ok": ok, "problema": "" if ok else problema,
            "imagem_corrigida": "" if ok else v["imagem_corrigida"]}


def julgar_varias(r: dict, itens: list[tuple[int, Path]], epoca: str, juiz: str | None = None) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    local = (juiz or llm.JUIZ_VISUAL).startswith("ollama:")  # a GPU local julga uma por vez
    import contextvars
    # cada thread leva uma cópia do contexto: sem isso o medidor (contextvars) não vê as chamadas do juiz
    ctxs = [contextvars.copy_context() for _ in itens]
    with ThreadPoolExecutor(1 if local else JUIZES_EM_PARALELO) as ex:
        return list(ex.map(lambda p: p[0].run(julgar_imagem, r, p[1][0], p[1][1], epoca, juiz), zip(ctxs, itens)))


def camada3(r: dict, pasta: Path, epoca: str, so: list[int] | None = None) -> list[dict]:
    """Juiz visual, uma imagem por vez. Devolve as cenas reprovadas: [{cena, problema, imagem_corrigida}]."""
    itens = [(i, a) for i in range(1, len(r["cenas"]) + 1) if not so or i in so
             for a in [next(iter(sorted(pasta.glob(f"cena_{i:02d}.*"))), None)] if a]
    return [v for v in julgar_varias(r, itens, epoca) if not v["ok"]]
