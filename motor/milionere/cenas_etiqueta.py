"""Cenas por ETIQUETA (opção barata ao lado do cenas_codigo.py): o Claude decide O QUÊ, o código decide ONDE.

Por cena o Claude escreve só uma etiqueta curta (molde, pose do Bob/Amigo, figurino, objeto, piada); posição,
tamanho, entrada e câmera vêm dos moldes daqui. Objeto que a biblioteca não tem é desenhado UMA vez pelo Opus e
salvo em dados/objetos_doodle.json: do vídeo seguinte em diante sai de graça. Sem revisão visual (o layout é fixo).

Custo típico: 1 chamada barata (Sonnet, saída de ~40 tokens por cena) + Opus só para objetos novos.

Uso avulso: python cenas_etiqueta.py roteiro.json
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import animacao_codigo as ac
import caminhos
import cenas_codigo
import llm

BIBLIOTECA = Path(__file__).with_name("dados") / "objetos_doodle.json"
DURACAO = cenas_codigo.DURACAO

# poses prontas: nome -> campos do personagem
POSES = {
    "explica": {"fala": True, "braco_d": "aponta"},
    "fala": {"fala": True, "braco_d": "frente"},
    "chocado": {"olhos": "arregalados", "sobrancelhas": "levantadas", "boca": "aberta", "braco_e": "cima", "braco_d": "frente", "tremer": True},
    "surpreso": {"olhos": "arregalados", "sobrancelhas": "levantadas", "boca": "o"},
    "feliz": {"olhos": "feliz", "boca": "grande", "braco_d": "acena"},
    "rindo": {"olhos": "feliz", "sobrancelhas": "levantadas", "boca": "grande", "pula": True},
    "orgulhoso": {"olhos": "feliz", "sobrancelhas": "levantadas", "boca": "sorriso", "braco_e": "cintura", "braco_d": "cintura"},
    "pensando": {"sobrancelhas": "uma", "boca": "reta", "braco_d": "rosto"},
    "confuso": {"olhos": "arregalados", "sobrancelhas": "preocupadas", "boca": "reta"},
    "vergonha": {"olhos": "fechados", "sobrancelhas": "preocupadas", "boca": "triste", "braco_e": "cobre", "braco_d": "cobre", "corado": True},
    "nervoso": {"sobrancelhas": "preocupadas", "boca": "nervosa", "suor": True},
    "triste": {"sobrancelhas": "preocupadas", "boca": "triste"},
    "bravo": {"sobrancelhas": "bravo", "boca": "reta", "braco_e": "cintura", "braco_d": "cintura"},
    "cansado": {"olhos": "fechados", "boca": "aberta", "braco_d": "boca"},
    "sussurro": {"olhos": "lado", "sobrancelhas": "uma", "boca": "sussurro", "braco_d": [95, -150]},
    "joinha": {"olhos": "feliz", "boca": "sorriso", "braco_d": "joinha"},
    "encolhe": {"sobrancelhas": "levantadas", "boca": "reta", "braco_e": "encolhe", "braco_d": "encolhe"},
    "segura": {"boca": "sorriso", "sobrancelhas": "levantadas", "braco_d": [150, -40]},
    "calmo": {"boca": "sorriso"},
    # ações
    "bocejo": {"olhos": "fechados", "sobrancelhas": "preocupadas", "boca": "aberta", "braco_e": "cima", "braco_d": "cima"},
    "dormindo": {"olhos": "fechados", "boca": "reta", "braco_e": "baixo", "braco_d": "baixo"},
    "corre": {"olhos": "arregalados", "boca": "aberta", "corre": True, "braco_e": "frente", "braco_d": "tras"},
    "come": {"olhos": "feliz", "fala": True, "braco_d": [60, -110]},
    "empurra": {"sobrancelhas": "bravo", "boca": "nervosa", "braco_e": [-200, -40], "braco_d": [200, -40]},
    "tonto": {"olhos": "espiral", "sobrancelhas": "preocupadas", "boca": "nervosa"},
    # expressões ricas
    "encantado": {"olhos": "brilho", "sobrancelhas": "levantadas", "boca": "sorrisao", "braco_e": "cima", "braco_d": "cima"},
    "apaixonado": {"olhos": "coracao", "boca": "sorrisao", "corado": True},
    "deslumbrado": {"olhos": "estrela", "sobrancelhas": "levantadas", "boca": "sorrisao", "pula": True},
    "chorando": {"olhos": "choro", "sobrancelhas": "preocupadas", "boca": "triste"},
    "desconfiado": {"olhos": "desconfiado", "sobrancelhas": "uma", "boca": "reta", "braco_d": "rosto"},
    "eita": {"olhos": "arregalados", "sobrancelhas": "preocupadas", "boca": "dentes", "suor": True},
    "zoeira": {"olhos": "feliz", "boca": "lingua", "braco_d": "joinha"},
    "curioso": {"olhos": "brilho", "sobrancelhas": "uma", "boca": "biquinho", "braco_d": "rosto"},
}
MOLDES = ("solo", "dupla", "close", "objeto", "pensa", "segura", "gigante", "divide", "lista")
EFEITOS = ("ondas", "vibra", "susto", "estrelas", "xis", "interrogacao", "zzz", "chuva")
LUGARES = ("padrao", "quarto", "sala", "cozinha", "escritorio", "escola", "onibus", "supermercado", "academia", "hospital",
           "laboratorio", "rua", "noite", "parque", "praia", "mar", "espaco", "corpo",
           "cor_azul", "cor_amarelo", "cor_rosa", "cor_verde")
ANIMS = ("pop", "desliza", "cai", "cresce")
CAMERAS = ("aproxima", "lado", "aproxima", "afasta")
TRANSICOES = ("desliza", "", "soco", "", "iris", "")  # metade das trocas continua corte seco (ritmo)

# objetos prontos do renderizador: tipo, escala "de destaque" e campo que recebe o parâmetro (celular:EU??)
PRONTOS = {
    "celular": ("celular", 1.1, "tela"), "telefone": ("celular", 1.1, "tela"), "lampada": ("lampada", 1.8, None),
    "ideia": ("lampada", 1.8, None), "microfone": ("microfone", 1.4, None), "caixa de som": ("caixa_som", 0.8, None),
    "rato": ("rato", 1.5, "fala"), "orelha": ("orelha", 1.7, None), "ouvido": ("orelha", 1.7, None),
    "placa": ("placa", 1.0, "txt"), "botao": ("botao", 1.0, "txt"),
}


def _chave(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome.lower().strip())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if not unicodedata.combining(c))).strip()


def biblioteca() -> dict:
    return json.loads(BIBLIOTECA.read_text(encoding="utf-8")) if BIBLIOTECA.exists() else {}


def _achar(nome: str, bib: dict) -> tuple[str, dict] | None:
    k = _chave(nome)
    if k in PRONTOS:
        return "pronto", {"nome": k}
    for chave, obj in bib.items():
        if k == chave or k in obj.get("sinonimos", []):
            return "bib", {"nome": chave, **obj}
    return None


# ---------------------------------------------------------------- objetos novos (Opus, uma vez)

SCHEMA_OBJETOS = {"type": "object", "properties": {"objetos": {"type": "array", "items": {
    "type": "object",
    "properties": {"nome": {"type": "string"}, "sinonimos": {"type": "array", "items": {"type": "string"}},
                   "mexe": {"type": "string"}, "formas": {"type": "array", "items": {"type": "object"}}},
    "required": ["nome", "formas"]}}}, "required": ["objetos"]}


def desenhar_novos(nomes: list[str], log=print) -> None:
    """Uma chamada ao Opus para todos os objetos que faltam; salva na biblioteca."""
    if not nomes:
        return
    prompt = (
        "Desenhe estes objetos como DOODLE para um canal de animação (contorno preto grosso, cores chapadas, "
        "reconhecível de longe, estilo desenho à mão simples). Cada objeto cabe numa caixa de -110 a 110 em x e y, "
        "centro em 0,0 (y cresce para baixo). Use 5 a 25 formas.\n"
        "Formas: {\"f\":\"circulo\",\"x\",\"y\",\"r\"} {\"f\":\"elipse\",\"x\",\"y\",\"rx\",\"ry\",\"rot\"} "
        "{\"f\":\"linha\"|\"poligono\",\"pts\":[[x,y],...]} {\"f\":\"arco\",\"x\",\"y\",\"r\",\"de\",\"ate\"} (graus) "
        "{\"f\":\"texto\",\"x\",\"y\",\"txt\",\"tam\"}; cada uma com \"cor\" (contorno: tinta ou \"nenhuma\"), "
        "\"preenche\" (tinta, azul, laranja, vermelho, amarelo, verde, branco, cinza ou #rrggbb) e \"larg\" (4 a 8). "
        "A ordem é a de desenho (fundo primeiro).\n"
        "Para cada um devolva também 'sinonimos' (outros nomes em português, minúsculas, sem acento) e 'mexe' "
        "(flutua, gira, pulsa, balanca ou vazio) se o objeto tiver um movimento natural.\n"
        "OBJETOS: " + ", ".join(nomes))
    with llm.medidor.etapa("objetos novos"):
        resp = llm.chamar(prompt, SCHEMA_OBJETOS, modelo=caminhos.MODELO_CENAS, timeout=900)
    bib = biblioteca()
    for o in resp.get("objetos", []):
        k = _chave(o.get("nome", ""))
        if k and o.get("formas"):
            bib[k] = {"sinonimos": sorted({_chave(s) for s in o.get("sinonimos", []) if s} - {k}),
                      "mexe": o.get("mexe", ""), "formas": o["formas"]}
            log(f"objeto novo na biblioteca: {k}")
    BIBLIOTECA.write_text(json.dumps(bib, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- etiquetas (Sonnet, barato)

SCHEMA = {"type": "object", "properties": {"cenas": {"type": "array", "items": {
    "type": "object",
    "properties": {
        "m": {"type": "string"}, "bob": {"type": "string"}, "amigo": {"type": "string"},
        "fig": {"type": "string"}, "fig_amigo": {"type": "string"}, "obj": {"type": "string"},
        "txt": {"type": "string"}, "cor": {"type": "string"}, "fx": {"type": "string"}, "lugar": {"type": "string"}},
    "required": ["m", "bob", "txt"]}}}, "required": ["cenas"]}


def _prompt(r: dict, bib: dict) -> str:
    objs = sorted(set(PRONTOS) | set(bib))
    falas = "\n".join(f"{i}. {c['fala']}" for i, c in enumerate(r["cenas"], 1))
    return f"""Você dirige as cenas de um Short em doodle (canal Bob Curioso). Para CADA fala, uma etiqueta curta que
