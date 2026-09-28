"""Diretor das cenas em código (opção de imagens "animação em código"): do roteiro narrado aprovado às cenas
animadas, sem GPU.

1. o Claude descreve cada cena em JSON (elenco, objetos, textos), no formato do animacao_codigo.py;
2. o código conserta a geometria (texto fora da tela, personagem cortado, texto em cima de cabeça, tipo desconhecido);
3. renderiza as prévias numa folha e o Claude olha uma vez e corrige as cenas ruins (uma rodada só: não segura o vídeo);
4. renderiza producao/midia/<slug>/cena_NN.mp4, que a montagem usa como mídia da cena.

Uso avulso: python cenas_codigo.py roteiro.json   (roteiro no formato do produzir.py, lista com um roteiro)
"""

import json
import math
import sys
import time
from pathlib import Path

import cairo
from PIL import Image

import animacao_codigo as ac
import caminhos
import llm

EXEMPLO = caminhos.PRODUCAO / "cenas_codigo" / "propria-voz-codigo.json"  # piloto aprovado (27/09/2026)
DURACAO = 7  # s por cena renderizada; a montagem corta no tempo da fala (e congela se faltar)

CATALOGO = """
TELA DE TRABALHO: 1080 de largura. A parte visível no vídeo vai de x=140 a x=940 (fora disso é cortado).
Chão: os pés de todo personagem ficam no chão automaticamente (não há "y" para personagem).
Cabeça de um personagem de escala 1: centro em y≈620, raio 135. Ombro em y≈795. Boca em y≈675.
Faixa dos TEXTOS grandes: y entre 280 e 440 (acima das cabeças). A legenda do vídeo fica no chão: não escreva lá.
Objetos: entre y 450 e 1150 (1150 = altura do chão). Mesa/celular apoiado: y≈950 é a altura de uma mesa.

PERSONAGENS (tipo "bob" = cabeça branca, protagonista; "amigo" = cabeça azul, reage):
  x (250 a 830), olha (1 = para a direita, -1 = esquerda), escala (1; close-up até 1.3, e então x=540),
  olhos: normal | arregalados | fechados | feliz | lado
  sobrancelhas: neutra | levantadas | preocupadas | bravo | uma (uma arqueada: desconfiado/pensando) | nenhuma
  boca: sorriso | grande (gargalhada) | aberta (grito/susto/cantando) | o (espanto) | triste | nervosa | reta | sussurro
  fala: true (boca mexendo no ritmo; use quando o personagem está explicando)
  braco_e / braco_d: baixo | cintura | acena | cima | aponta | frente | rosto (mão no rosto) | boca | ombro_amigo |
       joinha | segura | orelha | tras | encolhe  — ou [dx, dy] = mão relativa ao ombro (dx para fora do corpo, até ~230)
  suor, corado, tremer, pula: true
  FIGURINO (o Bob VIRA o que a fala diz: falou de polícia, ele aparece de policial; de chef, de chef...):
    chapeu: policia | chef | piloto | astronauta | coroa | cartola | capacete_obra | formatura | bone | cowboy |
            mago | pirata
    roupa: gravata | jaleco (médico/cientista) | capa (herói/rei) | distintivo | avental | colete | medalha
    oculos: grau | sol     bigode: true
  entra: segundos até aparecer (com "pop")
  Dois personagens: separados por pelo menos 280 em x (ex.: 300 e 780), olhando um para o outro.

OBJETOS PRONTOS (todos aceitam "entra": segundos; x,y = centro):
  celular {x,y,tam, play:true, tela:"TXT", onda_audio:true}
  ondas {x,y, ang (graus; 0 = direita, -90 = cima), alcance, n, larg, vel, cor}  ondas de som saindo
  zigue {de:[x,y], ate:[x,y], cor, dentes, amp, larg, desenha}  vibração/choque/raio em zigue-zague
  seta {de:[x,y], ate:[x,y], curva:[x,y], cor, rotulo:"TXT", rotulo_em:[x,y], larg}
  balao {x,y,w,h, cauda:[x,y] (ponto perto da cabeça), fala:true p/ balão de fala}  depois coloque objetos dentro
  orelha, lampada, microfone, caixa_som, mesa {x,y,w}, xis {x,y,tam} (X vermelho), rato {x,y,tam,fala}
  placa {x,y,w,h,txt,txt_tam,cor}, botao {x,y,w,h,txt,txt_tam,cor}, interrogacao {x,y,tam,txt,cor},
  estrelas {x,y} (tontura), cabeca_por_dentro {x,y}
  texto {x,y,txt,tam (70 a 150),cor,rot}: a PIADA/palavra-chave da cena, 1 a 3 palavras, MAIÚSCULAS
  desenho {x,y,tam,mexe: flutua|gira|pulsa|balanca, formas:[...]}  QUALQUER OUTRO OBJETO, desenhado por você com
     formas relativas a (x,y): {"f":"circulo","x","y","r"} {"f":"elipse","x","y","rx","ry","rot"}
     {"f":"linha"|"poligono","pts":[[x,y],...]} {"f":"arco","x","y","r","de","ate"} {"f":"texto","x","y","txt","tam"}
     cada forma com "cor" (contorno; "nenhuma" = sem), "preenche", "larg" (4 a 8). Cores: tinta, azul, laranja,
     vermelho, amarelo, verde, branco, cinza ou "#rrggbb". Desenhe como doodle: poucas formas (5 a 25), contorno
     preto, cores chapadas, reconhecível de longe (planeta, coração, relógio, dinheiro, cérebro, comida, bicho...).
CÂMERA da cena: "camera": aproxima (padrão) | fixa | afasta; "susto": true treme no início; "foco":[x,y] do zoom.
Ordem dos elementos = ordem de desenho (o que vem depois fica por cima).
"""

