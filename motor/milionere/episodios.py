"""Série bíblica em 2 passos: a HISTÓRIA COMPLETA primeiro (um roteirista, um juiz), depois o corte em episódios.

    historia(...)       -> um roteiro com o arco inteiro, validado (fatos, ordem, personagens, compreensão)
    particionar(...)    -> onde cortar + só o que é novo em cada episódio (gancho, recapitulação, suspense, CTA, post)
    montar(...)         -> cada episódio no formato do produzir.py, conferido pela camada 1 (tamanho, gancho, CTA)
    serie_biblica(...)  -> tudo junto: (plano, [(arquivo, pacote), ...])

Antes (serie.py): plano -> cada parte escrita do zero -> juiz em cada uma -> juiz da série mandando reescrever. A série
do José rodou 27+ min várias vezes e nunca fechou (25/09): cada parte brigava sozinha com o limite de palavras e com
a continuidade. Aqui a narração aprovada NÃO é reescrita no corte: só as frases de ligação são novas.
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import caminhos  # noqa: E402
import cta  # noqa: E402
import llm  # noqa: E402
import medidor  # noqa: E402
import roteirista  # noqa: E402
import validar  # noqa: E402
from serie import SerieInviavel  # noqa: E402  (o painel transforma em vídeo único)

TENTATIVAS_HISTORIA = 3
TENTATIVAS_CORTE = 3
TEMPO_MAX_HISTORIA = 480  # como o teto do juiz do CEO: passou, segue a melhor versão sem erro de fato, com avisos
MIOLO_EPISODIO = (45, 80)
# corte que só erra tamanho pode seguir com aviso, mas nunca acima disso: a voz fala ~2,5 palavras/s (medido em 4
# vídeos de 25/09: 96-102 palavras = 38-41 s), então 140 palavras ~ 56 s, abaixo do teto de 58 s da camada 4.
# Antes seguia um episódio de 172 palavras que ia reprovar no render, depois de gerar as imagens (José, 25/09)
TETO_PALAVRAS_EPISODIO = 140  # palavras da narração que cabem num episódio além do gancho, recapitulação e fechamento
RECEITA_HISTORIA = (
    "Conte o episódio bíblico INTEIRO como uma história falada, do primeiro ao último fato do trecho, na ORDEM do texto. "
    "Frases ligadas com conectivos (e, mas, então, só que), como alguém contando em voz alta; nada de lista de frases "
    "soltas. Cada virada (traição, prisão, reviravolta) fica clara numa frase própria: é onde a série vai ser cortada. "
    "Inclua um detalhe exato do texto que pouca gente nota. Termine no desfecho da história, sem sermão.")


# ---------------------------------------------------------------- 1. a história completa

def _formato_historia(formato: dict, max_partes: int) -> dict:
    f = {**formato, "completa": True, "receita": RECEITA_HISTORIA}
    # a camada 1 aceita +15%: o teto nominal fica abaixo para o total caber nos episódios (345 em 4 não cabia)
    f["palavras"] = [MIOLO_EPISODIO[0] * 2, int(MIOLO_EPISODIO[1] * max_partes / (1 + validar.MARGEM_PALAVRAS))]
    f["cenas"] = [10, 9 * max_partes]
    f.pop("nicho", None)  # sem a checagem de amém/inscrição: a história não tem fechamento
    return f


def _erros_historia(r: dict, f: dict, tema: dict) -> list[str]:
    """Camada 1 sem o que é de episódio (gancho curto e CTA vêm no corte)."""
    return [e for e in validar.camada1(r, f, tema)
            if not e.startswith("gancho com") and not e.startswith("última cena não é um CTA")]


def historia(formato: dict, tema: dict, max_partes: int, reg, log=print) -> dict:
    f = _formato_historia(formato, max_partes)
    correcoes, anterior, melhor, historico = None, None, None, []  # melhor = (pontos, roteiro, problemas, notas)
    comeco = time.time()
    for tentativa in range(1, TENTATIVAS_HISTORIA + 1):
        if melhor and _pode_seguir(melhor[3]) and time.time() - comeco > TEMPO_MAX_HISTORIA:
            log(f"história: passou de {TEMPO_MAX_HISTORIA // 60} min, segue a melhor versão")
            break
        log(f"história completa: tentativa {tentativa}")
        with medidor.etapa("serie_historia"):
            r = roteirista.escrever(f, tema, correcoes, anterior)
        palavras = sum(len(c["fala"].split()) for c in r["cenas"])
        e1 = _erros_historia(r, f, tema)
        reg.add("historia_camada1", not e1, tentativa=tentativa, problemas=e1, falas=[c["fala"] for c in r["cenas"]])
        if e1:
            log(f"  camada 1 reprovou ({palavras} palavras): " + " | ".join(e1[:3]))
            correcoes, anterior = e1 + historico, r
            continue
        e2, juiz = validar.camada2(r, f, tema)
        notas = {c["criterio"]: c["nota"] for c in juiz["criterios"]}
        # gancho/payoff não são da história inteira (são de cada episódio): só fatos, ordem, personagens e compreensão
        e2 = [p for p in e2 if p.startswith("ERRO FACTUAL") or p.split(" ")[0] in validar.RIGIDOS]
        reg.add("historia_camada2", not e2, tentativa=tentativa, notas=notas, problemas=e2,
                entendimento=juiz["entendimento"])
        log(f"  {palavras} palavras, notas do juiz: {notas}")
        if not e2:
            log("  história aprovada")
            r["_notas_juiz"] = notas
            return r
        log("  juiz reprovou: " + " | ".join(e2[:3]))
        pontos = sum(notas.values()) - 5 * len(juiz["erros_factuais"])
        if melhor is None or pontos >= melhor[0]:
            melhor = (pontos, r, e2, notas)
        historico += [p for p in e2 if p.startswith("ERRO FACTUAL") and p not in historico]
        correcoes, anterior = melhor[2] + historico, melhor[1]
    if melhor and _pode_seguir(melhor[3]):
        log(f"  segue a melhor versão da história, com {len(melhor[2])} aviso(s) para a revisão")
        melhor[1]["_notas_juiz"], melhor[1]["_avisos_juiz"] = melhor[3], [f"juiz: {p}" for p in melhor[2]]
        return melhor[1]
    raise RuntimeError(f"a história completa não passou em {TENTATIVAS_HISTORIA} tentativas (veja {reg.arq})")


def _pode_seguir(notas: dict) -> bool:
    """Sem aprovação, a melhor versão segue (com os pontos do juiz como aviso) se a FIDELIDADE for >= 4. O juiz dava
    fidelidade 4 e ainda listava 'erro factual' que ele mesmo chamava de 'inferência razoável' ('mandaram prender',
    'dois anos esquecido'): a história do José caiu 2x assim (25/09). Fidelidade <= 3 continua travando."""
    return notas.get("fidelidade", 0) >= 4


# ---------------------------------------------------------------- 2. o corte em episódios

_CENA = {"type": "object", "additionalProperties": False,
         "required": ["fala", "personagens", "rosto_visivel", "imagem", "busca"],
         "properties": {"fala": {"type": "string"},
                        "personagens": {"type": "array", "items": {"type": "string"}},
                        "rosto_visivel": {"type": "boolean"},
                        "imagem": {"type": "string", "description": "prompt de imagem em inglês (regras abaixo)"},
                        "busca": {"type": "string"}}}
SCHEMA_CORTE = {
    "type": "object", "additionalProperties": False, "required": ["titulo_serie", "arco", "partes"],
    "properties": {
        "titulo_serie": {"type": "string", "description": "até 45 caracteres"},
        "arco": {"type": "string", "description": "1-2 frases: começo, virada e fim da história inteira"},
        "partes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["n", "titulo", "inicio", "fim", "resumo", "virada", "gancho", "gancho_tela", "recap",
                         "suspense", "aplicacao", "fechamento", "versiculo", "descricao", "hashtags",
                         "comentario_fixado", "tiktok_titulo", "tiktok_legenda"],
            "properties": {
                "n": {"type": "integer"},
                "titulo": {"type": "string", "description": "título do post, até 50 caracteres (o '(Parte k/N)' entra sozinho): " + cta.REGRA_TITULO},
                "inicio": {"type": "integer", "description": "número da PRIMEIRA cena da história neste episódio"},
                "fim": {"type": "integer", "description": "número da ÚLTIMA cena da história neste episódio"},
                "resumo": {"type": "string"}, "virada": {"type": "string"},
                "gancho": {**_CENA, "description": "cena 1 do episódio: até 8 palavras, abre uma lacuna sobre ESTE episódio"},
                "gancho_tela": {"type": "string", "description": "3 a 6 palavras grandes na tela, complementa o gancho"},
                "recap": {**_CENA, "description": "episódio 2 em diante: 1 frase curta (até 12 palavras) do que aconteceu antes; fala vazia no episódio 1"},
                "suspense": {**_CENA, "description": "pergunta em aberto sobre o próximo episódio, sem contar o que acontece; fala vazia no último"},
                "aplicacao": {**_CENA, "description": "SÓ no último episódio: 1 frase em 2ª pessoa ligada a uma dor real; fala vazia nos outros"},
                "fechamento": {"type": "array", "minItems": 1, "maxItems": 2, "items": _CENA,
                               "description": "1 ou 2 cenas curtas pedindo o amém E a inscrição"},
                "versiculo": {"type": "object", "additionalProperties": False, "required": ["ref", "texto"],
                              "properties": {"ref": {"type": "string"},
                                             "texto": {"type": "string", "description": "copiado EXATAMENTE da fonte"}}},
                "descricao": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}},
                "comentario_fixado": {"type": "string"},
                "tiktok_titulo": {"type": "string"}, "tiktok_legenda": {"type": "string"}}}}},
}


def _palavras(t: str) -> int:
    return len(t.split())


def dividir_longas(cenas: list[dict], limite: int = 14) -> list[dict]:
    """Frase de ligação (gancho, recap, suspense, CTA) longa vira 2 cenas, cortada na vírgula ou no conectivo mais
    perto do meio, com a mesma imagem. Uma frase de 18 palavras derrubou o corte da série do José 3 vezes (25/09)."""
    import re
    saida = []
    for c in cenas:
        palavras = c["fala"].split()
        if len(palavras) <= limite:
            saida.append(c)
            continue
        meio, melhor = len(palavras) / 2, None
        for i in range(3, len(palavras) - 2):  # corta ANTES da palavra i
            antes, depois = palavras[i - 1], palavras[i].lower()
            if antes.endswith((",", ".", ":", "?", "!")) or depois in ("e", "mas", "porque", "só"):
                if melhor is None or abs(i - meio) < abs(melhor - meio):
                    melhor = i
        if melhor is None:
            saida.append(c)
            continue
        a, b = " ".join(palavras[:melhor]), " ".join(palavras[melhor:])
        if a.endswith(","):  # corte na vírgula: a frase continua na cena seguinte, a voz só respira
            saida += [{**c, "fala": a}, {**c, "fala": b}]
            continue
        a = a.rstrip(":") if a.endswith((".", "?", "!")) else a.rstrip(":") + "."
        saida += [{**c, "fala": a}, {**c, "fala": b[0].upper() + b[1:]}]
    return saida


def faixas(cenas: list[dict], n: int) -> list[tuple[int, int]]:
    """Onde cortar, decidido pelo CÓDIGO (1-based, inclusivo): n episódios com a narração mais equilibrada possível,
    preferindo cortar onde o evento muda. O modelo não conta palavras: deixado com ele, o corte do José errou o
    tamanho em 7 de 8 tentativas (25/09)."""
    w = [_palavras(c["fala"]) for c in cenas]
    M, alvo = len(w), sum(w) / n
    pref = [0] + [sum(w[:i + 1]) for i in range(M)]
    INF = float("inf")
    # custo[k][j]: melhor custo com k episódios cobrindo as cenas 1..j; volta[k][j] = onde começou o k-ésimo
    custo = [[INF] * (M + 1) for _ in range(n + 1)]
    volta = [[0] * (M + 1) for _ in range(n + 1)]
    custo[0][0] = 0
    for k in range(1, n + 1):
        for j in range(1, M + 1):
            for i in range(k - 1, j):  # episódio k = cenas i+1..j
                if custo[k - 1][i] == INF or j - i < 3:
                    continue
                meio_evento = j < M and cenas[j - 1].get("evento") and cenas[j - 1].get("evento") == cenas[j].get("evento")
                c = custo[k - 1][i] + (pref[j] - pref[i] - alvo) ** 2 + (400 if meio_evento else 0)
                if c < custo[k][j]:
                    custo[k][j], volta[k][j] = c, i
    out, j = [], M
    for k in range(n, 0, -1):
        i = volta[k][j]
        out.append((i + 1, j))
        j = i
    return out[::-1]


def _bloco_faixas(cenas: list[dict], fx: list[tuple[int, int]]) -> str:
    return ("# Episódios (JÁ DEFINIDOS pelo código: use exatamente estas cenas em inicio/fim, "
            f"{len(fx)} episódios)\n" + "\n".join(
                f"- Episódio {k}: cenas {a} a {b} ({sum(_palavras(c['fala']) for c in cenas[a - 1:b])} palavras de narração)"
                for k, (a, b) in enumerate(fx, 1)))


def _min_eps(total: int, max_partes: int) -> int:
    """Menos episódios que isso não cabe: o corte da série do José pôs 320 palavras em 3 e estourou (25/09)."""
    import serie as ms
    return max(2, min(ms.MAX_PARTES, -(-total // MIOLO_EPISODIO[1])))  # passa do pedido se a história exigir (até 5)


def _prompt_corte(h: dict, tema: dict, max_partes: int, lo: int, hi: int, correcoes: list[str], anterior: dict | None) -> str:
    refs = {e["n"]: e["ref"] for e in h["eventos"]}
    cenas = "\n".join(f"{i}. ({_palavras(c['fala'])} palavras) [{refs.get(c['evento'], '')}] {c['fala']}"
                      for i, c in enumerate(h["cenas"], 1))
    total = sum(_palavras(c["fala"]) for c in h["cenas"])
    pers = "\n".join(f"- `{p['id']}`: {p['nome']}" for p in h["personagens"])
    partes = [
        "Uma história bíblica já aprovada foi cortada em EPISÓDIOS de Shorts/TikTok (português do Brasil). A narração "
        "NÃO muda e os cortes já estão definidos: você escreve só as frases de ligação de cada episódio.",
        f"# Tema\n{tema['titulo']}",
        f"# Fonte ({biblia.TRADUCAO}), para o versículo e para não inventar nada\n{biblia.trecho(tema['ref'])}",
        f"# História aprovada ({len(h['cenas'])} cenas, {total} palavras)\n{cenas}",
        f"# Personagens (use só estes ids)\n{pers}",
        _bloco_faixas(h["cenas"], faixas(h["cenas"], _min_eps(total, max_partes))),
        "# O que você escreve em cada episódio (CADA frase nova tem no máximo 14 palavras: conte)\n"
        "- gancho: até 8 palavras, paradoxo ou choque sobre um momento DESTE episódio; funciona pra quem não viu o anterior.\n"
        "- recap (do 2º em diante): 1 frase curta ligando ao anterior, com o nome do personagem.\n"
        "- suspense (todos menos o último): pergunta real sobre o que vem, sem contar a resposta.\n"
        "- aplicacao (só no último, depois do desfecho): 1 frase em 2ª pessoa ligada a uma dor real.\n"
        "- fechamento: " + cta.bloco("gospel", 2).split("\n", 1)[1] + " Nos episódios do meio, chame pro próximo "
        "episódio pelo número; no último, não chame parte nenhuma.\n"
        "- versiculo: um versículo das cenas DESTE episódio, copiado letra por letra da fonte.\n"
        "- Frases novas não trazem fato que não está na fonte. Nomes e papéis iguais aos da história.\n"
        "- Post: título até 50 caracteres, " + cta.REGRA_TITULO + " Descrição com o versículo entre aspas, "
        "2 frases, uma pergunta e 'Leia <livro capítulo>', 5 hashtags com #shorts, comentário fixado com pergunta "
        "pessoal; TikTok com título próprio e legenda curta com pergunta e 3 a 5 hashtags sem #shorts.",
        "# Imagens das cenas novas\n" + roteirista.regras_imagem() + " Época bíblica, sem nenhum objeto moderno.",
    ]
    if correcoes and anterior:
        partes.append("# CORRIJA o corte anterior (mantenha o que não foi apontado)\n"
                      + json.dumps(anterior, ensure_ascii=False)[:6000] + "\n\nProblemas:\n"
                      + "\n".join(f"- {c}" for c in correcoes))
    return "\n\n".join(partes)


def montar(h: dict, corte: dict, formato: dict, tema: dict) -> tuple[list[dict], list[str]]:
    """Episódios no formato do roteirista (cenas, eventos, personagens, versículo, post) + os erros de código."""
    M, erros, eps = len(h["cenas"]), [], []
    partes = corte["partes"]
    esperado = 1
    for x in partes:
        if x["inicio"] != esperado or x["fim"] < x["inicio"]:
            erros.append(f"episódio {x['n']}: começa na cena {x['inicio']}, devia começar na {esperado} (sem buraco nem repetição)")
        esperado = x["fim"] + 1
    if esperado != M + 1:
        erros.append(f"o último episódio termina na cena {esperado - 1}, mas a história tem {M} cenas")
    if not 2 <= len(partes):
        raise SerieInviavel("o corte deu 1 episódio só")
    if erros:
        return [], erros
    N = len(partes)
    por_n = {e["n"]: e for e in h["eventos"]}
    fichas = {p["id"]: p for p in h["personagens"]}
    for k, x in enumerate(partes, 1):
        miolo = [dict(c) for c in h["cenas"][x["inicio"] - 1:x["fim"]]]
        novas = lambda c: {**c, "evento": 0}  # noqa: E731 - gancho, ligação e fechamento ficam fora da linha do tempo
        cenas = [novas(x["gancho"])] + ([novas(x["recap"])] if k > 1 and x["recap"]["fala"].strip() else []) + miolo
        cenas += [novas(x["suspense"])] if k < N and x["suspense"]["fala"].strip() else []
        cenas += [novas(x["aplicacao"])] if k == N and x["aplicacao"]["fala"].strip() else []
        cenas += [novas(c) for c in x["fechamento"]]
        cenas = _dividir_novas(cenas, miolo, len(x["fechamento"]))
        usados = sorted({c["evento"] for c in miolo if c["evento"]})
        eventos = [por_n[n] for n in usados if n in por_n]
        ids = list(dict.fromkeys(pid for c in cenas for pid in c["personagens"]))
        r = {**h, "cenas": cenas, "eventos": eventos, "versiculo": x["versiculo"],
             "personagens": [fichas[i] for i in ids if i in fichas],
             "titulo": x["titulo"], "gancho_tela": x["gancho_tela"], "descricao": x["descricao"], "hashtags": x["hashtags"],
             "comentario_fixado": x["comentario_fixado"], "tiktok_titulo": x["tiktok_titulo"],
             "tiktok_legenda": x["tiktok_legenda"]}
        trecho = "; ".join(dict.fromkeys(e["ref"] for e in eventos if e["ref"].strip())) or tema["ref"]
        for pid in ids:
            if pid not in fichas:
                erros.append(f"episódio {k}: personagem '{pid}' não existe na história (use: {', '.join(fichas)})")
        for e in validar.camada1(r, formato, tema):
            erros.append(f"episódio {k}: {e}")
        try:
            if not {v for v, _ in biblia.versiculos(x["versiculo"]["ref"])} <= {v for v, _ in biblia.versiculos(trecho)}:
                erros.append(f"episódio {k}: o versículo {x['versiculo']['ref']} não é de uma cena deste episódio ({trecho})")
        except biblia.RefInvalida as ex:
            erros.append(f"episódio {k}: versículo inválido ({ex})")
        eps.append({"r": r, "trecho": trecho})
    return eps, erros


def encurtar_cta(c: dict, limite: int = 14) -> dict:
    """CTA longo não pode ser dividido (a última cena perdia o pedido): corta no primeiro 'e/mas/,' depois do pedido
    e fica com a parte que pede. 'Se inscreve pra ver a parte 5 e descobrir o que José fez...' (18 palavras, derrubou
    o corte do José) -> 'Se inscreve pra ver a parte 5.'"""
    import re
    palavras = c["fala"].split()
    if len(palavras) <= limite:
        return c
    pedido = re.compile(r"am[eé]m|inscrev|comenta|escreve|segue|compartilha|salva|manda", re.I)
    for i in range(3, len(palavras) - 1):
        antes, depois = palavras[i - 1], palavras[i].lower()
        if (antes.endswith(",") or depois in ("e", "mas", "porque")) and pedido.search(" ".join(palavras[:i])) \
                and not pedido.search(" ".join(palavras[i:])):
            return {**c, "fala": " ".join(palavras[:i]).rstrip(",") + "."}
    return c


def _dividir_novas(cenas: list[dict], miolo: list[dict], fechamento: int) -> list[dict]:
    """Só gancho, recap, suspense e aplicação são divididos. A narração aprovada fica como está, e o fechamento
    também: partido, a última cena perdia o CTA ('...pra não perder' + 'o que aconteceu com José')."""
    fecho = {id(c) for c in cenas[len(cenas) - fechamento:]}
    return [y for c in cenas for y in ([c] if id(c) in {id(m) for m in miolo}
                                       else [encurtar_cta(c)] if id(c) in fecho else dividir_longas([c]))]


def particionar(h: dict, formato: dict, tema: dict, max_partes: int, reg, log=print,
                correcoes: list[str] | None = None, anterior: dict | None = None) -> tuple[dict, list[dict], list[str]]:
    lo, hi = formato["palavras"]
    ultimo = []
    for tentativa in range(1, TENTATIVAS_CORTE + 1):
        log(f"corte em episódios: tentativa {tentativa}")
        with medidor.etapa("serie_corte"):
            corte = llm.chamar(_prompt_corte(h, tema, max_partes, lo, hi, correcoes or [], anterior), SCHEMA_CORTE,
                               papel="roteirista", modelo=caminhos.MODELO_CORTE)
        fx = faixas(h["cenas"], _min_eps(sum(_palavras(c["fala"]) for c in h["cenas"]), max_partes))
        if len(corte["partes"]) != len(fx):
            eps, erros = [], [f"devolva exatamente {len(fx)} episódios (veio {len(corte['partes'])})"]
        else:
            for k, (x, (a, b)) in enumerate(zip(corte["partes"], fx), 1):  # os cortes são os do código, sempre
                x["n"], x["inicio"], x["fim"] = k, a, b
            eps, erros = montar(h, corte, formato, tema)
        reg.add("corte", not erros, tentativa=tentativa, problemas=erros,
                partes=[[x["inicio"], x["fim"]] for x in corte["partes"]])
        if not erros:
            log(f"  corte ok: {len(eps)} episódios, cenas " + " | ".join(f"{x['inicio']}-{x['fim']}" for x in corte["partes"]))
            return corte, eps, []
        log("  corte reprovado: " + " | ".join(erros[:4]))
        ultimo, correcoes, anterior = erros, erros, corte
    if ultimo and all("palavras" in e or "cenas; o formato" in e for e in ultimo) and eps \
            and all(sum(_palavras(c["fala"]) for c in e["r"]["cenas"]) <= TETO_PALAVRAS_EPISODIO for e in eps):
        return corte, eps, [f"corte: {e}" for e in ultimo]  # só tamanho: segue com aviso (como o juiz do CEO)
    raise RuntimeError(f"o corte em episódios não passou em {TENTATIVAS_CORTE} tentativas: " + " | ".join(ultimo[:3]))


# ---------------------------------------------------------------- 3. tudo junto

def serie_biblica(formato_id: str, formato: dict, tema: dict, max_partes: int, slug_serie: str, log=print):
    """-> (plano para o painel, [(arquivo, pacote), ...]). O juiz da série faz 1 passada só nas frases novas."""
    import pipeline
    import serie as ms

    f_ep = dict(formato)
    # teto do episódio = o que cabe em ~56 s (a camada 1 soma +15% em cima do nominal)
    f_ep["palavras"] = [formato["palavras"][0], int(TETO_PALAVRAS_EPISODIO / (1 + validar.MARGEM_PALAVRAS))]
    f_ep["cenas"] = [7, 18]
    reg = pipeline.Registro(slug_serie)
    # história aprovada fica guardada: se o corte ou as imagens falharem, a próxima rodada começa do corte
    cache = pipeline.PROD / "roteiros" / f"{date.today():%Y-%m-%d}_{slug_serie}-historia.json"
    if cache.exists() and json.loads(cache.read_text(encoding="utf-8")).get("_ref") == tema["ref"]:
        h = json.loads(cache.read_text(encoding="utf-8"))
        log(f"história completa: reaproveitando a aprovada hoje ({cache.name})")
    else:
        h = historia(formato, tema, max(2, min(ms.MAX_PARTES, max_partes)), reg, log)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({**h, "_ref": tema["ref"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    if sum(_palavras(c["fala"]) for c in h["cenas"]) < MIOLO_EPISODIO[0] * 2:
        raise SerieInviavel("a história completa é curta demais para 2 episódios: gere como vídeo único")
    corte, eps, avisos = particionar(h, f_ep, tema, max_partes, reg, log)
    plano = {"titulo_serie": corte["titulo_serie"], "arco": corte["arco"], "personagens": h["personagens"],
             "partes": [{"n": x["n"], "titulo": x["titulo"], "trecho": e["trecho"], "resumo": x["resumo"],
                         "virada": x["virada"], "gancho_final": x["suspense"]["fala"], "versiculo": x["versiculo"]["ref"]}
                        for x, e in zip(corte["partes"], eps)]}
    log("juiz da série: lendo os episódios juntos (só as frases de ligação são novas)")
    vistos = [{"falas": [c["fala"] for c in e["r"]["cenas"]], "personagens": e["r"]["personagens"]} for e in eps]
    problemas = ms.julgar_roteiros(plano, vistos, "gospel", tema["ref"])
    if problemas:
        log("  juiz da série: " + " | ".join(f"ep. {k}: {p[0]}" for k, p in problemas.items()) + " -> refaz o corte uma vez")
        corte2, eps2, avisos2 = particionar(h, f_ep, tema, max_partes, reg, log,
                                            [f"episódio {k}: {p}" for k, ps in problemas.items() for p in ps], corte)
        vistos = [{"falas": [c["fala"] for c in e["r"]["cenas"]], "personagens": e["r"]["personagens"]} for e in eps2]
        plano2 = {**plano, "titulo_serie": corte2["titulo_serie"], "arco": corte2["arco"]}
        resto = ms.julgar_roteiros(plano2, vistos, "gospel", tema["ref"])
        corte, eps, avisos = corte2, eps2, avisos2 + [f"juiz da série, ep. {k}: {p}" for k, ps in resto.items() for p in ps]
        plano = {**plano2, "partes": [{"n": x["n"], "titulo": x["titulo"], "trecho": e["trecho"], "resumo": x["resumo"],
                                       "virada": x["virada"], "gancho_final": x["suspense"]["fala"],
                                       "versiculo": x["versiculo"]["ref"]} for x, e in zip(corte["partes"], eps)]}
    else:
        log("  juiz da série: aprovada")
    N, saida = len(eps), []
    for k, e in enumerate(eps, 1):
        r = e["r"]
        r["_avisos_juiz"] = list(h.get("_avisos_juiz", [])) + avisos
        slug = f"{slug_serie}-p{k}"
        tema_p = {**tema, "id": f"{tema['id']}-p{k}", "ref": e["trecho"]}
        pacote = pipeline.empacotar(r, formato_id, formato, tema_p, formato["estilo"], slug)
        pacote["titulo"] = ms.titulo_parte(pacote["titulo"], k, N)
        if pacote.get("tiktok_titulo"):
            pacote["tiktok_titulo"] = ms.titulo_parte(pacote["tiktok_titulo"], k, N)
        pacote["serie"] = {"slug": slug_serie, "titulo": plano["titulo_serie"], "parte": k, "total": N}
        pipeline.salvar_fichas(pacote)
        arq = pipeline.PROD / "roteiros" / f"{date.today():%Y-%m-%d}_{slug}.json"
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps([pacote], ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"episódio {k}/{N} ({sum(_palavras(c['fala']) for c in r['cenas'])} palavras):\n"
            + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]))
        saida.append((arq, pacote))
    return plano, saida


# ---------------------------------------------------------------- outros nichos (roteirista genérico do painel)

_CENA_SIMPLES = {"type": "object", "additionalProperties": False, "required": ["fala", "busca", "imagem"],
                 "properties": {"fala": {"type": "string"}, "busca": {"type": "string"}, "imagem": {"type": "string"}}}
SCHEMA_CORTE_SIMPLES = {
    "type": "object", "additionalProperties": False, "required": ["titulo_serie", "arco", "partes"],
    "properties": {
        "titulo_serie": {"type": "string"}, "arco": {"type": "string"},
        "partes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["titulo", "inicio", "fim", "resumo", "virada", "gancho", "recap", "suspense", "fechamento",
                         "descricao", "hashtags", "comentario_fixado", "tiktok_titulo", "tiktok_legenda"],
            "properties": {
                "titulo": {"type": "string", "description": "até 50 caracteres (o '(Parte k/N)' entra sozinho): " + cta.REGRA_TITULO},
                "inicio": {"type": "integer"}, "fim": {"type": "integer"},
                "resumo": {"type": "string"}, "virada": {"type": "string"},
                "gancho": {**_CENA_SIMPLES, "description": "até 8 palavras, sobre um momento DESTE episódio"},
                "recap": {**_CENA_SIMPLES, "description": "do 2º episódio em diante, 1 frase curta; fala vazia no 1º"},
                "suspense": {**_CENA_SIMPLES, "description": "pergunta em aberto sobre o próximo; fala vazia no último"},
                "fechamento": {"type": "array", "minItems": 1, "maxItems": 2, "items": _CENA_SIMPLES},
                "descricao": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}},
                "comentario_fixado": {"type": "string"}, "tiktok_titulo": {"type": "string"},
                "tiktok_legenda": {"type": "string"}}}}},
}


def serie_generica(nicho: str, formato_nome: str, tema: str, max_partes: int, log=print) -> tuple[dict, list[dict]]:
    """-> (plano, [roteiro no formato do _roteiro_generico, um por episódio]). Mesmo desenho da bíblica, sem fonte."""
    import caminhos
    import guia
    import serie as ms
    import servico_pipeline as sp

    preset = sp._preset(nicho)
    max_partes = max(2, min(ms.MAX_PARTES, max_partes))
    refs = caminhos.DADOS / "referencias"
    ler = lambda n: (refs / n).read_text(encoding="utf-8") if (refs / n).exists() else ""  # noqa: E731
    lo_h, hi_h = MIOLO_EPISODIO[0] * 2, MIOLO_EPISODIO[1] * max_partes
    base = "\n\n".join(p for p in [
        "Você é roteirista de Shorts/TikTok em português do Brasil. Escreva a HISTÓRIA COMPLETA abaixo, dividida em "
        "cenas. Ela vai ser cortada depois em episódios de ~40 s.",
        f"# Nicho: {nicho} · formato: {formato_nome}\n# Tema: {tema}",
        f"# Tamanho\n{lo_h} a {hi_h} palavras, uma frase por cena (3 a 14 palavras). NÃO escreva gancho nem chamada "
        "final: só a narração, do começo ao fim, com viradas claras (onde dá pra cortar deixando suspense).",
        "# Fatos\nO fato central tem que ser verdadeiro. O resto pode ser dramatização em tom de hipótese ('imagina', 'provavelmente').",
        guia.bloco(nicho, formato_nome, tema), f"# Linguagem\n{ler('anti-ia.md')}",
        "# Post\nPreencha título, descrição e hashtags para a série inteira (cada episódio ganha os seus depois).",
    ] if p)
    comeco, correcoes, melhor = time.time(), [], None
    for tentativa in range(1, TENTATIVAS_HISTORIA + 1):
        if melhor and time.time() - comeco > TEMPO_MAX_HISTORIA:
            break
        log(f"história completa: tentativa {tentativa}")
        prompt = base + ("\n\n# REESCREVA corrigindo:\n" + "\n".join(f"- {c}" for c in correcoes) + "\n\nVersão anterior:\n"
                         + json.dumps([c["fala"] for c in melhor[0]["cenas"]], ensure_ascii=False) if correcoes and melhor else "")
        with medidor.etapa("serie_historia"):
            h = llm.chamar(prompt, sp.SCHEMA_SIMPLES, papel="roteirista")
        total = sum(_palavras(c["fala"]) for c in h["cenas"])
        erros = [e for e in guia.checar(h["cenas"], {"palavras_min": lo_h, "palavras_max": hi_h})
                 if not e.startswith(("gancho com", "a última cena não é", ))
                 and "cenas; use de" not in e]
        if not erros:
            with medidor.etapa("juiz"):
                probs, notas = sp._juiz(h, {"nicho": nicho, "serie": "HISTÓRIA COMPLETA de uma série: ainda sem gancho "
                                            "nem chamada (vêm no corte). Avalie fatos e clareza."}, tema)
            # gancho/payoff/CTA são do episódio: na história só o fato errado e a clareza reprovam
            erros = [p for p in probs if p.startswith("ERRO FACTUAL")] + \
                    ([f"clareza (nota {notas['clareza']})"] if notas.get("clareza", 5) < 3 else [])
            log(f"  {total} palavras, notas do juiz: {notas}")
        else:
            log(f"  camada 1 reprovou ({total} palavras): " + " | ".join(erros[:3]))
        if melhor is None or len(erros) <= len(melhor[1]):
            melhor = (h, erros)
        if not erros:
            break
        correcoes = erros
    h, erros_h = melhor
    if any(e.startswith("ERRO FACTUAL") for e in erros_h):
        raise RuntimeError("a história completa ficou com erro de fato: " + " | ".join(erros_h[:2]))
    if sum(_palavras(c["fala"]) for c in h["cenas"]) < MIOLO_EPISODIO[0] * 2:
        raise SerieInviavel("a história é curta demais para 2 episódios: gere como vídeo único")

    preset_ep = {"palavras_min": preset["palavras_min"], "palavras_max": int(TETO_PALAVRAS_EPISODIO / 1.15)}  # guia.checar: +15%
    M, total_h = len(h["cenas"]), sum(_palavras(c["fala"]) for c in h["cenas"])
    fx = faixas(h["cenas"], _min_eps(total_h, max_partes))
    cenas_txt = "\n".join(f"{i}. ({_palavras(c['fala'])} palavras) {c['fala']}" for i, c in enumerate(h["cenas"], 1))

    def cortar(problemas: list[str], anterior: dict | None) -> tuple[dict, list[dict], list[str]]:
        erros = []
        for tentativa in range(1, TENTATIVAS_CORTE + 1):
            log(f"corte em episódios: tentativa {tentativa}")
            prompt = "\n\n".join([
                "Uma história já aprovada foi cortada em EPISÓDIOS de Shorts/TikTok (pt-BR). A narração NÃO muda e os "
                "cortes já estão definidos: você escreve só as frases de ligação.",
                f"# Nicho: {nicho} · Tema: {tema}\n# História ({M} cenas)\n{cenas_txt}",
                _bloco_faixas(h["cenas"], fx),
                "# Frases novas (CADA uma com no máximo 14 palavras: conte)\n- gancho: até 8 palavras.\n- recap (do 2º em diante): 1 frase curta.\n- suspense (menos "
                "o último): pergunta real sobre o que vem.\n- fechamento: " + cta.bloco(nicho, 2).split("\n", 1)[1]
                + " Nos do meio, chame pro próximo episódio pelo número; no último, não chame parte nenhuma."
                + (f" A chamada também pede pra se inscrever no canal {preset['inscreva_canal']}." if preset.get("inscreva_canal") else ""),
                "# Busca e imagem das cenas novas\n" + sp.SCHEMA_SIMPLES["properties"]["cenas"]["items"]["properties"]["busca"]["description"],
            ] + ([f"# CORRIJA o corte anterior\n{json.dumps(anterior, ensure_ascii=False)[:5000]}\nProblemas:\n"
                  + "\n".join(f"- {p}" for p in problemas)] if problemas and anterior else []))
            with medidor.etapa("serie_corte"):
                corte = llm.chamar(prompt, SCHEMA_CORTE_SIMPLES, papel="roteirista", modelo=caminhos.MODELO_CORTE)
            erros, eps, esperado = [], [], 1
            N = len(corte["partes"])
            if N != len(fx):
                log(f"  corte reprovado: veio {N} episódios, eram {len(fx)}")
                problemas, anterior = [f"devolva exatamente {len(fx)} episódios"], corte
                continue
            for x, (a, b) in zip(corte["partes"], fx):  # os cortes são os do código, sempre
                x["inicio"], x["fim"] = a, b
            for k, x in enumerate(corte["partes"], 1):
                if x["inicio"] != esperado or x["fim"] < x["inicio"]:
                    erros.append(f"episódio {k}: começa na cena {x['inicio']}, devia começar na {esperado}")
                esperado = x["fim"] + 1
                miolo = [dict(c) for c in h["cenas"][x["inicio"] - 1:x["fim"]]]
                cenas = [x["gancho"]] + ([x["recap"]] if k > 1 and x["recap"]["fala"].strip() else []) + miolo
                cenas += ([x["suspense"]] if k < N and x["suspense"]["fala"].strip() else []) + list(x["fechamento"])
                cenas = _dividir_novas(cenas, miolo, len(x["fechamento"]))
                ep_erros = guia.checar(cenas, preset_ep)
                if nicho == "gospel":
                    ep_erros += validar.checar_cta_gospel(cenas)
                erros += [f"episódio {k}: {e}" for e in ep_erros if "cenas; use de" not in e]
                eps.append({"titulo": ms.titulo_parte(x["titulo"], k, N), "cenas": cenas, "descricao": x["descricao"],
                            "hashtags": x["hashtags"], "comentario_fixado": x["comentario_fixado"],
                            "tiktok_titulo": ms.titulo_parte(x["tiktok_titulo"], k, N) if x["tiktok_titulo"] else "",
                            "tiktok_legenda": x["tiktok_legenda"]})
            if esperado != M + 1:
                erros.append(f"o último episódio termina na cena {esperado - 1}, mas a história tem {M}")
            if not erros:
                log(f"  corte ok: {N} episódios")
                return corte, eps, []
            log("  corte reprovado: " + " | ".join(erros[:4]))
            problemas, anterior = erros, corte
        if all("palavras" in e for e in erros) and eps \
                and all(sum(_palavras(c["fala"]) for c in e["cenas"]) <= TETO_PALAVRAS_EPISODIO for e in eps):
            return corte, eps, [f"corte: {e}" for e in erros]
        raise RuntimeError(f"o corte em episódios não passou em {TENTATIVAS_CORTE} tentativas: " + " | ".join(erros[:3]))

    def plano_de(corte: dict) -> dict:
        return {"titulo_serie": corte["titulo_serie"], "arco": corte["arco"], "personagens": [],
                "partes": [{"n": k, "titulo": x["titulo"], "trecho": "", "resumo": x["resumo"], "virada": x["virada"],
                            "gancho_final": x["suspense"]["fala"], "versiculo": ""}
                           for k, x in enumerate(corte["partes"], 1)]}

    corte, eps, avisos = cortar([], None)
    log("juiz da série: lendo os episódios juntos")
    problemas = ms.julgar_roteiros(plano_de(corte), [{"falas": [c["fala"] for c in e["cenas"]]} for e in eps], nicho)
    if problemas:
        log("  juiz da série: " + " | ".join(f"ep. {k}: {p[0]}" for k, p in problemas.items()) + " -> refaz o corte uma vez")
        corte, eps, avisos = cortar([f"episódio {k}: {p}" for k, ps in problemas.items() for p in ps], corte)
        resto = ms.julgar_roteiros(plano_de(corte), [{"falas": [c["fala"] for c in e["cenas"]]} for e in eps], nicho)
        avisos += [f"juiz da série, ep. {k}: {p}" for k, ps in resto.items() for p in ps]
    else:
        log("  juiz da série: aprovada")
    avisos = erros_h + avisos
    for e in eps:
        e["_avisos"] = list(avisos)
    return plano_de(corte), eps