ENCENA o que está sendo dito (a fala vira imagem na hora).
Campos:
 m: molde — solo (Bob + objeto grande) | dupla (Bob e o Amigo) | close (rosto do Bob, emoção forte) |
    objeto (o objeto é a estrela) | pensa (Bob pensando no objeto, balão) | segura (Bob segurando o objeto) |
    gigante (objeto ENORME e o Bob pequenininho olhando pra cima: escala, exagero) |
    divide (tela dividida: obj "A|B", mito x verdade, antes x depois; o A leva um X) |
    lista (3 objetos aparecendo um por um: obj "A|B|C")
 lugar: ONDE a cena acontece — {" | ".join(LUGARES)}.
    AMBIENTAÇÃO é o que dá vida: mostre a SITUAÇÃO REAL do dia a dia que a fala descreve (esqueceu o que ia pegar ->
    sala/cozinha; reunião -> escritorio; celular antes de dormir -> quarto; fila -> supermercado; trânsito -> onibus;
    treino -> academia; sintoma -> hospital; noite/insônia -> noite). Explicação "por dentro" -> corpo; céu -> espaco.
    Continuidade: a história tem um lugar principal (onde o Bob vive a situação) e só troca quando a fala troca de
    situação: 2 a 4 lugares por vídeo. "cor_*" (fundo chapado) no máximo 1 vez, só no maior impacto.
 bob / amigo: pose — {" | ".join(POSES)}  (amigo vazio = não aparece; use em "dupla")
 fig / fig_amigo: figurino quando a fala cita um papel — chapéu (policia chef piloto astronauta coroa cartola
    capacete_obra formatura bone cowboy mago pirata) e/ou roupa (gravata jaleco capa distintivo avental colete medalha),
    ex.: "piloto+gravata"; vazio se não houver
 obj: QUASE SEMPRE preencha (só fica vazio num close de pura emoção): UM objeto concreto que representa a ideia da fala, em português, 1 a 2 palavras (ex.: cerebro, relogio,
    dinheiro, coracao, cafe). Preferir os que já existem: {", ".join(objs)}. Pode inventar outro (será desenhado).
    Parâmetro depois de ":" para celular/placa/botao (texto na tela), ex.: "celular:EU??". Vazio se não precisar.
 txt: a piada/palavra-chave em MAIÚSCULAS, 1 a 3 palavras — SÓ em ~1/3 das cenas (nos momentos-chave: gancho,
    virada, final). No resto deixe VAZIO: a imagem conta sozinha e a legenda já mostra a fala.
 cor: cor do txt — vermelho | azul | laranja | verde | tinta
 fx: efeito opcional — {" | ".join(EFEITOS)}
