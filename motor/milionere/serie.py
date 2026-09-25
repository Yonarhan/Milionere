"""Séries: uma história em 2 a 5 partes, com o arco planejado ANTES e juízes que olham a série inteira.

    planejar(...)         -> plano validado: quantas partes, o que cada uma conta, o gancho que deixa, personagens fixos
    contexto_parte(...)   -> bloco que entra no prompt do roteirista de cada parte
    julgar_roteiros(...)  -> {parte: [problemas]}: continuidade, repetição, nomes/papéis, ganchos que ligam
    julgar_visual(...)    -> avisos: o mesmo personagem com a mesma cara em todas as partes
    roteiro_gospel(...)   -> uma parte pelo pipeline bíblico (camadas 1 e 2), empacotada e salva

Cada parte continua passando pelos juízes de sempre; os daqui só olham o que um vídeo sozinho não mostra.
Quem orquestra (e decide o que fazer com as reprovações) é o painel: servico/estudio/producao.py.
"""

import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import caminhos  # noqa: E402
import cta  # noqa: E402
import llm  # noqa: E402
import medidor  # noqa: E402

MAX_PARTES = 5
TENTATIVAS_PLANO = 4
RODADAS_SERIE = 2  # rodadas do juiz da série (cada uma reescreve só as partes apontadas)
# trecho de uma parte: com 13 versículos de ação (Gênesis 37:3-4; 37:18-28) o roteirista escrevia 150-230 palavras
# para um limite de ~120 e a série do José caía nas 4 tentativas (25/09)
MAX_VERSICULOS_PARTE = 11  # 10 + a margem de 10% (validar.MARGEM)
FOLGA_PARTE, FOLGA_PARTE_RECAP = 10, 16  # palavras a mais que o formato de vídeo único (parte 1 / partes seguintes)

# os mais lidos/compartilhados (YouVersion e buscas em pt-BR): se cair no trecho, vira o versículo de uma parte
VERSICULOS_FAMOSOS = [
    "João 3:16", "Jeremias 29:11", "Filipenses 4:13", "Romanos 8:28", "Isaías 41:10", "Josué 1:9", "Salmos 23:1",
    "Salmos 23:4", "Provérbios 3:5", "Provérbios 3:6", "Mateus 11:28", "Filipenses 4:6", "Filipenses 4:7",
    "Isaías 40:31", "Salmos 46:1", "Salmos 46:10", "Mateus 6:33", "Mateus 6:34", "2 Timóteo 1:7", "Salmos 91:1",
    "Salmos 91:11", "Romanos 12:2", "Romanos 8:38", "Romanos 8:39", "Gênesis 50:20", "1 Samuel 17:47", "Rute 1:16",
    "Daniel 6:22", "Salmos 37:5", "Lamentações 3:22", "Lamentações 3:23", "Hebreus 11:1", "1 Coríntios 13:4",
    "João 14:6", "João 16:33", "Mateus 5:14", "Salmos 121:1", "Salmos 121:2", "Josué 24:15", "João 21:17",
]


class SerieInviavel(Exception):
    """O tema não rende mais de uma parte sem enrolar: gere como vídeo único."""


# ---------------------------------------------------------------- plano

