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
import cta  # noqa: E402
import llm  # noqa: E402
import medidor  # noqa: E402
import roteirista  # noqa: E402
import validar  # noqa: E402
from serie import SerieInviavel  # noqa: E402  (o painel transforma em vídeo único)

TENTATIVAS_HISTORIA = 3
TENTATIVAS_CORTE = 3
TEMPO_MAX_HISTORIA = 480  # como o teto do juiz do CEO: passou, segue a melhor versão sem erro de fato, com avisos
MIOLO_EPISODIO = (45, 80)  # palavras da narração que cabem num episódio além do gancho, recapitulação e fechamento
RECEITA_HISTORIA = (
    "Conte o episódio bíblico INTEIRO como uma história falada, do primeiro ao último fato do trecho, na ORDEM do texto. "
    "Frases ligadas com conectivos (e, mas, então, só que), como alguém contando em voz alta; nada de lista de frases "
    "soltas. Cada virada (traição, prisão, reviravolta) fica clara numa frase própria: é onde a série vai ser cortada. "
    "Inclua um detalhe exato do texto que pouca gente nota. Termine no desfecho da história, sem sermão.")


# ---------------------------------------------------------------- 1. a história completa

def _formato_historia(formato: dict, max_partes: int) -> dict:
    f = {**formato, "completa": True, "receita": RECEITA_HISTORIA}
    f["palavras"] = [MIOLO_EPISODIO[0] * 2, MIOLO_EPISODIO[1] * max_partes]
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
        if melhor and _sem_erro_de_fato(melhor[2]) and time.time() - comeco > TEMPO_MAX_HISTORIA:
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
    if melhor and _sem_erro_de_fato(melhor[2]):
        log(f"  segue a melhor versão da história, com {len(melhor[2])} aviso(s) para a revisão")
        melhor[1]["_notas_juiz"], melhor[1]["_avisos_juiz"] = melhor[3], [f"juiz: {p}" for p in melhor[2]]
        return melhor[1]
    raise RuntimeError(f"a história completa não passou em {TENTATIVAS_HISTORIA} tentativas (veja {reg.arq})")


def _sem_erro_de_fato(problemas: list[str]) -> bool:
    return not any(p.startswith("ERRO FACTUAL") or p.startswith("fidelidade") for p in problemas)


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
                "titulo": {"type": "string", "description": "título do post, até 50 caracteres (o '(Parte k/N)' entra sozinho)"},
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


