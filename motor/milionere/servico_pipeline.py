"""Ponte entre o produto (site) e o pipeline: o Django chama só estas funções.

    catalogo()                                  -> nichos, formatos, temas e roteiros prontos (formato da tela)
    roteiro_pronto(tema_id)                     -> roteiro já aprovado (Lázaro, Pedro, planeta de vidro...) ou None
    gerar_roteiro(entrada, log)                 -> roteiro por IA (gospel do catálogo bíblico: pipeline do Rafael
                                                   com as camadas 1 e 2; outros nichos: roteirista genérico)
    gerar_video(entrada, pasta_job, log)        -> {video, post}: roda o produzir.py com progresso por etapa

`log(etapa, msg)` recebe o progresso ('roteiro', 'voz', 'imagens', 'montagem', 'post').
Cada vídeo usa um slug próprio (job-<id>): dois usuários com o mesmo tema nunca se sobrescrevem.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402

REPO_PRODUCAO = caminhos.RAIZ / "producao"   # roteiros e mídias já feitos pelo time (fonte dos "prontos")
PRESET_DO_NICHO = {"gospel": "gospel", "astronomia": "astronomia", "animais": "curiosidades"}
VOZES = {"antonio": "pt-BR-AntonioNeural-Male", "francisca": "pt-BR-FranciscaNeural-Female",
         "thalita": "pt-BR-ThalitaMultilingualNeural-Female"}
BUSCA_PADRAO = {"gospel": "man praying with bible", "astronomia": "galaxy stars space", "animais": "wild animal close up"}
# tema da tela -> slug do roteiro pronto em producao/roteiros (os do pipeline do Rafael usam o campo "tema")
PRONTOS_POR_SLUG = {"jesus-chorou-lazaro": "lazaro", "isaias-41-10-nao-tema": "isaias-41-10",
                    "ele-negou-jesus-3-vezes": "pedro-negou", "planeta-chove-vidro": "vidro",
                    "e-se-a-lua-sumisse": "lua", "enguia-escapa-estomago": "enguia"}
PARADAS = set("a o e é de da do das dos que em no na nos nas um uma pra para por com se ele ela eles elas lá já não "
              "mais mas mesmo foi era tá ser sua seu você isso esse essa aí ao aos como quando".split())


# ------------------------------------------------------------------ catálogo

def _prontos() -> dict[str, dict]:
    achados = {}
    for arq in sorted(REPO_PRODUCAO.glob("roteiros/*.json")):
        for r in json.loads(arq.read_text(encoding="utf-8")):
            if not r.get("cenas"):
                continue
            tema = PRONTOS_POR_SLUG.get(r["slug"]) or r.get("tema")
            if tema:
                achados[tema] = r
    return achados


def _tela(r: dict) -> dict:
    return {"titulo": r.get("titulo", ""), "falas": [c["fala"] for c in r["cenas"]],
            "extra": [{"busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
            "desc": r.get("descricao", ""), "tags": " ".join(r.get("hashtags", [])), "base": r["slug"]}


def roteiro_pronto(tema_id: str) -> dict | None:
    r = _prontos().get(tema_id)
    return _tela(r) if r else None


def catalogo() -> dict:
    import biblia

    formatos = {k: v for k, v in json.loads((caminhos.DADOS / "formatos.json").read_text(encoding="utf-8")).items()
                if not k.startswith("_")}
    temas = biblia.temas()
    gospel = {}
    for fid, f in formatos.items():
        lista = [[t["id"], f"{t['titulo']} · {t['ref']}" if t.get("ref") and fid != "personagem" else t["titulo"]]
                 for t in temas.get(f["catalogo"], [])]
        gospel[fid] = {"nome": f["nome"], "temas": lista}
    gospel["historia"]["temas"][:0] = [["lazaro", "Jesus chorou (Lázaro) · João 11"],
                                       ["pedro-negou", "Ele negou Jesus 3 vezes · Lucas 22 / João 21"]]
    gospel["sermao"] = {"nome": "Mensagem curta / sermão", "temas": [["isaias-41-10", "Se você tá com medo hoje · Isaías 41:10"]]}
    return {
        "nichos": {
            "gospel": {"nome": "Gospel", "cor": "#C9A227", "grad": ["#3b2a17", "#a8733a", "#f1c27d"], "formatos": gospel},
            "astronomia": {"nome": "Astronomia", "cor": "#4C6FFF", "grad": ["#050814", "#1b2a6b", "#6d8cff"], "formatos": {
                "uau": {"nome": "Fato que dá “uau”", "temas": [["vidro", "O planeta onde chove vidro de lado"],
                        ["neutron", "Uma colher de estrela de nêutrons"], ["espaguete", "Cair num buraco negro"],
                        ["pegadas", "As pegadas na Lua vão durar milhões de anos"]]},
                "ese": {"nome": "E se…?", "temas": [["lua", "E se a Lua sumisse hoje à noite?"], ["sol", "E se o Sol apagasse?"],
                        ["terra-parar", "E se a Terra parasse de girar?"]]}}},
            "animais": {"nome": "Animais bizarros", "cor": "#2E9E6B", "grad": ["#062016", "#146b4a", "#7fd6a8"], "formatos": {
                "bizarro": {"nome": "Bicho bizarro", "temas": [["enguia", "A enguia que escapa do estômago"],
                            ["polvo", "Três corações e sangue azul"], ["agua-viva", "O animal que não morre de velhice"]]}}},
            "tecnologia": {"nome": "Tecnologia", "cor": "#8A8F98", "breve": True},
            "historia": {"nome": "História", "cor": "#9C5B3B", "breve": True},
            "mitologia": {"nome": "Mitologia", "cor": "#7A5AC8", "breve": True},
            "psicologia": {"nome": "Psicologia", "cor": "#D0598A", "breve": True},
        },
        "prontos": {k: _tela(r) for k, r in _prontos().items()},
    }


# ------------------------------------------------------------------ roteiro por IA

SCHEMA_SIMPLES = {
    "type": "object", "additionalProperties": False,
    "required": ["titulo", "cenas", "descricao", "hashtags", "comentario_fixado"],
    "properties": {
        "titulo": {"type": "string"},
        "cenas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "required": ["fala", "busca", "imagem"], "properties": {
                      "fala": {"type": "string", "description": "1 frase curta em pt-BR, 3 a 14 palavras"},
                      "busca": {"type": "string", "description": "em inglês: termo concreto de vídeo de banco (Pexels)"},
                      "imagem": {"type": "string", "description": "em inglês: prompt de imagem da cena, até 30 palavras"}}}},
        "descricao": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}},
        "comentario_fixado": {"type": "string"},
    },
}


SCHEMA_JUIZ = {
    "type": "object", "additionalProperties": False, "required": ["notas", "erros_factuais", "problemas"],
    "properties": {
        "notas": {"type": "object", "additionalProperties": False,
                  "required": ["gancho", "clareza", "ritmo", "linguagem", "payoff", "precisao"],
                  "properties": {k: {"type": "integer", "minimum": 1, "maximum": 5}
                                 for k in ["gancho", "clareza", "ritmo", "linguagem", "payoff", "precisao"]}},
        "erros_factuais": {"type": "array", "items": {"type": "string"}},
        "problemas": {"type": "array", "items": {"type": "string"}, "description": "cada um com o número da cena e como corrigir"},
    },
}
MAX_TENTATIVAS = 3


def _preset(nicho: str) -> dict:
    return json.loads((caminhos.DADOS / "presets.json").read_text(encoding="utf-8"))[PRESET_DO_NICHO.get(nicho, "curiosidades")]


def _juiz(r: dict, entrada: dict, tema: str) -> tuple[list[str], dict]:
    """Camada 2 genérica: outra conversa, modelo barato (papel juiz), critérios fixos."""
    import llm

    cenas = "\n".join(f"{i}. {c['fala']}" for i, c in enumerate(r["cenas"], 1))
    prompt = (
        "Você revisa roteiros de Shorts/TikTok em pt-BR antes de publicar. Ache problemas, não elogie. "
        "Nota 5 só se não há nada a melhorar; 3 = publicável com defeito visível.\n\n"
        f"# Nicho: {entrada['nicho']} · Tema: {tema}\n# Roteiro (uma voz narra; cada linha é uma cena com uma imagem)\n{cenas}\n\n"
        "# Critérios (1-5)\n- gancho: a 1ª frase faz parar de rolar o feed?\n- clareza: quem ouve UMA vez entende tudo?\n"
        "- ritmo: nenhuma frase sobrando, frases curtas e variadas?\n- linguagem: soa como gente falando, sem cara de IA?\n"
        "- payoff: o final entrega surpresa/emoção e responde o gancho?\n"
        "- precisao: o FATO CENTRAL está correto? Dramatização em tom de hipótese ('imagina') não é erro.\n"
        "erros_factuais = só afirmações apresentadas como fato que estão erradas. "
        "Cada problema: número da cena + como corrigir, em 1 frase.")
    j = llm.chamar(prompt, SCHEMA_JUIZ, papel="juiz", modelo=caminhos.MODELO_JUIZ_ROTEIRO)
    notas = j["notas"]
    reprova = bool(j["erros_factuais"]) or min(notas.values()) < 3 or sum(notas.values()) / len(notas) < 3.6
    problemas = [f"ERRO FACTUAL: {e}" for e in j["erros_factuais"]] + (j["problemas"] if reprova else [])
    return problemas, notas


def _roteiro_generico(entrada: dict, log) -> dict:
    """Roteirista guiado: exemplos e erros do nicho no prompt -> checagem por código -> juiz -> reescreve só o apontado."""
    import banco_roteiros
    import guia
    import llm
    import medidor

    refs = caminhos.DADOS / "referencias"
    ler = lambda n: (refs / n).read_text(encoding="utf-8") if (refs / n).exists() else ""  # noqa: E731
    nicho, preset = entrada["nicho"], _preset(entrada["nicho"])
    lo, hi = preset["palavras_min"], preset["palavras_max"]
    tema = entrada.get("tema_livre") or entrada.get("tema_titulo") or entrada.get("tema")
    formato = entrada.get("formato_nome", entrada.get("formato", ""))
    base = "\n\n".join([
        "Você é roteirista de Shorts/TikTok em português do Brasil. Escreva UM roteiro dividido em cenas.",
        f"# Nicho: {nicho} · formato: {formato}\n# Tema: {tema}",
        f"# Tamanho\n{lo} a {hi} palavras no total, 7 a 13 cenas, uma frase por cena (3 a 14 palavras). "
        "A 1ª é o gancho (até 8 palavras); a última é um CTA curto (comenta, manda pra alguém, escreve...).",
        "# Fatos\nO fato central tem que ser verdadeiro. O resto pode ser dramatização em tom de hipótese ('imagina', 'provavelmente').",
        guia.bloco(nicho, formato, tema),
        f"# Ganchos\n{ler('ganchos.md')}", f"# Linguagem\n{ler('anti-ia.md')}",
        "# Post\nTítulo até 60 caracteres, descrição com 1-2 frases e uma pergunta, 5 hashtags com #shorts.",
    ])
    melhor, correcoes = None, []
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        prompt = base
        if correcoes:
            prompt += ("\n\n# REESCREVA corrigindo TODOS estes problemas (sem criar outros)\n"
                       + "\n".join(f"- {c}" for c in correcoes) + "\n\nVersão anterior:\n"
                       + json.dumps([c["fala"] for c in melhor[0]["cenas"]], ensure_ascii=False))
        log("roteiro", f"escrevendo (tentativa {tentativa})")
        with medidor.etapa("roteiro"):
            r = llm.chamar(prompt, SCHEMA_SIMPLES, papel="roteirista")
        erros = guia.checar(r["cenas"], preset)                      # camada 1: código, grátis
        notas = {}
        if not erros and caminhos.JUIZ_ROTEIRO:                      # camada 2: só se o código aprovou
            log("roteiro", f"juiz revisando (tentativa {tentativa})")
            with medidor.etapa("juiz"):
                erros, notas = _juiz(r, entrada, tema)
        pontos = (sum(notas.values()) if notas else 0) - 3 * len(erros)
        if melhor is None or pontos >= melhor[2]:
            melhor = (r, notas, pontos)
        banco_roteiros.registrar_erros(nicho, formato, erros)          # a memória aprende com cada reprovação
        if not erros:
            banco_roteiros.adicionar(nicho, formato, tema, r["titulo"], [c["fala"] for c in r["cenas"]], notas, "ia")
            return {**r, "_notas_juiz": notas, "_tentativas": tentativa}
        correcoes = erros
    r, notas, _ = melhor
    return {**r, "_notas_juiz": notas, "_tentativas": MAX_TENTATIVAS, "_avisos": correcoes}


def gerar_roteiro(entrada: dict, log) -> dict:
    """entrada: {nicho, formato, tema, tema_livre?, tema_titulo?}. Devolve o roteiro no formato da tela."""
    import medidor

    pronto = None if entrada.get("tema_livre") else roteiro_pronto(entrada.get("tema", ""))
    if pronto:
        return pronto
    if entrada["nicho"] == "gospel" and not entrada.get("tema_livre"):
        import banco_roteiros
        import biblia
        import pipeline

        formato = pipeline.carregar("formatos.json").get(entrada.get("formato", ""))
        tema = next((t for t in biblia.temas().get(formato["catalogo"], []) if t["id"] == entrada.get("tema")), None) if formato else None
        if tema:
            log("roteiro", "escrevendo com o texto exato da Bíblia e validando (camadas 1 e 2)")
            reg = pipeline.Registro(f"svc-{entrada.get('job', 'x')}")
            with medidor.etapa("roteiro+juiz (bíblico)"):
                r = pipeline.roteiro_validado(formato, tema, reg)
            reprovacoes = [p for e in reg.dados["etapas"] if not e["ok"] for p in e.get("problemas", [])]
            banco_roteiros.registrar_erros("gospel", formato["nome"], reprovacoes)
            if not r:
                raise RuntimeError("o roteiro não passou nas validações; tente outro tema ou escreva o seu")
            banco_roteiros.adicionar("gospel", formato["nome"], tema["titulo"], r["titulo"], [c["fala"] for c in r["cenas"]],
                                     r.get("_notas_juiz", {}), "ia")
            return {**_tela({**r, "slug": ""}), "base": "", "notas": r.get("_notas_juiz", {})}
    r = _roteiro_generico(entrada, log)
    return {**_tela({**r, "slug": ""}), "base": "", "notas": r.get("_notas_juiz", {}), "tentativas": r.get("_tentativas"),
            "avisos": r.get("_avisos", [])}


# ------------------------------------------------------------------ vídeo

def _busca_auto(fala: str, nicho: str) -> str:
    palavras = [w for w in re.findall(r"[\wÀ-ÿ]+", fala.lower()) if len(w) > 3 and w not in PARADAS]
    termo = " ".join(palavras[:3])
    return (f"pt:{termo}|" if termo else "") + BUSCA_PADRAO.get(nicho, "cinematic landscape")


def _salvar_upload(data_url: str, pasta: Path, n: int) -> None:
    cab, dados = data_url.split(",", 1)
    ext = {"image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4"}.get(cab[5:].split(";")[0], ".jpg")
    for velho in pasta.glob(f"cena_{n:02d}*"):
        velho.unlink()
    (pasta / f"cena_{n:02d}{ext}").write_bytes(base64.b64decode(dados))


def montar_roteiro(entrada: dict, slug: str) -> dict:
    """entrada da tela -> roteiro do produzir.py. Reaproveita busca/escolha/imagens do roteiro pronto quando a fala não mudou."""
    nicho = entrada["nicho"]
    base = _prontos().get(entrada.get("tema", "")) if not entrada.get("tema_livre") else None
    midia = caminhos.PRODUCAO / "midia" / slug
    midia.mkdir(parents=True, exist_ok=True)
    cenas = []
    for i, c in enumerate(entrada["cenas"]):
        fala = c["fala"].strip()
        if not fala:
            continue
        n = len(cenas) + 1
        igual = base and i < len(base["cenas"]) and base["cenas"][i]["fala"].strip() == fala
        if igual:
            cena = {k: v for k, v in base["cenas"][i].items() if k in ("fala", "busca", "arte", "foto", "escolha", "imagem")}
            for arq in (REPO_PRODUCAO / "midia" / base["slug"]).glob(f"cena_{i + 1:02d}*"):
                shutil.copy(arq, midia / arq.name.replace(f"cena_{i + 1:02d}", f"cena_{n:02d}", 1))
        else:
            cena = {"fala": fala, "busca": (c.get("busca") or "").strip() or _busca_auto(fala, nicho)}
            if c.get("imagem"):
                cena["imagem"] = c["imagem"]
        cenas.append(cena)
        if (entrada.get("uploads") or {}).get(str(i)):
            _salvar_upload(entrada["uploads"][str(i)], midia, n)
    # banco de imagens do nicho: cena sem imagem ainda (sem upload e sem imagem do roteiro pronto) consulta o banco
    usados, do_banco = set(), {}
    try:
        import banco_imagens
        contexto = []  # último personagem citado: "chorou sozinho" depois de uma cena do Pedro = Pedro chorando
        for n, cena in enumerate(cenas, 1):
            citados = banco_imagens.detectar_personagens(cena["fala"])
            contexto = citados or contexto
            if any(midia.glob(f"cena_{n:02d}.*")):
                continue
            texto = cena["fala"] if citados or not contexto else f"{cena['fala']} ({contexto[0]})"
            achado = next((a for a in banco_imagens.buscar(nicho, texto, dono=entrada.get("dono", ""), excluir=usados)
                           if a["nota"] >= banco_imagens.LIMIAR_REUSO), None)
            if achado:
                shutil.copy(achado["arquivo"], midia / f"cena_{n:02d}{achado['arquivo'].suffix}")
                usados.add(achado["id"])
                do_banco[n] = {"id": achado["id"], "nota": achado["nota"]}
    except Exception as e:  # o banco nunca derruba o vídeo: sem banco, segue para a busca normal
        print(f"banco de imagens indisponível: {e}")
    if base:  # as escolhas da curadoria apontam para o candidatos.json do roteiro pronto
        cur = REPO_PRODUCAO / "curadoria" / base["slug"] / "candidatos.json"
        if cur.exists():
            (caminhos.PRODUCAO / "curadoria" / slug).mkdir(parents=True, exist_ok=True)
            shutil.copy(cur, caminhos.PRODUCAO / "curadoria" / slug / "candidatos.json")
    post = entrada.get("post") or {}
    ajustes = {"voice_rate": float(entrada.get("vel", 1.0)),
               "voice_name": VOZES.get(entrada.get("voz", "antonio"), VOZES["antonio"]),
               "subtitle_display_mode": "word_by_word" if entrada.get("leg") == "palavra" else "sentence",
               "text_fore_color": "#FFE600" if entrada.get("cor") == "amarela" else "#FFFFFF"}
    return {"slug": slug, "nicho": PRESET_DO_NICHO.get(nicho, "curiosidades"), "titulo": post.get("titulo") or "Meu Short",
            "cenas": cenas, "descricao": post.get("desc", ""), "hashtags": (post.get("tags") or "#shorts").split(),
            "comentario_fixado": post.get("comentario", ""), "ajustes": ajustes, "_do_banco": do_banco}


def gerar_video(entrada: dict, pasta_job: Path, log) -> dict:
    slug = f"job-{pasta_job.name[:8]}"
    r = montar_roteiro(entrada, slug)
    if not r["cenas"]:
        raise RuntimeError("o roteiro está vazio")
    pasta_job.mkdir(parents=True, exist_ok=True)
    arq = pasta_job / "roteiro.json"
    arq.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
    log("roteiro", f"{len(r['cenas'])} cenas prontas")
    cmd = [str(caminhos.PYTHON_MOTOR), str(Path(__file__).with_name("produzir.py")), str(arq)]
    mus = entrada.get("mus", "sem")
    if mus == "sem":
        cmd.append("--sem-musica")
    elif mus == "ambas":
        cmd.append("--duas-versoes")  # monta uma vez; a versão com música é só a mistura do áudio
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(cmd, cwd=caminhos.MOTOR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    video, videos, falhas, saida = None, [], [], []
    for linha in proc.stdout:
        linha = linha.rstrip()
        saida.append(linha)
        if linha.startswith("ETAPA "):
            log(linha.split()[1], "")
        elif linha.startswith("PRONTO"):
            videos.append(Path(linha.split("] ", 1)[1].strip()))
            video = next((v for v in videos if "_sem-musica" not in v.stem), videos[0])
        elif linha.startswith("FALHOU"):
            falhas.append(linha)
    proc.wait()
    (pasta_job / "log.txt").write_text("\n".join(saida), encoding="utf-8")
    if not video or not video.exists():
        raise RuntimeError(falhas[-1] if falhas else "o render falhou: veja log.txt do job")
    log("post", "")
    banco = _alimentar_banco(entrada, r, slug)
    try:  # vídeo com roteiro que passa na checagem por código também vira exemplo do nicho
        import banco_roteiros
        import guia
        if not guia.checar(r["cenas"], _preset(entrada["nicho"])) and not roteiro_pronto(entrada.get("tema", "")):
            banco_roteiros.adicionar(entrada["nicho"], entrada.get("formato", ""), entrada.get("tema_livre") or entrada.get("tema", ""),
                                     r["titulo"], [c["fala"] for c in r["cenas"]], {}, "video")
    except Exception as e:
        print(f"banco de roteiros indisponível: {e}")
    txt = video.with_suffix(".txt")
    return {"video": str(video), "videos": [str(v) for v in videos if v.exists()],
            "post_txt": txt.read_text(encoding="utf-8") if txt.exists() else "",
            "titulo": r["titulo"], "descricao": r["descricao"], "hashtags": " ".join(r["hashtags"]), "banco": banco}


def _alimentar_banco(entrada: dict, r: dict, slug: str) -> dict:
    """Depois do vídeo pronto: marca o uso das imagens que vieram do banco e guarda as novas (uploads e IA).
    Upload só vira compartilhado se o usuário autorizou; senão fica no banco privado dele (dono)."""
    try:
        import banco_imagens
    except Exception:
        return {}
    do_banco = r.get("_do_banco", {})
    banco_imagens.marcar_uso([v["id"] for v in do_banco.values()])
    midia, novas = caminhos.PRODUCAO / "midia" / slug, 0
    uploads = {int(k) for k in (entrada.get("uploads") or {})}
    for n, cena in enumerate(r["cenas"], 1):
        if n in do_banco:
            continue
        img = next((p for p in sorted(midia.glob(f"cena_{n:02d}.*")) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), None)
        if not img:
            continue
        de_upload = (n - 1) in uploads
        desc = " | ".join(x for x in (cena["fala"], cena.get("imagem", "")) if x)
        if banco_imagens.adicionar(img, entrada["nicho"], desc, estilo=entrada.get("estilo", "cinema"),
                                   origem="upload" if de_upload else "ia-time", credito="Imagem gerada por IA",
                                   compartilhada=bool(entrada.get("compartilhar_banco")) or not de_upload,
                                   dono=entrada.get("dono", "")):
            novas += 1
    return {"reusadas": len(do_banco), "novas": novas}