SCHEMA_PLANO = {
    "type": "object", "additionalProperties": False,
    "required": ["titulo_serie", "arco", "partes_possiveis", "personagens", "partes"],
    "properties": {
        "titulo_serie": {"type": "string", "description": "nome da série, até 45 caracteres"},
        "arco": {"type": "string", "description": "em 1-2 frases: o começo, a virada e o fim da história inteira"},
        "partes_possiveis": {"type": "integer", "description": "quantas partes a história aguenta SEM enrolar (pode ser 1)"},
        "personagens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "nome", "nome_en", "descricao_visual"],
            "properties": {"id": {"type": "string"}, "nome": {"type": "string"}, "nome_en": {"type": "string"},
                           "descricao_visual": {"type": "string", "description": "em inglês: idade, cabelo, barba, pele, roupa. Fixa na série inteira."}}}},
        "partes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["n", "titulo", "trecho", "resumo", "virada", "gancho_final", "versiculo"],
            "properties": {
                "n": {"type": "integer"},
                "titulo": {"type": "string", "description": "título curto desta parte"},
                "trecho": {"type": "string", "description": f"história bíblica: SÓ os versículos desta parte (ex.: 'Gênesis 37:3-4; 37:23-28'), no máximo {MAX_VERSICULOS_PARTE} versículos (cabe em ~45 s de fala), dentro da fonte, na ordem, sem repetir versículo de outra parte. Pode deixar versículos da fonte de fora. Outros nichos: vazio"},
                "resumo": {"type": "string", "description": "o que esta parte conta, em 1-2 frases"},
                "virada": {"type": "string", "description": "o momento forte que faz esta parte valer sozinha"},
                "gancho_final": {"type": "string", "description": "a pergunta em aberto que empurra pra próxima parte; vazio na última"},
                "versiculo": {"type": "string", "description": "referência do versículo-chave desta parte (dentro do trecho); vazio fora do gospel"}}}},
    },
}
SCHEMA_VEREDITO = {
    "type": "object", "additionalProperties": False, "required": ["aprovado", "problemas"],
    "properties": {"aprovado": {"type": "boolean"},
                   "problemas": {"type": "array", "items": {"type": "string"},
                                 "description": "cada um com a parte e como corrigir, em 1 frase; no máximo 5"}},
}


def famosos_no_trecho(ref: str) -> list[str]:
    try:
        rots = {rot for rot, _ in biblia.versiculos(ref)}
    except biblia.RefInvalida:
        return []
    return [v for v in VERSICULOS_FAMOSOS if v in rots]


def checar_plano(p: dict, max_partes: int, fonte_ref: str | None) -> list[str]:
    """Camada de código do plano. Levanta SerieInviavel se o tema só rende 1 parte."""
    partes = p["partes"]
    if len(partes) < 2 or p["partes_possiveis"] < 2:
        raise SerieInviavel(f"o tema só rende {max(1, min(len(partes), p['partes_possiveis']))} parte: gere como vídeo único")
    erros = []
    if len(partes) > max_partes:
        erros.append(f"o plano tem {len(partes)} partes; o máximo pedido é {max_partes}: junte partes")
    if [x["n"] for x in partes] != list(range(1, len(partes) + 1)):
        erros.append("numere as partes de 1 em diante, na ordem")
    for x in partes[:-1]:
        if not x["gancho_final"].strip():
            erros.append(f"parte {x['n']} sem gancho_final: toda parte, menos a última, termina em aberto")
    ids = [c["id"] for c in p["personagens"]]
    if len(ids) != len(set(ids)):
        erros.append(f"personagem repetido: {ids}")
    if fonte_ref:
        import validar
        fonte = {rot for rot, _ in biblia.versiculos(fonte_ref)}
        vistos, ultimo = set(), None
        for x in partes:
            try:
                rots = [rot for rot, _ in biblia.versiculos(x["trecho"])]
            except biblia.RefInvalida as e:
                erros.append(f"parte {x['n']}: trecho inválido ({e})")
                continue
            if not set(rots) <= fonte:
                erros.append(f"parte {x['n']}: o trecho {x['trecho']} sai da fonte ({fonte_ref})")
            if vistos & set(rots):
                erros.append(f"parte {x['n']}: repete versículos de outra parte ({sorted(vistos & set(rots))[:3]})")
            if ultimo and validar._pos(rots[0]) < ultimo:
                erros.append(f"parte {x['n']}: começa antes, no texto, do fim da parte anterior (fora de ordem)")
            vistos |= set(rots)
            ultimo = validar._pos(rots[-1])
            if len(rots) > MAX_VERSICULOS_PARTE:
                erros.append(f"parte {x['n']}: {len(rots)} versículos não cabem em ~45 s (máx. {MAX_VERSICULOS_PARTE}); "
                             "fique só com os versículos dos momentos principais (pode deixar versículos da fonte de fora)")
            if len(rots) < 2:
                erros.append(f"parte {x['n']}: 1 versículo só não sustenta um vídeo; junte com a vizinha")
            if x["versiculo"].strip():
                try:
                    if not {r for r, _ in biblia.versiculos(x["versiculo"])} <= set(rots):
                        erros.append(f"parte {x['n']}: o versículo-chave {x['versiculo']} não está no trecho dela")
                except biblia.RefInvalida:
                    erros.append(f"parte {x['n']}: versículo-chave inválido ({x['versiculo']})")
    return erros