REGRAS = """
Você é o diretor de arte do canal "Bob Curioso" (Shorts em doodle). Para CADA cena do roteiro, descreva a imagem
animada que ENCENA a fala, como nos vídeos aprovados:
- emoção e pose do Bob combinando com a frase (susto, dúvida, orgulho, vergonha, explicando...);
- SEMPRE ilustre o que está sendo falado: cada fala tem que virar imagem na hora, é isso que dá dinâmica;
- quando a fala cita uma profissão, papel ou pessoa (policial, médico, rei, cientista, cozinheiro, piloto...),
  o Bob (ou o Amigo) aparece VESTIDO disso com o figurino;
- a IDEIA da fala vira OBJETO na tela (use os objetos prontos ou "desenho" para qualquer coisa nova);
- uma piada/palavra-chave de 1 a 3 palavras em "texto", no alto (y 280-440), em quase toda cena;
- o Amigo aparece para reagir quando a fala envolve outra pessoa ou pede reação (nem sempre);
- movimento: objetos entram em sequência (entra 0.2, 0.5, 0.9...), ondas/zigue/desenho com "mexe" dão vida;
- variedade: não repita a mesma composição em cenas seguidas; alterne close (escala 1.3) com cena aberta;
- o Bob (ou o Amigo) aparece em TODA cena: é o canal dele. Cena sem personagem não é aceita;
- objetos GRANDES e legíveis: o objeto principal ocupa uns 250 a 400 px (num "desenho", use coordenadas nessa escala,
  ex.: círculo de raio 120, não 30). Objeto pequeno some no celular;
- nada de texto longo; nada fora da faixa visível (x 140 a 940).
Devolva uma cena para cada fala, na mesma ordem.
"""

SCHEMA = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {
        "type": "object",
        "properties": {"camera": {"type": "string"}, "susto": {"type": "boolean"},
                       "foco": {"type": "array", "items": {"type": "number"}},
                       "elementos": {"type": "array", "items": {"type": "object"}}},
        "required": ["elementos"]}}},
    "required": ["cenas"],
}