Use as poses de AÇÃO quando a fala tem ação (bocejo, dormindo, corre, come, empurra, tonto): o Bob FAZ o que a fala
diz. Varie os moldes (nunca o mesmo em cenas seguidas) e alterne emoções. Uma etiqueta por fala, na ordem.

TÍTULO: {r.get('titulo', '')}
FALAS:
{falas}
"""


# ---------------------------------------------------------------- layout (código, grátis)

def _pessoa(quem: str, pose: str, x: float, olha: int, fig: str = "", **extra) -> dict:
    e = {"tipo": quem, "x": x, "olha": olha, "pose_nome": pose, **POSES.get(pose, POSES["calmo"]), **extra}
    for p in (fig or "").replace(",", "+").split("+"):
        p = _chave(p).replace(" ", "_")
        if p in ("policia", "chef", "piloto", "astronauta", "coroa", "cartola", "capacete_obra", "formatura", "bone",
                 "cowboy", "mago", "pirata"):
            e["chapeu"] = p
        elif p in ("gravata", "jaleco", "capa", "distintivo", "avental", "colete", "medalha"):
            e["roupa"] = p
        elif p in ("oculos", "sol", "grau"):
            e["oculos"] = "sol" if p == "sol" else "grau"
        elif p == "bigode":
            e["bigode"] = True
    return e


def _objeto(spec: str, x: float, y: float, escala: float, bib: dict, entra: float = 0.3) -> dict | None:
    if not spec:
        return None
    nome, _, param = spec.partition(":")
    achado = _achar(nome, bib)
    if not achado:
        return None
    tipo, info = achado
    if tipo == "pronto":
        t, base, campo = PRONTOS[info["nome"]]
        e = {"tipo": t, "x": x, "y": y, "tam": base * escala, "entra": entra}
        if t in ("placa", "botao"):
            e.update(txt=_texto(param or nome).upper()[:12], w=300 * escala, h=120 * escala, txt_tam=50 * escala)
        elif campo and param:
            e[campo] = _texto(param)[:10]
        if t == "celular" and not param:
            e["onda_audio"] = True
        return e
    if info.get("svg"):  # objeto desenhado por ilustrador/pacote (dados/svg/), no traço do canal
        return {"tipo": "svg", "arquivo": info["svg"], "x": x, "y": y, "tam": 1.5 * escala, "entra": entra,
                "mexe": info.get("mexe", "")}
    return {"tipo": "desenho", "x": x, "y": y, "tam": 1.5 * escala, "entra": entra, "mexe": info.get("mexe", ""),
            "formas": info["formas"]}


_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")


def _texto(t: str) -> str:
    """A letra de mão não tem índice/expoente (O₂ virava quadradinho)."""
    return t.translate(_SUB)


def montar(et: dict, bib: dict, i: int = 0) -> dict:
    """Etiqueta -> cena completa do animacao_codigo, pelos moldes. `i` (nº da cena) varia entrada e câmera."""
    m = et.get("m") if et.get("m") in MOLDES else "solo"
    pb, pa = et.get("bob") or "explica", et.get("amigo") or ""
    obj, fx = et.get("obj", ""), et.get("fx", "")
    els, foco, camera = [], (540, 800), CAMERAS[i % len(CAMERAS)]
    partes = [p.strip() for p in obj.split("|") if p.strip()]
    if m in ("divide", "lista") and len(partes) < 2:
        m = "solo"  # sem os objetos da comparação/lista, vira cena simples
    if m == "gigante":
        o = _objeto(partes[0] if partes else obj, 640, 600, 1.9, bib, 0.15)
        els.append(_pessoa("bob", pb if pb != "explica" else "surpreso", 230, 1, et.get("fig", ""), escala=0.85))
        foco, boca = (600, 700), (240, 850)
    elif m == "divide":
        els.append({"tipo": "desenho", "x": 540, "y": 700, "fixo": True, "formas": [
            {"f": "linha", "pts": [[0, -330], [0, 420]], "cor": "tinta", "larg": 8}]})
        a = _objeto(partes[0], 300, 620, 0.75, bib, 0.2)
        o = _objeto(partes[1], 780, 620, 0.75, bib, 0.7)
        if a:
            els += [a, {"tipo": "xis", "x": 300, "y": 620, "tam": 90, "entra": 0.5}]
        els.append(_pessoa("bob", pb, 780, -1, et.get("fig", ""), escala=0.75, entra=0.9))
        camera, boca = "fixa", (780, 900)
    elif m == "lista":
        for k, p in enumerate(partes[:3]):
            ob = _objeto(p, 250 + 290 * k, 560, 0.5, bib, 0.2 + 0.45 * k)
            if ob:
                els.append(ob)
        o = None
        els.append(_pessoa("bob", pb, 540, 1, et.get("fig", ""), escala=0.9))
        camera, boca = "fixa", (560, 780)
    elif m == "dupla" or (pa and m == "solo"):
        els.append(_pessoa("bob", pb, 300, 1, et.get("fig", "")))
        els.append(_pessoa("amigo", pa or "surpreso", 780, -1, et.get("fig_amigo", ""), entra=0.25))
        o = _objeto(obj, 540, 990, 0.5, bib)  # no chão, entre os dois (o alto é do texto)
        boca = (350, 690)
    elif m == "close":
        els.append(_pessoa("bob", pb, 540, 1, et.get("fig", ""), escala=1.15))
        o = _objeto(obj, 840, 620, 0.55, bib, 0.5)
        foco, boca = (540, 560), (570, 580)
    elif m == "objeto":
        o = _objeto(obj, 600, 640, 1.15, bib, 0.1)
        els.append(_pessoa("bob", pb, 250, 1, et.get("fig", ""), escala=0.95))
        foco, boca = (600, 640), (270, 770)
    elif m == "pensa":
        els.append(_pessoa("bob", pb if pb != "explica" else "pensando", 300, 1, et.get("fig", "")))
        els.append({"tipo": "balao", "x": 700, "y": 480, "w": 440, "h": 320, "cauda": [420, 580], "entra": 0.2})
        o = _objeto(obj, 700, 480, 0.6, bib, 0.45)
        boca = (340, 690)
    elif m == "segura":
        els.append(_pessoa("bob", pb if pb in ("feliz", "orgulhoso", "surpreso", "chocado") else "segura", 380, 1,
                           et.get("fig", ""), braco_d=[150, -40]))
        o = _objeto(obj, 560, 740, 0.55, bib, 0.2)
        boca = (420, 690)
    else:  # solo
        els.append(_pessoa("bob", pb, 320, 1, et.get("fig", "")))
        o = _objeto(obj, 730, 720, 0.9, bib)
        boca = (370, 690)
    if o:
        els.append(o)
    for k, e in enumerate(els):  # entradas variadas (pop, desliza, cai, cresce), sem repetir padrão entre cenas
        if e["tipo"] not in ("bob", "amigo", "balao") and not e.get("fixo"):
            e["anim"] = ANIMS[(i + k) % len(ANIMS)]
    if "zzz" in fx:
        for k in range(3):
            els.append({"tipo": "texto", "txt": "z", "x": 430 + k * 45, "y": 470 - k * 55, "tam": 50 + k * 18,
                        "cor": "azul", "entra": 0.3 + k * 0.35, "rot": 0})
    if "ondas" in fx:
        els.append({"tipo": "ondas", "x": boca[0], "y": boca[1], "ang": 0, "alcance": 260, "n": 3})
    if "vibra" in fx:
        els.append({"tipo": "zigue", "de": [boca[0] + 40, boca[1] - 40], "ate": [boca[0] + 260, boca[1] - 40],
                    "cor": "laranja", "entra": 0.3})
    if "estrelas" in fx:
        els.append({"tipo": "estrelas", "x": 540 if m == "close" else 320, "y": 430})
    if "xis" in fx and o:
        els.append({"tipo": "xis", "x": o["x"], "y": o["y"], "tam": 70, "entra": 0.9})
    if "interrogacao" in fx:
        els.append({"tipo": "interrogacao", "x": 320 if m != "close" else 820, "y": 330, "tam": 150, "entra": 0.4})
    if et.get("txt"):
        tx = 560 if m not in ("close", "pensa") else (540 if m == "pensa" else 600)
        ty = 265 if m in ("pensa", "close") else 360
        els.append({"tipo": "texto", "txt": _texto(et["txt"]), "x": tx, "y": ty, "tam": 95 if m in ("pensa", "close") else 110,
                    "cor": et.get("cor") if et.get("cor") in ac.CORES else "vermelho", "entra": 0.35})
    lugar = et.get("lugar", "") if et.get("lugar") in LUGARES else ""
    cena = {"camera": camera, "foco": list(foco), "susto": "susto" in fx, "elementos": els,
            "cenario": "" if lugar == "padrao" else lugar, "clima": "chuva" if "chuva" in fx else "",
            # padrão desde 28/09/2026: Bob "vivo" (linha de ação); MILIONERE_CORPO=palito volta ao Bob antigo
            "corpo": "" if os.environ.get("MILIONERE_CORPO") == "palito" else "vivo",
            # transição no lugar do corte seco: soco no impacto, desliza/iris alternando no resto
            "transicao": "soco" if "susto" in fx or m == "close" else TRANSICOES[i % len(TRANSICOES)]}
    return cenas_codigo.consertar(cena)[0]


def enxugar_textos(etiquetas: list[dict]) -> list[dict]:
    """Texto na tela em no máximo ~1/3 das cenas e nunca em duas seguidas (fica o do gancho e dos momentos-chave)."""
    saida, anterior = [], False
    limite = max(2, round(len(etiquetas) / 3))
    usados = 0
    for k, e in enumerate(etiquetas):
        e = dict(e)
        chave = k == 0 or k == len(etiquetas) - 1
        if e.get("txt") and (chave or (not anterior and usados < limite)):
            usados += 1
            anterior = True
        else:
            e["txt"] = "" if not chave else e.get("txt", "")
            anterior = bool(e.get("txt"))
        saida.append(e)
    return saida


def variar(etiquetas: list[dict]) -> list[dict]:
    """Anti-repetição por código (grátis): nunca o mesmo molde em cenas seguidas."""
    troca = {"solo": "segura", "segura": "solo", "close": "solo", "dupla": "solo", "objeto": "gigante",
             "gigante": "objeto", "pensa": "solo", "divide": "solo", "lista": "solo"}
    saida = []
    for k, e in enumerate(etiquetas):
        e = dict(e)
        if k and e.get("m") == saida[-1].get("m"):
            e["m"] = troca.get(e.get("m"), "solo")
            if e["m"] == saida[-1].get("m"):
                e["m"] = "close"
        saida.append(e)
    return saida


# ---------------------------------------------------------------- tudo junto

def dirigir(r: dict, log=print) -> Path:
    inicio = time.time()
    bib = biblioteca()
    log(f"etiquetando as {len(r['cenas'])} cenas (Claude, modelo {caminhos.MODELO_ROTEIRO})")
    with llm.medidor.etapa("etiquetas"):
        resp = llm.chamar(_prompt(r, bib), SCHEMA)
    etiquetas = resp.get("cenas", [])[:len(r["cenas"])]
    etiquetas += [{"m": "solo", "bob": "explica", "txt": ""}] * (len(r["cenas"]) - len(etiquetas))
    etiquetas = enxugar_textos(variar(etiquetas))
    nomes = {_chave(p.partition(":")[0]) for e in etiquetas for p in e.get("obj", "").split("|")}
    faltam = sorted(n for n in nomes if n and not _achar(n, bib))
    if faltam:
        log(f"desenhando {len(faltam)} objeto(s) novo(s) (Opus, uma vez só): {', '.join(faltam)}")
        try:
            desenhar_novos(faltam, log)
        except Exception as e:  # noqa: BLE001 - objeto que não saiu some da cena; o vídeo segue
            log(f"objetos novos falharam: {str(e)[:200]}")
        bib = biblioteca()
    cenas = [montar(e, bib, i) for i, e in enumerate(etiquetas)]
    trabalho = caminhos.PRODUCAO / "cenas_codigo"
    trabalho.mkdir(parents=True, exist_ok=True)
    (trabalho / f"{r['slug']}.json").write_text(json.dumps({"slug": r["slug"], "etiquetas": etiquetas, "cenas": cenas},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    pasta = caminhos.PRODUCAO / "midia" / r["slug"]
    for velho in pasta.glob("cena_*"):
        velho.unlink()
    for i, c in enumerate(cenas, 1):
        ac.renderizar({**c, "duracao": DURACAO}, pasta / f"cena_{i:02d}.mp4")
    log(f"cenas prontas em {time.time() - inicio:.0f}s")
    return pasta


if __name__ == "__main__":
    roteiro = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(dirigir(roteiro[0] if isinstance(roteiro, list) else roteiro))