def _fixas(p: dict, biblico: bool) -> None:
    """Personagem bíblico que já tem ficha usa SEMPRE a ficha salva (a mesma cara de todos os vídeos do canal)."""
    if not biblico:
        return
    conhecidos = biblia.personagens()
    for c in p["personagens"]:
        if c["id"] in conhecidos:
            c.update(conhecidos[c["id"]])


def planejar(nicho: str, formato: dict, tema: dict, max_partes: int, log=print) -> dict:
    """tema: {titulo, angulo, ref?, personagens?}. formato: {nome, receita, epoca?, palavras?}."""
    max_partes = max(2, min(MAX_PARTES, max_partes))
    fonte_ref = tema.get("ref") if nicho == "gospel" and formato.get("epoca") == "biblica" else None
    conhecidos = biblia.personagens() if fonte_ref else {}
    fichas = "\n".join(f"- `{k}`: {v['nome']} ({v['nome_en']}) — {v['descricao_visual']}" for k, v in conhecidos.items())
    famosos = famosos_no_trecho(fonte_ref) if fonte_ref else []
    base = "\n\n".join(x for x in [
        f"Você planeja uma SÉRIE de Shorts/TikTok em português do Brasil, nicho **{nicho}**. Cada parte é um vídeo de "
        f"30 a 45 segundos ({'/'.join(map(str, formato.get('palavras', [60, 90])))} palavras) que vai ao ar separado.",
        f"# Tema\n{tema['titulo']}\nÂngulo: {tema.get('angulo', '')}",
        f"# Formato de cada parte\n{formato['nome']}\n{formato.get('receita', '')}",
        (f"# FONTE DA VERDADE ({biblia.TRADUCAO})\n{biblia.trecho(fonte_ref)}\n\nCada parte recebe SÓ um pedaço desta fonte "
         "(campo `trecho`), em ordem, sem repetir versículo. Nada fora dela." if fonte_ref else ""),
        ("# Versículos muito lidos que estão neste trecho\n" + ", ".join(famosos) + "\nSão os que o público mais procura e "
         "compartilha: use cada um como `versiculo` de uma parte (o da parte onde ele acontece)." if famosos else ""),
        f"# Quantas partes\nNo máximo {max_partes}. Cada parte cobre no MÁXIMO {MAX_VERSICULOS_PARTE} versículos "
          "(conte; o primeiro plano sempre passava disso): fique com os momentos principais e deixe o resto da fonte de fora. Use SÓ quantas a história aguenta com uma virada forte em cada uma: "
        "melhor 2 partes fortes que 4 com enchimento. Se a história não rende mais de 1 vídeo, diga `partes_possiveis` = 1.\n"
        "Cada parte tem começo, virada e um gancho final que deixa uma pergunta real em aberto. A última fecha o arco.",
        ("# Personagens com aparência fixa (reuse o id)\n" + fichas if fichas else "")
        + "\nListe em `personagens` todos que aparecem na série, com uma descricao_visual em inglês bem específica. "
          "Eles terão a MESMA aparência em todas as partes. Todo personagem COM NOME que fala ou age em alguma parte "
          "(ex.: Rúben e Judá, entre os irmãos de José) tem id e ficha próprios, fora do grupo; o grupo continua na "
          "lista só para as cenas em que aparece junto.",
    ] if x)
    correcoes, ultimo_erro, anterior, historico = [], "", None, []
    for tentativa in range(1, TENTATIVAS_PLANO + 1):
        prompt = base
        if correcoes:  # corrige a versão anterior (sem ela, cada tentativa recomeçava do zero e trocava de defeito)
            prompt += ("\n\n# CORRIJA o plano anterior (mantenha o que não foi apontado)\n"
                       + json.dumps({k: anterior[k] for k in ("titulo_serie", "arco", "partes")}, ensure_ascii=False)
                       + "\n\nProblemas:\n" + "\n".join(f"- {c}" for c in correcoes)
                       # cada tentativa consertava um defeito e trazia de volta um antigo (José, 25/09)
                       + ("\n\nJá apontados em versões anteriores (não volte a cometer):\n" + "\n".join(f"- {c}" for c in historico)
                          if historico else ""))
        log(f"série: planejando (tentativa {tentativa})")
        with medidor.etapa("serie_plano"):
            p = llm.chamar(prompt, SCHEMA_PLANO, papel="roteirista")
        if p["partes"]:
            p["partes"][-1]["gancho_final"] = ""
        erros = checar_plano(p, max_partes, fonte_ref)  # SerieInviavel sobe direto
        if not erros:
            erros = julgar_plano(p, nicho, tema, fonte_ref, max_partes)
        if not erros:
            _fixas(p, bool(fonte_ref))
            log(f"série: plano aprovado, {len(p['partes'])} partes: " + " | ".join(x["titulo"] for x in p["partes"]))
            return p
        log("série: plano reprovado: " + " | ".join(erros[:4]))
        historico += [c for c in correcoes if c not in historico]
        correcoes, ultimo_erro, anterior = erros, "; ".join(erros[:3]), p
    raise RuntimeError(f"o plano da série não passou em {TENTATIVAS_PLANO} tentativas: {ultimo_erro}")