SCHEMA_REVISAO = {
    "type": "object",
    "properties": {"correcoes": {"type": "array", "items": {
        "type": "object",
        "properties": {"cena": {"type": "integer"}, "problema": {"type": "string"},
                       "elementos": {"type": "array", "items": {"type": "object"}},
                       "camera": {"type": "string"}},
        "required": ["cena", "problema", "elementos"]}}},
    "required": ["correcoes"],
}


# ---------------------------------------------------------------- conserto automático

_medidor = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 4, 4))


def _largura_texto(txt: str, tam: float) -> float:
    _medidor.select_font_face(ac.FONTE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    _medidor.set_font_size(tam)
    return max(_medidor.text_extents(lin).x_advance for lin in txt.split("\n"))


def _quebrar(txt: str) -> str:
    """Frase de 2+ palavras que não cabe grande vira 2 linhas equilibradas (melhor que encolher até sumir)."""
    palavras = txt.replace("\n", " ").split()
    if len(palavras) < 2:
        return txt
    melhor = min(range(1, len(palavras)),
                 key=lambda k: abs(len(" ".join(palavras[:k])) - len(" ".join(palavras[k:]))))
    return " ".join(palavras[:melhor]) + "\n" + " ".join(palavras[melhor:])


def _num(v, padrao):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else padrao


def consertar(cena: dict) -> tuple[dict, list[str]]:
    """Ajustes determinísticos; devolve a cena e o que foi mexido."""
    notas = []
    els = []
    for e in cena.get("elementos", []):
        if not isinstance(e, dict) or e.get("tipo") not in ("bob", "amigo", *ac.OBJETOS):
            notas.append(f"tipo desconhecido removido: {e.get('tipo') if isinstance(e, dict) else e}")
            continue
        els.append(e)
    if not any(e["tipo"] in ("bob", "amigo") for e in els):  # cena sem elenco (ou vazia): o Bob entra explicando
        els.insert(0, {"tipo": "bob", "x": 300, "olha": 1, "fala": True, "braco_d": "aponta"})
        notas.append("cena sem elenco: Bob adicionado")
    cabecas = []
    for e in els:
        if e["tipo"] in ("bob", "amigo"):
            esc = min(1.35, max(0.6, _num(e.get("escala"), 1.0)))
            e["escala"] = esc
            lim = 135 * esc + 120
            x = _num(e.get("x"), 540)
            e["x"] = min(1080 - lim, max(lim, x))
            if e["x"] != x:
                notas.append(f"{e['tipo']} trazido para dentro (x {x:.0f} -> {e['x']:.0f})")
            # chapéu alto (chef, cartola, mago) aumenta a "cabeça" para cima: o texto não pode encostar nele
            alto = {"chef": 110, "cartola": 150, "mago": 200, "coroa": 60, "astronauta": 40}.get(e.get("chapeu"), 30 if e.get("chapeu") else 0)
            if (e.get("corpo") or cena.get("corpo")) == "vivo":  # Bob vivo: cabeça menor e mais alta (pescoço)
                cabecas.append((e["x"], ac.PES - 700 * esc, 75 * esc))
            else:
                cabecas.append((e["x"], ac.PES - 560 * esc - alto * esc / 2, 135 * esc + alto * esc / 2))
    # objetos grandes também são obstáculos: o texto não pode cobrir a "ideia" da cena
    raio_base = {"desenho": 110, "svg": 110, "celular": 140, "caixa_som": 230, "lampada": 90, "microfone": 100}
    for e in els:
        if e["tipo"] in raio_base and isinstance(e.get("x"), (int, float)) and isinstance(e.get("y"), (int, float)):
            r = raio_base[e["tipo"]] * _num(e.get("tam"), 1.0)
            if r > 70:
                cabecas.append((e["x"], e["y"], r))
    for e in els:
        if e["tipo"] != "texto" or not e.get("txt"):
            continue
        tam = min(160, max(40, _num(e.get("tam"), 110)))
        txt = str(e["txt"]) if len(str(e["txt"])) <= 24 else str(e["txt"])[:24].rsplit(" ", 1)[0]
        if _largura_texto(txt, tam) > 780 and "\n" not in txt:
            txt = _quebrar(txt)
        while _largura_texto(txt, tam) > 780 and tam > 50:
            tam -= 8
        e["tam"], e["txt"] = tam, txt
        meia = _largura_texto(txt, tam) / 2
        x, y = _num(e.get("x"), 540), _num(e.get("y"), 360)
        e["x"] = min(940 - meia, max(140 + meia, x))
        alt = tam * 0.55 * (txt.count("\n") + 1)  # meia altura do bloco de texto
        for cx, cy, r in cabecas:  # texto em cima de uma cabeça: sobe para a faixa dos textos
            if abs(y - cy) < r + alt and abs(e["x"] - cx) < r + meia:
                y = min(y, cy - r - alt - 10)
        y = max(250, y)
        for _ in range(4):  # não coube acima (chapéu alto, close): vai para o lado da cabeça e diminui um pouco
            bate = next((h for h in cabecas if abs(y - h[1]) < h[2] + alt and abs(e["x"] - h[0]) < h[2] + meia), None)
            if not bate:
                break
            tam = max(72, tam * 0.88)  # desvia, mas continua legível no celular
            meia, alt = _largura_texto(txt, tam) / 2, tam * 0.55 * (txt.count("\n") + 1)
            lado = 1 if bate[0] < 540 else -1
            e["x"] = min(940 - meia, max(140 + meia, bate[0] + lado * (bate[2] + meia + 15)))
        e["tam"], e["y"] = round(tam), y
        if (e["x"], e["y"]) != (x, _num(e.get("y"), 360)):
            notas.append(f"texto «{txt}» reposicionado")
    cena = {**cena, "elementos": els, "duracao": DURACAO}
    if cena.get("camera") not in (None, "aproxima", "fixa", "afasta", "lado"):
        cena["camera"] = "aproxima"
    return cena, notas


# ---------------------------------------------------------------- Claude

def _prompt(r: dict) -> str:
    exemplo = ""
    if EXEMPLO.exists():
        ex = json.loads(EXEMPLO.read_text(encoding="utf-8"))["cenas"]
        exemplo = ("\nEXEMPLO APROVADO (vídeo 'por que você odeia a própria voz', cenas 2, 5 e 8):\n" +
                   "\n".join(json.dumps(ex[i], ensure_ascii=False) for i in (1, 4, 7) if i < len(ex)))
    falas = "\n".join(f"{i}. «{c['fala']}»" + (f"  (ideia da imagem: {c['imagem']})" if c.get("imagem") else "")
                      for i, c in enumerate(r["cenas"], 1))
    return f"{REGRAS}\n{CATALOGO}{exemplo}\n\nTÍTULO: {r.get('titulo', '')}\nROTEIRO ({len(r['cenas'])} cenas):\n{falas}\n"


def folha(cenas: list[dict], destino: Path) -> Path:
    """Prévias (quadro de 1,6 s de cada cena) numa folha numerada, para o Claude revisar."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    col, lw, lh = 5, 270, 480
    linhas = math.ceil(len(cenas) / col)
    img = Image.new("RGB", (col * lw, linhas * (lh + 40)), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    tmp = destino.with_suffix(".tmp.png")
    for i, c in enumerate(cenas):
        ac.quadro(c, round(1.6 * ac.FPS)).write_to_png(str(tmp))
        x, y = (i % col) * lw, (i // col) * (lh + 40)
        img.paste(Image.open(tmp).convert("RGB").resize((lw, lh)), (x, y + 40))
        d.text((x + 8, y + 8), f"CENA {i + 1}", fill="black")
    tmp.unlink(missing_ok=True)
    img.save(destino)
    return destino


def revisar(r: dict, cenas: list[dict], pasta: Path, log=print) -> list[dict]:
    """Uma rodada: o Claude olha a folha e reescreve só as cenas com problema visível."""
    arq = folha(cenas, pasta / "folha.png")
    prompt = (f"Abra a imagem {arq.name} (pasta {pasta}). São as prévias das cenas de um Short em doodle, em ordem, "
              "cada uma com a fala abaixo. Aponte SÓ problemas visíveis e graves: texto cortado ou ilegível, objeto "
              "irreconhecível, coisas sobrepostas escondendo o rosto, personagem cortado, cena que não tem a ver com a "
              "fala, cena vazia. Para cada cena com problema devolva os elementos completos corrigidos (mesmo formato). "
              "Se estiver tudo bom, devolva correcoes vazio.\n" + CATALOGO + "\nFALAS:\n" +
              "\n".join(f"{i}. «{c['fala']}»\nATUAL: {json.dumps(cenas[i - 1]['elementos'], ensure_ascii=False)}"
                        for i, c in enumerate(r["cenas"], 1)))
    try:
        resp = llm.chamar(prompt, SCHEMA_REVISAO, ler_arquivos_em=pasta, modelo=caminhos.MODELO_CENAS, papel="juiz")
    except Exception as e:  # noqa: BLE001 - a revisão é bônus: sem ela, seguem as cenas consertadas
        log(f"revisão visual das cenas pulada: {str(e)[:200]}")
        return cenas
    for cor in resp.get("correcoes", []):
        n = cor.get("cena")
        if isinstance(n, int) and 1 <= n <= len(cenas) and cor.get("elementos"):
            nova, _ = consertar({**cenas[n - 1], "elementos": cor["elementos"], "camera": cor.get("camera") or cenas[n - 1].get("camera")})
            cenas[n - 1] = nova
            log(f"cena {n} refeita na revisão: {cor.get('problema', '')[:120]}")
    return cenas


def dirigir(r: dict, log=print, revisao: bool = True) -> Path:
    """Roteiro -> producao/midia/<slug>/cena_NN.mp4. Devolve a pasta de mídia."""
    inicio = time.time()
    log(f"desenhando as {len(r['cenas'])} cenas em código (Claude)")
    resp = llm.chamar(_prompt(r), SCHEMA, modelo=caminhos.MODELO_CENAS, timeout=900)
    brutas = resp.get("cenas", [])
    cenas = []
    for i in range(len(r["cenas"])):
        c, notas = consertar(brutas[i] if i < len(brutas) else {"elementos": [{"tipo": "bob", "x": 540, "fala": True}]})
        cenas.append(c)
        for n in notas:
            log(f"cena {i + 1}: {n}")
    trabalho = caminhos.PRODUCAO / "cenas_codigo"
    if revisao:
        cenas = revisar(r, cenas, trabalho / f"{r['slug']}_revisao", log)
    arq = trabalho / f"{r['slug']}.json"
    arq.write_text(json.dumps({"slug": r["slug"], "cenas": cenas}, ensure_ascii=False, indent=1), encoding="utf-8")
    pasta = caminhos.PRODUCAO / "midia" / r["slug"]
    for velho in pasta.glob("cena_*"):
        velho.unlink()
    t = time.time()
    for i, c in enumerate(cenas, 1):
        try:
            ac.renderizar(c, pasta / f"cena_{i:02d}.mp4")
        except Exception as e:  # noqa: BLE001 - cena quebrada vira o Bob explicando, não derruba o vídeo
            log(f"cena {i} falhou no render ({str(e)[:120]}); vai o Bob explicando")
            ac.renderizar({"duracao": DURACAO, "elementos": [{"tipo": "bob", "x": 540, "fala": True}]},
                          pasta / f"cena_{i:02d}.mp4")
    log(f"cenas renderizadas em {time.time() - t:.0f}s (total {time.time() - inicio:.0f}s)")
    return pasta


# legenda menor, no chão bege (abaixo dos pés do elenco), aprovada no piloto de 27/09/2026
AJUSTES_LEGENDA = {"font_size": 56, "subtitle_position": "custom", "custom_position": 85}


if __name__ == "__main__":
    roteiro = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))[0]
    print(dirigir(roteiro, revisao="--sem-revisao" not in sys.argv))