def _prompt_corte(h: dict, tema: dict, max_partes: int, lo: int, hi: int, correcoes: list[str], anterior: dict | None) -> str:
    refs = {e["n"]: e["ref"] for e in h["eventos"]}
    cenas = "\n".join(f"{i}. ({_palavras(c['fala'])} palavras) [{refs.get(c['evento'], '')}] {c['fala']}"
                      for i, c in enumerate(h["cenas"], 1))
    total = sum(_palavras(c["fala"]) for c in h["cenas"])
    pers = "\n".join(f"- `{p['id']}`: {p['nome']}" for p in h["personagens"])
    partes = [
        "Você corta uma história bíblica já aprovada em EPISÓDIOS de Shorts/TikTok (português do Brasil). A narração "
        "abaixo NÃO muda: você escolhe onde cortar e escreve só as frases de ligação de cada episódio.",
        f"# Tema\n{tema['titulo']}",
        f"# Fonte ({biblia.TRADUCAO}), para o versículo e para não inventar nada\n{biblia.trecho(tema['ref'])}",
        f"# História aprovada ({len(h['cenas'])} cenas, {total} palavras)\n{cenas}",
        f"# Personagens (use só estes ids)\n{pers}",
        "# Como cortar\n"
        f"- 2 a {max_partes} episódios, em sequência: o 1º começa na cena 1, cada um começa na cena seguinte ao fim do "
        f"anterior, e o último termina na cena {len(h['cenas'])}. Nenhuma cena fica de fora nem se repete.\n"
        f"- Cada episódio: {MIOLO_EPISODIO[0]} a {MIOLO_EPISODIO[1]} palavras de narração (some a contagem das cenas "
        f"acima) e, com gancho, recapitulação, suspense e fechamento, {lo} a {hi} palavras NO TOTAL.\n"
        "- Corte logo depois de uma virada (traição, prisão, reviravolta): o episódio termina com tensão e cada um "
        "tem uma virada própria. Melhor menos episódios fortes que muitos com enchimento.",
        "# O que você escreve em cada episódio\n"
        "- gancho: até 8 palavras, paradoxo ou choque sobre um momento DESTE episódio; funciona pra quem não viu o anterior.\n"
        "- recap (do 2º em diante): 1 frase curta ligando ao anterior, com o nome do personagem.\n"
        "- suspense (todos menos o último): pergunta real sobre o que vem, sem contar a resposta.\n"
        "- aplicacao (só no último, depois do desfecho): 1 frase em 2ª pessoa ligada a uma dor real.\n"
        "- fechamento: " + cta.bloco("gospel", 2).split("\n", 1)[1] + " Nos episódios do meio, chame pro próximo "
        "episódio pelo número; no último, não chame parte nenhuma.\n"
        "- versiculo: um versículo das cenas DESTE episódio, copiado letra por letra da fonte.\n"
        "- Frases novas não trazem fato que não está na fonte. Nomes e papéis iguais aos da história.\n"
        "- Post: título até 50 caracteres (curiosidade, não repita o gancho), descrição com o versículo entre aspas, "
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


def particionar(h: dict, formato: dict, tema: dict, max_partes: int, reg, log=print,
                correcoes: list[str] | None = None, anterior: dict | None = None) -> tuple[dict, list[dict], list[str]]:
    lo, hi = formato["palavras"]
    ultimo = []
    for tentativa in range(1, TENTATIVAS_CORTE + 1):
        log(f"corte em episódios: tentativa {tentativa}")
        with medidor.etapa("serie_corte"):
            corte = llm.chamar(_prompt_corte(h, tema, max_partes, lo, hi, correcoes or [], anterior), SCHEMA_CORTE,
                               papel="roteirista")
        for x in corte["partes"]:  # o miolo é o da história; o que vale para as palavras é o episódio montado
            x["n"] = corte["partes"].index(x) + 1
        eps, erros = montar(h, corte, formato, tema)
        reg.add("corte", not erros, tentativa=tentativa, problemas=erros,
                partes=[[x["inicio"], x["fim"]] for x in corte["partes"]])
        if not erros:
            log(f"  corte ok: {len(eps)} episódios, cenas " + " | ".join(f"{x['inicio']}-{x['fim']}" for x in corte["partes"]))
            return corte, eps, []
        log("  corte reprovado: " + " | ".join(erros[:4]))
        ultimo, correcoes, anterior = erros, erros, corte
    if ultimo and all("palavras" in e or "cenas; o formato" in e for e in ultimo) and eps:
        return corte, eps, [f"corte: {e}" for e in ultimo]  # só tamanho: segue com aviso (como o juiz do CEO)
    raise RuntimeError(f"o corte em episódios não passou em {TENTATIVAS_CORTE} tentativas: " + " | ".join(ultimo[:3]))


# ---------------------------------------------------------------- 3. tudo junto

def serie_biblica(formato_id: str, formato: dict, tema: dict, max_partes: int, slug_serie: str, log=print):
    """-> (plano para o painel, [(arquivo, pacote), ...]). O juiz da série faz 1 passada só nas frases novas."""
    import pipeline
    import serie as ms

    f_ep = dict(formato)
    f_ep["palavras"] = [formato["palavras"][0], formato["palavras"][1] + ms.FOLGA_PARTE_RECAP]
    f_ep["cenas"] = [7, 18]
    reg = pipeline.Registro(slug_serie)
    h = historia(formato, tema, max(2, min(ms.MAX_PARTES, max_partes)), reg, log)
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