def julgar_plano(p: dict, nicho: str, tema: dict, fonte_ref: str | None, max_partes: int = MAX_PARTES) -> list[str]:
    partes = "\n".join(f"Parte {x['n']} «{x['titulo']}» [{x['trecho'] or '-'}]: {x['resumo']} | virada: {x['virada']} | "
                       f"termina com: {x['gancho_final'] or '(fim da série)'}" for x in p["partes"])
    prompt = (
        "Você revisa o PLANO de uma série de vídeos curtos antes de alguém escrever os roteiros. Ache problemas, não elogie.\n\n"
        f"# Nicho: {nicho} · Tema: {tema['titulo']}\n"
        + (f"# Fonte ({biblia.TRADUCAO})\n{biblia.trecho(fonte_ref)}\n\n" if fonte_ref else "")
        + f"# Plano: «{p['titulo_serie']}»\nArco: {p['arco']}\n{partes}\n\n"
        "# Reprove (aprovado=false) se\n"
        "- alguma parte não tem virada própria (é só enchimento ou preparação pra próxima);\n"
        "- dá pra contar a mesma coisa em menos partes sem perder força (diga quais juntar);\n"
        "- a divisão corta a história num lugar sem tensão, ou o gancho final não deixa uma pergunta real;\n"
        "- partes repetem o mesmo acontecimento;\n"
        # detalhe de ligação no resumo ("vai visitá-los no campo") reprovava o plano inteiro (José, 25/09); o resumo não vai
        # ao ar e o roteiro de cada parte é conferido depois contra o próprio trecho (camada 2)
        + ("- a VIRADA ou o fato central de alguma parte NÃO está no trecho daquela parte, ou contradiz a fonte (detalhe "
           "de ligação no resumo não reprova; o gancho_final PODE antecipar ou perguntar sobre o que a PRÓXIMA parte "
           "conta, é pra isso que ele existe);\n" if fonte_ref else "- o fato central é falso;\n")
        + "- a última parte não fecha o arco.\n"
        # o juiz mandou dividir em 4 com teto de 3, e o plano morreu no teto (José, 25/09)
        + f"A série tem no MÁXIMO {max_partes} partes: nunca peça mais partes que isso; se falta espaço, diga o que cortar.\n"
        "SÓ esses motivos reprovam. Gosto (um gancho que podia ser mais forte, um título melhor) NÃO reprova: se o plano "
        "não tem nenhum dos problemas acima, aprovado=true e problemas vazio. Resumo que conta um fato da fonte com outras "
        "palavras não é erro. Cada problema: a parte e como corrigir DENTRO da fonte dada, em 1 frase. No máximo 5.")
    with medidor.etapa("serie_juiz"):
        v = llm.chamar(prompt, SCHEMA_VEREDITO, papel="juiz", modelo=caminhos.MODELO_JUIZ_ROTEIRO)
    return [] if v["aprovado"] else (v["problemas"] or ["o revisor reprovou o plano sem dizer por quê: refaça com viradas mais fortes"])


# ---------------------------------------------------------------- roteiro de cada parte

def contexto_parte(plano: dict, k: int, nicho: str, anteriores: list[list[str]], correcoes: list[str] | None = None) -> str:
    N = len(plano["partes"])
    x = plano["partes"][k - 1]
    linhas = [f"# SÉRIE «{plano['titulo_serie']}»: este roteiro é a PARTE {k} de {N}",
              f"Arco da série: {plano['arco']}", "Plano de todas as partes:"]
    linhas += [f"- Parte {y['n']}: {y['titulo']}: {y['resumo']}" + (f" (termina com: {y['gancho_final']})" if y['gancho_final'] else "")
               for y in plano["partes"]]
    linhas.append(f"\nESTA parte ({k}) conta: {x['resumo']}\nVirada desta parte: {x['virada']}")
    if x.get("versiculo"):
        linhas.append(f"Versículo-chave desta parte (use no campo versiculo e na fala): {x['versiculo']}")
    if k < N:
        linhas.append(f"Termina EM ABERTO: a cena antes do CTA é o gancho «{x['gancho_final']}». NÃO conte o que é da parte "
                      f"{k + 1}. Aqui o payoff é a virada desta parte + a curiosidade pra próxima.")
    else:
        linhas.append("É o FINAL da série: resolve o arco e responde os ganchos das partes anteriores.")
    linhas.append(cta.bloco(nicho, k + 1 if k < N else None))
    if k > 1:
        linhas.append("A cena 1 é um gancho que funciona até pra quem NÃO viu a parte anterior (até 8 palavras); a cena 2 "
                      "situa em 1 frase curta o que aconteceu antes. Não repita frases das partes anteriores.")
    linhas.append(f"O título do post e o título do TikTok terminam com '(Parte {k}/{N})'.")
    if anteriores:
        linhas.append("\nPartes anteriores, já escritas (continuidade: mesmos nomes, mesmos fatos):")
        linhas += [f"Parte {j}: " + " ".join(f) for j, f in enumerate(anteriores, 1)]
    if plano["personagens"]:
        linhas.append("\nPersonagens fixos da série (mesmo id, nome e papel em todas as partes):")
        linhas += [f"- `{c['id']}`: {c['nome']} ({c['nome_en']}) — {c['descricao_visual']}" for c in plano["personagens"]]
    if correcoes:
        linhas.append("\nO revisor da SÉRIE reprovou a versão anterior desta parte. Corrija:")
        linhas += [f"- {c}" for c in correcoes]
    return "\n".join(linhas)


def fixar_personagens(r: dict, plano: dict) -> None:
    """Consistência por construção: o personagem da parte usa a ficha do plano, mesmo que o roteirista tenha reescrito."""
    fichas = {c["id"]: c for c in plano["personagens"]}
    for p in r.get("personagens", []):
        if p["id"] in fichas:
            p.update({k: fichas[p["id"]][k] for k in ("nome", "nome_en", "descricao_visual")})


def titulo_parte(t: str, k: int, n: int) -> str:
    return t if f"{k}/{n}" in t else f"{t.strip()} (Parte {k}/{n})"


def roteiro_gospel(formato_id: str, tema: dict, plano: dict, k: int, slug_serie: str, anteriores: list[list[str]],
                   correcoes: list[str] | None = None, anterior: dict | None = None) -> tuple[Path, dict]:
    """Uma parte pelo pipeline bíblico (camadas 1 e 2 de sempre), com o trecho só desta parte como fonte."""
    import pipeline

    formato = dict(pipeline.carregar("formatos.json")[formato_id])
    N, x = len(plano["partes"]), plano["partes"][k - 1]
    # o trecho de uma parte é maior que o de um vídeo único e o fechamento chama pra próxima parte; da 2ª em diante
    # ainda tem a frase que recapitula. A duração real continua conferida na camada 4 (pipeline.DURACAO_OK)
    formato["palavras"] = [formato["palavras"][0], formato["palavras"][1] + (FOLGA_PARTE if k == 1 else FOLGA_PARTE_RECAP)]
    # as correções vão pelo caminho de reescrita do pipeline (com a versão anterior), não aqui
    formato["receita"] = formato["receita"] + "\n\n" + contexto_parte(plano, k, "gospel", anteriores)
    tema_p = {**tema, "id": f"{tema['id']}-p{k}", "ref": x["trecho"] or tema["ref"],
              "titulo": f"{tema['titulo']} (parte {k} de {N}: {x['titulo']})",
              "angulo": f"{x['resumo']} Virada: {x['virada']}", "personagens": [c["id"] for c in plano["personagens"]]}
    slug = f"{slug_serie}-p{k}"
    reg = pipeline.Registro(slug)
    r = pipeline.roteiro_validado(formato, tema_p, reg, [f"(série) {c}" for c in correcoes] if correcoes else None, anterior)
    if not r:
        raise RuntimeError(f"parte {k}: o roteiro não passou nas validações em {pipeline.MAX_REESCRITAS} tentativas ({reg.arq})")
    fixar_personagens(r, plano)
    pacote = pipeline.empacotar(r, formato_id, formato, tema_p, formato["estilo"], slug)
    if formato["epoca"] != "biblica":  # personagem inventado: um retrato só pra série toda (não um por parte)
        for p in pacote["personagens"]:
            p["id_retrato"] = f"{slug_serie}__{p['id']}"
    pacote["titulo"] = titulo_parte(pacote["titulo"], k, N)
    if pacote.get("tiktok_titulo"):
        pacote["tiktok_titulo"] = titulo_parte(pacote["tiktok_titulo"], k, N)
    pacote["serie"] = {"slug": slug_serie, "titulo": plano["titulo_serie"], "parte": k, "total": N}
    pipeline.salvar_fichas(pacote)
    arq = pipeline.PROD / "roteiros" / f"{date.today():%Y-%m-%d}_{slug}.json"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps([pacote], ensure_ascii=False, indent=2), encoding="utf-8")
    return arq, pacote


# ---------------------------------------------------------------- juiz da série (roteiros)

SCHEMA_SERIE = {
    "type": "object", "additionalProperties": False, "required": ["entendimento", "partes"],
    "properties": {
        "entendimento": {"type": "string", "description": "em 1-2 frases, a história que quem vê a série inteira entende"},
        "partes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["n", "problemas"],
            "properties": {"n": {"type": "integer"},
                           "problemas": {"type": "array", "items": {"type": "string"},
                                         "description": "só problemas da SÉRIE, cada um com a cena e como corrigir; vazio se ok"}}}},
    },
}


def julgar_roteiros(plano: dict, roteiros: list[dict], nicho: str, fonte_ref: str | None = None) -> dict[int, list[str]]:
    """roteiros: [{falas: [...], personagens: [{id, nome}]}], na ordem. Devolve só as partes com problema."""
    N = len(roteiros)
    blocos = []
    for k, r in enumerate(roteiros, 1):
        pers = ", ".join(f"{p['nome']} ({p['id']})" for p in r.get("personagens", [])) or "-"
        blocos.append(f"## Parte {k} de {N} · personagens: {pers}\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(r["falas"], 1)))
    prompt = (
        "Você revisa uma SÉRIE de vídeos curtos inteira, antes das imagens. Cada parte já passou sozinha por outro revisor: "
        "aqui você olha SÓ o que aparece quando as partes são vistas em sequência. Ache problemas, não elogie.\n\n"
        f"# Nicho: {nicho} · Série «{plano['titulo_serie']}»\nArco planejado: {plano['arco']}\n\n"
        + (f"# Fonte ({biblia.TRADUCAO})\n{biblia.trecho(fonte_ref)}\n\n" if fonte_ref else "")
        + "# Roteiros (uma voz narra; cada linha é uma cena)\n" + "\n\n".join(blocos) + "\n\n"
        "# Aponte, por parte\n"
        "- continuidade: um fato de uma parte contradiz outra, ou a ordem dos acontecimentos se inverte entre partes;\n"
        "- personagens: o mesmo personagem com outro nome, outro papel ou apresentado de novo como se fosse novo; "
        "alguém que some ou surge sem explicação;\n"
        "- repetição: a parte reconta o que a anterior já contou (além de 1 frase curta de recapitulação);\n"
        "- ligação: o fim da parte k não abre a pergunta que a parte k+1 responde, ou a parte k+1 não retoma o gancho;\n"
        "- sozinha: quem cair direto numa parte do meio não entende quem é quem;\n"
        "- final: a última parte não fecha o arco nem responde os ganchos;\n"
        + ("- fechamento: toda parte termina pedindo o amém e a inscrição; as do meio chamam pra próxima parte.\n"
           if nicho == "gospel" else "- chamada: as partes do meio não chamam pra próxima parte.\n")
        + "Não aponte gosto, ritmo ou detalhe que não seja da série. Devolva um item por parte (problemas vazio se ok).")
    with medidor.etapa("serie_juiz"):
        v = llm.chamar(prompt, SCHEMA_SERIE, papel="juiz", modelo=caminhos.MODELO_JUIZ_ROTEIRO)
    return {x["n"]: x["problemas"] for x in v["partes"] if x["problemas"] and 1 <= x["n"] <= N}


# ---------------------------------------------------------------- juiz visual da série

SCHEMA_ROSTO = {
    "type": "object", "additionalProperties": False, "required": ["mesma_pessoa", "destoam", "problema"],
    "properties": {"mesma_pessoa": {"type": "boolean"},
                   "destoam": {"type": "array", "items": {"type": "integer"}, "description": "números (da lista) das imagens que destoam"},
                   "problema": {"type": "string"}},
}


def julgar_visual(partes: list[tuple[int, dict, Path]], pasta_tmp: Path) -> list[str]:
    """partes: [(k, roteiro empacotado, pasta de mídia)]. Para cada personagem que aparece em 2+ partes, pega uma
    imagem por parte (a 1ª cena em que ele é o principal, de rosto visível) e pergunta se é a mesma pessoa."""
    por_id: dict[str, list[tuple[int, Path]]] = {}
    fichas = {}
    for k, r, pasta in partes:
        for p in r.get("personagens", []):
            fichas.setdefault(p["id"], p)
        vistos = set()
        for n, c in enumerate(r["cenas"], 1):
            pid = (c.get("personagens") or [None])[0]
            if not pid or pid in vistos or not c.get("rosto_visivel", True) or pid.startswith("deus"):
                continue
            arq = next((a for a in sorted(pasta.glob(f"cena_{n:02d}.*")) if a.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}), None)
            if arq:
                vistos.add(pid)
                por_id.setdefault(pid, []).append((k, arq))
    avisos = []
    for pid, itens in por_id.items():
        if len({k for k, _ in itens}) < 2:
            continue
        pasta = pasta_tmp / pid
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        lista = []
        for i, (k, arq) in enumerate(itens, 1):
            dest = pasta / f"{i:02d}_parte{k}{arq.suffix}"
            shutil.copy(arq, dest)
            lista.append(f"{i}. {dest} (parte {k})")
        f = fichas[pid]
        prompt = (f"Abra com a ferramenta Read cada imagem da lista. Todas deveriam mostrar o MESMO personagem de uma série: "
                  f"{f['nome']} — {f['descricao_visual']}.\n\n" + "\n".join(lista) + "\n\n"
                  "É claramente a mesma pessoa em todas (rosto, idade, cabelo, barba, tom de pele, roupa)? Luz, ângulo, "
                  "expressão e cenário diferentes NÃO contam. Liste em `destoam` só as imagens em que um espectador diria "
                  "'esse é outro homem/outra mulher'.")
        try:
            with medidor.etapa("serie_juiz_visual"):
                v = llm.chamar(prompt, SCHEMA_ROSTO, ler_arquivos_em=pasta)  # mesmo modelo do juiz visual
        except Exception as e:  # noqa: BLE001 - juiz visual fora do ar não derruba a série: vira aviso pra revisão
            avisos.append(f"{f['nome']}: não consegui conferir o rosto entre as partes ({e})")
            continue
        if not v["mesma_pessoa"] or v["destoam"]:
            partes_ruins = sorted({itens[i - 1][0] for i in v["destoam"] if 1 <= i <= len(itens)})
            avisos.append(f"{f['nome']} muda de cara entre as partes" + (f" (parte {', '.join(map(str, partes_ruins))})" if partes_ruins else "")
                          + f": {v['problema']}")
    shutil.rmtree(pasta_tmp, ignore_errors=True)
    return avisos
