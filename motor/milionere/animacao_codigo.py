"""Animação em código (opção ao lado de "IA no pod"): o elenco do Bob Curioso desenhado em vetor (cairo) e animado
quadro a quadro, sem GPU. Cada cena é uma descrição (dict/JSON) com personagens, objetos e textos; o renderizador
grava producao/midia/<slug>/cena_NN.mp4, que a montagem do motor já usa como mídia da cena (prioridade total).

Traço de doodle: linha levemente irregular, como desenho à mão, e PARADA: a irregularidade depende da forma do traço
(índice do ponto e comprimento), não da posição na tela, então personagem respirando ou câmera andando não tremem.

Uso:
    python animacao_codigo.py cenas.json            # renderiza todas as cenas do arquivo
    python animacao_codigo.py cenas.json --so 3 5   # só as cenas 3 e 5
    python animacao_codigo.py cenas.json --png      # um quadro por cena (prévia rápida, sem vídeo)

cenas.json: {"slug": "...", "cenas": [{"duracao": 5, "camera": "aproxima", "elementos": [...]}, ...]}
"""

import argparse
import json
import math
import os
import subprocess
from pathlib import Path

import cairo
import imageio_ffmpeg

import caminhos

W, H, FPS = 1080, 1920, 30
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# paleta do canal (docs/animacoes.md): parede branca, chão bege, Bob branco, Amigo azul
PAREDE = (0.985, 0.980, 0.965)
CHAO = (0.925, 0.870, 0.765)
TINTA = (0.08, 0.08, 0.10)
AZUL = (0.35, 0.62, 0.93)
LARANJA = (0.98, 0.55, 0.15)
VERMELHO = (0.90, 0.20, 0.20)
AMARELO = (1.0, 0.85, 0.25)
VERDE = (0.30, 0.75, 0.40)
CORES = {"tinta": TINTA, "azul": AZUL, "laranja": LARANJA, "vermelho": VERMELHO, "amarelo": AMARELO,
         "verde": VERDE, "branco": (1, 1, 1), "cinza": (0.6, 0.6, 0.62)}
PISO = 1120          # linha parede/chão
PES = 1180           # onde os pés tocam
FONTE = "Segoe Print"  # letra de mão (Windows); cai na padrão do cairo se não houver
FONTE_LIMPA = "Arial Rounded MT Bold"  # traço "limpo": arredondada e moderna
TRACO = 7
# enquadramento: as cenas são descritas numa tela "de trabalho" e ampliadas em volta dos pés, para o elenco ocupar
# o quadro vertical (texto no alto ~y 520 no vídeo, legenda do motor em ~66% da altura, na altura das pernas)
ENQUADRA, PES_TELA = 1.3, 1560


# ---------------------------------------------------------------- traço de doodle

class Doodle:
    """Contexto de desenho com linha irregular fixa (o 'boiling line', que mudava a cada 4 quadros, foi reprovado:
    o público achou que a animação tremia)."""

    def __init__(self, ctx: cairo.Context, quadro: int, traco: str = ""):
        self.c = ctx
        self.ferve = 0
        # "rough" (opção): traço duplo com leve arco e preenchimento desencaixado, no estilo rough.js
        # padrão = "limpo" (28/09/2026: o tremido e o traço duplo foram reprovados); "doodle" e "rough" seguem como opção
        traco = traco or os.environ.get("MILIONERE_TRACO", "") or "limpo"
        self.rough = traco == "rough"
        # "limpo" (opção): linha lisa, sem tremida, fonte arredondada e texto reto: visual clean/sofisticado
        self.limpo = traco == "limpo"

    def _ruido(self, x: float, y: float, k: int = 0) -> float:
        h = math.sin(x * 12.9898 + y * 78.233 + (self.ferve * 7 + k) * 37.719) * 43758.5453
        return (h - math.floor(h)) * 2 - 1

    def _caminho(self, seq, forma: int, amp: float, k: int, arco: float) -> list:
        """Pontos do traço: subdivide a cada ~30 px, tremida fixa pela forma e, no rough, um arco ('bowing') por
        segmento, como a mão que curva a linha reta."""
        pts = []
        for s, ((x0, y0), (x1, y1)) in enumerate(zip(seq, seq[1:])):
            L = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(L / 30))
            nx, ny = (-(y1 - y0) / L, (x1 - x0) / L) if L else (0, 0)
            curva = self._ruido(s * 2.1 + k, forma, 5) * min(L * arco, 14)
            for i in range(n):
                u = i / n
                b = math.sin(math.pi * u) * curva
                pts.append((x0 + (x1 - x0) * u + nx * b, y0 + (y1 - y0) * u + ny * b))
        pts.append(seq[-1])
        return [(x + self._ruido(i * 1.37 + k, forma) * amp, y + self._ruido(forma, i * 1.37 + k, 1) * amp)
                for i, (x, y) in enumerate(pts)]

    def _tracar(self, pontos, fechar):
        c = self.c
        c.new_path()
        for i, (x, y) in enumerate(pontos):
            (c.move_to if i == 0 else c.line_to)(x, y)
        if fechar:
            c.close_path()

    def linha(self, pts, cor=TINTA, larg=TRACO, fechar=False, preencher=None, amp=2.2):
        """Polilinha com tremida perpendicular fixa; no modo rough, preenchimento desencaixado + traço duplo."""
        seq = list(pts) + ([pts[0]] if fechar else [])
        if len(seq) < 2:
            return
        if self.limpo:
            amp = 0.0
        c = self.c
        forma = round(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(seq, seq[1:])) / 10)
        if preencher:
            if self.rough:  # a tinta "vaza" um pouco para fora do contorno, como pintado à mão
                c.save()
                c.translate(4, 3)
                self._tracar(self._caminho(seq, forma, amp * 1.8, 7, 0.0), fechar)
                c.restore()
            else:
                self._tracar(self._caminho(seq, forma, amp, 0, 0.0), fechar)
            c.set_source_rgb(*preencher)
            c.fill()
        if cor:
            c.set_line_cap(cairo.LINE_CAP_ROUND)
            c.set_line_join(cairo.LINE_JOIN_ROUND)
            passadas = ((0, 1.0, larg * 0.85, 0.04), (3, 0.8, larg * 0.55, 0.06)) if self.rough else ((0, 1.0, larg, 0.0),)
            for k, alfa, lw, arco in passadas:
                self._tracar(self._caminho(seq, forma, amp * (2.0 if self.rough else 1), k, arco), fechar)
                c.set_source_rgba(*cor, alfa)
                c.set_line_width(lw)
                c.stroke()
        c.new_path()

    def circulo(self, x, y, r, cor=TINTA, larg=TRACO, preencher=None, amp=2.0):
        n = max(12, int(r / 3))
        self.linha([(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)],
                   cor, larg, True, preencher, amp)

    def elipse(self, x, y, rx, ry, cor=TINTA, larg=TRACO, preencher=None, rot=0.0):
        n = max(16, int(max(rx, ry) / 3))
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            px, py = rx * math.cos(a), ry * math.sin(a)
            pts.append((x + px * math.cos(rot) - py * math.sin(rot), y + px * math.sin(rot) + py * math.cos(rot)))
        self.linha(pts, cor, larg, True, preencher)

    def arco(self, x, y, r, a0, a1, cor=TINTA, larg=TRACO):
        n = max(6, int(abs(a1 - a0) * r / 20))
        self.linha([(x + r * math.cos(a0 + (a1 - a0) * i / n), y + r * math.sin(a0 + (a1 - a0) * i / n))
                    for i in range(n + 1)], cor, larg)

    def curva(self, p0, p1, p2, cor=TINTA, larg=TRACO, n=16):
        """Bézier quadrática (p1 = controle)."""
        pts = [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]
        self.linha(pts, cor, larg)
        return pts

    def ponto(self, x, y, r, cor=TINTA):
        self.c.arc(x, y, r, 0, 2 * math.pi)
        self.c.set_source_rgb(*cor)
        self.c.fill()

    def texto(self, x, y, txt, tam=90, cor=TINTA, contorno=(1, 1, 1), rot=0.0, negrito=True):
        c = self.c
        c.save()
        c.translate(x, y)
        if self.limpo:
            c.select_font_face(FONTE_LIMPA, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        else:
            c.rotate(rot + self._ruido(len(txt), 3) * 0.015)
            c.select_font_face(FONTE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if negrito else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(tam)
        linhas = txt.split("\n")  # várias linhas centralizadas no ponto (x, y)
        altura = tam * 1.05
        for k, lin in enumerate(linhas):
            e = c.text_extents(lin)
            c.move_to(-e.x_advance / 2, tam * 0.35 + (k - (len(linhas) - 1) / 2) * altura)
            c.text_path(lin)
        if contorno:
            c.set_source_rgb(*contorno)
            c.set_line_width(tam * 0.16)
            c.set_line_join(cairo.LINE_JOIN_ROUND)
            c.stroke_preserve()
        c.set_source_rgb(*cor)
        c.fill()
        c.restore()


# ---------------------------------------------------------------- tempo

def pop(t: float, ini: float, dur: float = 0.35) -> float:
    """Escala de entrada com 'estouro' (easeOutBack): 0 antes de ini, passa de 1 e volta."""
    if t < ini:
        return 0.0
    p = min(1.0, (t - ini) / dur)
    s = 1.9
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def suave(t: float, ini: float, dur: float) -> float:
    p = min(1.0, max(0.0, (t - ini) / dur))
    return p * p * (3 - 2 * p)


# ---------------------------------------------------------------- elenco

CABECA = {"bob": (1, 1, 1), "amigo": AZUL}

# mão relativa ao ombro (dx para o lado de fora do braço, dy para baixo), mais o lado para onde o cotovelo dobra
BRACOS = {
    "baixo": (40, 190), "cintura": (95, 80), "acena": (170, -150), "cima": (165, -200), "aponta": (215, -20),
    # "rosto" = mão no queixo (pensando); "cobre" = mãos tapando o rosto (vergonha)
    "frente": (170, 60), "rosto": (-5, -55), "cobre": (-25, -150), "boca": (-60, -100), "ombro_amigo": (230, -10), "joinha": (140, -60),
    "segura": (150, 20), "orelha": (35, -215), "tras": (-60, 170), "encolhe": (120, -95),
}


def _braco(d: Doodle, ox, oy, lado, pose, t, extra):
    if isinstance(pose, (list, tuple)):
        dx, dy = pose
    else:
        dx, dy = BRACOS.get(pose, BRACOS["baixo"])
    if pose == "acena":
        dx += 30 * math.sin(t * 12)
    hx, hy = ox + dx * lado, oy + dy
    # cotovelo: ponto médio empurrado para fora (IK simples, braço de ~115+115)
    mx, my = (ox + hx) / 2, (oy + hy) / 2
    dist = math.hypot(hx - ox, hy - oy)
    folga = math.sqrt(max(0.0, 115 ** 2 - (dist / 2) ** 2))
    nx, ny = -(hy - oy) / (dist or 1), (hx - ox) / (dist or 1)
    if nx * lado < 0:
        nx, ny = -nx, -ny
    ex, ey = mx + nx * folga * 0.6, my + ny * folga * 0.6 + (8 if dy > 0 else 0)
    if dy < -120 and dx > 60:  # mão acima do ombro e para fora: cotovelo abre para o lado (não atravessa o rosto)
        ex, ey = ox + lado * 150, oy - 30
    d.linha([(ox, oy), (ex, ey), (hx, hy)])
    d.circulo(hx, hy, 13, preencher=(1, 1, 1), larg=5)
    if pose == "joinha":
        d.linha([(hx, hy - 12), (hx, hy - 42)], larg=8)
    return hx, hy


def personagem(d: Doodle, e: dict, t: float):
    """e: quem (bob/amigo), x, olha (-1/1), olhos, sobrancelhas, boca, braco_e, braco_d, fala (boca mexe),
    suor, corado, tremer, pula, escala."""
    x = e.get("x", 540)
    esc = e.get("escala", 1.0) * pop(t, e.get("entra", 0), 0.4)
    if esc <= 0:
        return
    c = d.c
    c.save()
    respira = math.sin(t * 2.4 + x) * 5
    pulo = -abs(math.sin(t * 7)) * 45 if e.get("pula") else 0
    treme = math.sin(t * 70) * 5 if e.get("tremer") else 0
    c.translate(x + treme, PES)
    c.scale(esc, esc)
    olha = e.get("olha", 1)
    # sombra no chão
    c.save()
    c.scale(1, 0.18)
    c.arc(0, 0, 105 + pulo * 0.3, 0, 2 * math.pi)
    c.set_source_rgba(0, 0, 0, 0.10)
    c.fill()
    c.restore()
    if e.get("pula"):  # antecipação: amassa no chão antes de subir e ao cair (squash)
        chao = max(0.0, 1 - abs(math.sin(t * 7)) / 0.25)
        c.scale(1 + 0.10 * chao, 1 - 0.12 * chao)
    c.translate(0, pulo)
    cy, pesc, omb, quad = -560 + respira, -425 + respira, -385 + respira * 0.8, -195
    if e.get("roupa") == "capa":
        roupa(d, "capa", pesc, quad, olha, t)
    # pernas e corpo
    if e.get("corre"):  # pernas alternando (correndo/andando)
        for fase in (0, math.pi):
            a = math.sin(t * 12 + fase) * 0.6
            jx, jy = math.sin(a) * 100, quad + math.cos(a) * 100
            px, py = jx + math.sin(a - 0.5 * olha) * 95, min(0, jy + 95)
            d.linha([(0, quad), (jx, jy), (px, py), (px + 25 * olha, py)])
    else:
        d.linha([(0, quad), (-55, 0), (-80, 0)] if olha < 0 else [(0, quad), (-55, 0), (-30, 0)])
        d.linha([(0, quad), (55, 0), (30, 0)] if olha < 0 else [(0, quad), (55, 0), (80, 0)])
    d.linha([(0, pesc), (0, quad)])
    if e.get("roupa") != "capa":
        roupa(d, e.get("roupa"), pesc, quad, olha, t)
    _braco(d, 0, omb, -1, e.get("braco_e", "baixo"), t, e)
    # cabeça: inclina de leve ao falar (e quase nada parado), girando no pescoço
    inclina = math.sin(t * 6 + x) * 0.045 if e.get("fala") else math.sin(t * 1.3 + x) * 0.015
    c.save()
    c.translate(0, pesc)
    c.rotate(inclina)
    c.translate(0, -pesc)
    d.circulo(0, cy, 135, preencher=CABECA.get(e.get("quem", "bob"), (1, 1, 1)), larg=8)
    rosto(d, 0 + olha * 14, cy, e, t)
    # movimento secundário: o chapéu acompanha a cabeça com atraso (e mais forte no pulo)
    atraso = math.sin(t * 6 + x - 0.9) * 0.05 if e.get("fala") else 0.0
    atraso += math.sin(t * 7 - 1.2) * 0.08 if e.get("pula") else 0.0
    c.translate(0, cy - 135)
    c.rotate(atraso - inclina * 0.5)
    c.translate(0, -(cy - 135))
    acessorios(d, e, 0, cy, olha, t)
    c.restore()
    _braco(d, 0, omb, 1, e.get("braco_d", "baixo"), t, e)  # braço da frente por cima da cabeça (mão no rosto)
    c.restore()


# ---------------------------------------------------------------- figurino (o Bob "vira" o que a fala diz)

AZUL_POLICIA, PRETO = (0.12, 0.2, 0.42), (0.1, 0.1, 0.12)


def _quad(d, pts, cor, larg=6):
    d.linha(pts, fechar=True, preencher=cor, larg=larg)


def roupa(d: Doodle, tipo, pesc, quad, olha, t):
    """Peça no corpo: gravata | jaleco | capa | distintivo | avental | colete | medalha."""
    if not tipo:
        return
    y0 = pesc + 10
    if tipo == "capa":
        onda = math.sin(t * 5) * 18
        _quad(d, [(-35, y0), (35, y0), (95 - olha * 20 + onda, quad + 120), (-95 - olha * 20 + onda, quad + 120)], VERMELHO)
    elif tipo == "jaleco":
        _quad(d, [(-38, y0), (38, y0), (70, quad + 60), (-70, quad + 60)], (1, 1, 1))
        d.linha([(0, y0), (0, quad + 60)], larg=4)
        d.linha([(-38, y0), (0, y0 + 60), (38, y0)], larg=4)
    elif tipo == "avental":
        _quad(d, [(-45, y0 + 70), (45, y0 + 70), (60, quad + 50), (-60, quad + 50)], (1, 1, 1))
    elif tipo == "colete":
        _quad(d, [(-45, y0), (45, y0), (55, quad), (-55, quad)], LARANJA)
        d.linha([(-50, y0 + 110), (50, y0 + 110)], cor=(0.9, 0.9, 0.9), larg=10)
    if tipo == "gravata":
        _quad(d, [(-14, y0), (14, y0), (8, y0 + 25), (22, y0 + 130), (0, y0 + 155), (-22, y0 + 130), (-8, y0 + 25)], VERMELHO, 5)
    elif tipo == "distintivo":
        cx, cy = 28 * olha, y0 + 70
        d.linha([(cx + (26 if i % 2 == 0 else 11) * math.cos(i * math.pi / 5 - math.pi / 2),
                  cy + (26 if i % 2 == 0 else 11) * math.sin(i * math.pi / 5 - math.pi / 2)) for i in range(10)],
                fechar=True, preencher=AMARELO, larg=4)
    elif tipo == "medalha":
        d.linha([(-20, y0), (0, y0 + 60), (20, y0)], cor=AZUL, larg=6)
        d.circulo(0, y0 + 80, 22, preencher=AMARELO, larg=5)


def acessorios(d: Doodle, e, x, cy, olha, t):
    """Na cabeça (raio 135, centro x, cy): chapeu, oculos, bigode."""
    top = cy - 135
    ch = e.get("chapeu")
    if ch == "policia":
        _quad(d, [(-120, top + 40), (120, top + 40), (100, top - 45), (-100, top - 45)], AZUL_POLICIA)
        _quad(d, [(-10 + olha * 60, top + 40), (150 * olha, top + 50), (150 * olha, top + 62), (-10 + olha * 60, top + 58)], PRETO, 4)
        d.circulo(0, top - 5, 20, preencher=AMARELO, larg=4)
    elif ch == "chef":
        _quad(d, [(-75, top + 30), (75, top + 30), (75, top - 40), (-75, top - 40)], (1, 1, 1))
        for k in (-55, 0, 55):
            d.circulo(k, top - 70, 55, preencher=(1, 1, 1), larg=6)
    elif ch == "cartola":
        _quad(d, [(-130, top + 30), (130, top + 30), (130, top + 12), (-130, top + 12)], PRETO)
        _quad(d, [(-80, top + 14), (80, top + 14), (80, top - 150), (-80, top - 150)], PRETO)
        d.linha([(-80, top - 10), (80, top - 10)], cor=VERMELHO, larg=14)
    elif ch == "coroa":
        _quad(d, [(-85, top + 35), (85, top + 35), (95, top - 45), (48, top - 5), (0, top - 60), (-48, top - 5), (-95, top - 45)], AMARELO)
        d.circulo(0, top + 12, 12, preencher=VERMELHO, larg=4)
    elif ch == "piloto":
        _quad(d, [(-115, top + 40), (115, top + 40), (100, top - 30), (-100, top - 30)], PRETO)
        _quad(d, [(-10 + olha * 60, top + 40), (150 * olha, top + 52), (150 * olha, top + 62), (-10 + olha * 60, top + 58)], PRETO, 4)
        d.linha([(-45, top - 2), (-12, top + 6)], cor=AMARELO, larg=8)
        d.linha([(45, top - 2), (12, top + 6)], cor=AMARELO, larg=8)
        d.circulo(0, top + 5, 12, preencher=AMARELO, larg=4)
    elif ch == "capacete_obra":
        d.linha([(125 * math.cos(math.pi + a), top + 70 + 115 * math.sin(math.pi + a)) for a in (i * math.pi / 16 for i in range(17))],
                fechar=True, preencher=AMARELO)
        _quad(d, [(-150, top + 80), (150, top + 80), (150, top + 62), (-150, top + 62)], AMARELO)
    elif ch == "astronauta":
        d.c.arc(x, cy, 175, 0, 2 * math.pi)
        d.c.set_source_rgba(0.7, 0.85, 1.0, 0.25)
        d.c.fill()
        d.circulo(x, cy, 175, cor=(0.55, 0.6, 0.7), larg=9)
        d.arco(x - 60, cy - 70, 70, math.pi * 1.1, math.pi * 1.45, cor=(1, 1, 1), larg=10)
    elif ch == "formatura":
        _quad(d, [(-150, top + 5), (0, top - 45), (150, top + 5), (0, top + 55)], PRETO)
        d.linha([(0, top + 5), (110, top + 30), (110, top + 110)], cor=AMARELO, larg=6)
    elif ch == "bone":
        d.linha([(-125 + 250 * i / 16, top + 55 - 95 * math.sin(math.pi * i / 16)) for i in range(17)], fechar=True, preencher=VERMELHO)
        _quad(d, [(40 * olha, top + 45), (190 * olha, top + 58), (190 * olha, top + 72), (40 * olha, top + 65)], VERMELHO, 5)
    elif ch == "cowboy":
        d.elipse(0, top + 30, 190, 30, preencher=(0.55, 0.35, 0.18))
        _quad(d, [(-85, top + 25), (85, top + 25), (70, top - 70), (0, top - 50), (-70, top - 70)], (0.55, 0.35, 0.18))
    elif ch == "mago":
        _quad(d, [(-110, top + 45), (110, top + 45), (20, top - 200)], (0.4, 0.25, 0.7))
        d.texto(10, top - 30, "*", 70, cor=AMARELO, contorno=None)
    elif ch == "pirata":
        _quad(d, [(-140, top + 40), (140, top + 40), (90, top - 50), (0, top - 20), (-90, top - 50)], PRETO)
        d.texto(0, top + 5, "x", 50, cor=(1, 1, 1), contorno=None)
    oc = e.get("oculos")
    ex = x + olha * 14
    if oc in ("grau", "sol"):
        for lado in (-1, 1):
            d.circulo(ex + lado * 42, cy - 12, 34, preencher=PRETO if oc == "sol" else None, larg=6)
        d.linha([(ex - 10, cy - 14), (ex + 10, cy - 14)], larg=6)
    if e.get("bigode"):
        d.curva((ex - 60, cy + 40), (ex - 30, cy + 20), (ex, cy + 35), larg=10)
        d.curva((ex, cy + 35), (ex + 30, cy + 20), (ex + 60, cy + 40), larg=10)


def rosto(d: Doodle, x, y, e, t):
    olhos = e.get("olhos", "normal")
    sob = e.get("sobrancelhas", "neutra")
    boca = e.get("boca", "sorriso")
    olha = e.get("olha", 1)
    piscando = olhos in ("normal", "lado", "brilho") and (t % 2.9) < 0.12
    ex = 42
    # vida: o olhar passeia devagar e as sobrancelhas sobem junto com a fala
    passeia = math.sin(t * 0.9 + x) * 4 if olhos in ("normal", "brilho") else 0
    pula_sob = abs(math.sin(t * 5.5)) * 6 if e.get("fala") else 0
    for lado in (-1, 1):
        ox, oy = x + lado * ex, y - 12
        if olhos == "fechados" or piscando:
            d.linha([(ox - 16, oy), (ox + 16, oy)], larg=6)
        elif olhos == "feliz":
            d.arco(ox, oy + 8, 17, math.pi * 1.1, math.pi * 1.9, larg=6)
        elif olhos == "arregalados":
            d.circulo(ox, oy, 30, preencher=(1, 1, 1), larg=5)
            d.ponto(ox + olha * 6, oy + 3, 9)
        elif olhos == "brilho":  # olho grande com reflexo: fofo, encantado
            d.ponto(ox + olha * 5 + passeia, oy, 19)
            d.ponto(ox + olha * 5 + passeia - 6, oy - 7, 6, (1, 1, 1))
        elif olhos == "estrela":  # deslumbrado
            s = 1 + 0.12 * math.sin(t * 8)
            d.linha([(ox + (22 if i % 2 == 0 else 9) * s * math.cos(i * math.pi / 5 - math.pi / 2),
                      oy + (22 if i % 2 == 0 else 9) * s * math.sin(i * math.pi / 5 - math.pi / 2)) for i in range(10)],
                    fechar=True, preencher=AMARELO, larg=4)
        elif olhos == "coracao":  # apaixonado
            s = 1 + 0.15 * abs(math.sin(t * 6))
            d.linha([(ox + 16 * s * math.sin(a) ** 3, oy - s * (13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a)
                                                                 - math.cos(4 * a))) for a in (i * 2 * math.pi / 30 for i in range(30))],
                    fechar=True, preencher=VERMELHO, larg=3)
        elif olhos == "espiral":  # tonto
            d.linha([(ox + (2 + k * 0.9) * math.cos(k * 0.5 + t * 6 * lado), oy + (2 + k * 0.9) * math.sin(k * 0.5 + t * 6 * lado))
                     for k in range(24)], larg=4)
        elif olhos == "choro":
            d.arco(ox, oy - 4, 15, math.pi * 0.1, math.pi * 0.9, larg=6)
            q = (t * 1.2 + (lado + 1) * 0.3) % 1.0
            d.linha([(ox, oy + 12 + q * 60), (ox - 9, oy + 28 + q * 60), (ox, oy + 36 + q * 60), (ox + 9, oy + 28 + q * 60)],
                    cor=AZUL, fechar=True, preencher=(0.7, 0.86, 1), larg=3)
        elif olhos == "desconfiado":  # pálpebra meio fechada
            d.ponto(ox + olha * 8, oy + 4, 13)
            d.linha([(ox - 22, oy - 4), (ox + 22, oy - 4)], larg=7)
        else:
            d.ponto(ox + olha * 6 + passeia, oy, 14)
        # sobrancelhas
        by = oy - (60 if olhos == "arregalados" else 45) - pula_sob
        if sob == "levantadas":
            d.arco(ox, by + 18, 26, math.pi * 1.2, math.pi * 1.8, larg=6)
        elif sob == "preocupadas":
            d.linha([(ox - 22 * lado, by - 10), (ox + 20 * lado, by + 6)], larg=6)
        elif sob == "bravo":
            d.linha([(ox - 22 * lado, by + 8), (ox + 20 * lado, by - 8)], larg=6)
        elif sob == "uma" and lado == 1:
            d.linha([(ox - 22, by - 14), (ox + 22, by - 22)], larg=6)
        elif sob != "nenhuma":
            d.linha([(ox - 20, by), (ox + 20, by)], larg=6)
    by = y + 55
    if e.get("fala"):  # boca abre e fecha no ritmo da narração
        ab = abs(math.sin(t * 11)) * 0.8 + abs(math.sin(t * 5.3)) * 0.4
        d.elipse(x, by, 28, 6 + 22 * ab, preencher=(0.35, 0.08, 0.1), larg=5)
    elif boca == "sorriso":
        d.arco(x, by - 22, 38, math.pi * 0.2, math.pi * 0.8, larg=6)
    elif boca == "grande":
        d.linha([(x - 45, by - 8)] + [(x + 45 * math.cos(math.pi * i / 10), by - 8 + 40 * math.sin(math.pi * i / 10))
                                      for i in range(11)], preencher=(0.35, 0.08, 0.1), fechar=True, larg=5)
    elif boca == "aberta":
        d.elipse(x, by + 5, 26, 36, preencher=(0.35, 0.08, 0.1), larg=5)
    elif boca == "o":
        d.circulo(x, by, 15, preencher=(0.35, 0.08, 0.1), larg=5)
    elif boca == "triste":
        d.arco(x, by + 30, 32, math.pi * 1.2, math.pi * 1.8, larg=6)
    elif boca == "nervosa":
        d.linha([(x - 40 + i * 10, by + (8 if i % 2 else -4)) for i in range(9)], larg=5)
    elif boca == "reta":
        d.linha([(x - 25, by), (x + 25, by)], larg=6)
    elif boca == "sussurro":
        d.arco(x + 10, by - 10, 22, math.pi * 0.25, math.pi * 0.75, larg=6)
    elif boca == "sorrisao":  # sorriso aberto com dentes
        d.linha([(x - 50, by - 12)] + [(x + 50 * math.cos(math.pi * i / 12), by - 12 + 42 * math.sin(math.pi * i / 12))
                                       for i in range(13)], preencher=(0.35, 0.08, 0.1), fechar=True, larg=5)
        d.linha([(x - 44, by - 8), (x + 44, by - 8), (x + 36, by + 6), (x - 36, by + 6)], cor=None, fechar=True,
                preencher=(1, 1, 1))
    elif boca == "dentes":  # careta de "eita" (dentes cerrados)
        d.linha([(x - 42, by - 14), (x + 42, by - 14), (x + 42, by + 14), (x - 42, by + 14)], fechar=True,
                preencher=(1, 1, 1), larg=5)
        for k in (-21, 0, 21):
            d.linha([(x + k, by - 14), (x + k, by + 14)], larg=3)
        d.linha([(x - 42, by), (x + 42, by)], larg=3)
    elif boca == "lingua":  # zoeira
        d.arco(x, by - 22, 38, math.pi * 0.2, math.pi * 0.8, larg=6)
        d.linha([(x - 4 + 18 * math.cos(a), by + 18 + 20 * math.sin(a)) for a in (i * math.pi / 10 for i in range(11))],
                fechar=True, preencher=(0.98, 0.5, 0.58), larg=4)
    elif boca == "biquinho":
        d.circulo(x + 8, by, 9, preencher=(0.35, 0.08, 0.1), larg=4)
    if e.get("corado"):
        for lado in (-1, 1):
            d.c.arc(x + lado * 75, y + 30, 22, 0, 2 * math.pi)
            d.c.set_source_rgba(0.95, 0.4, 0.45, 0.45)
            d.c.fill()
    if e.get("suor"):
        for k, (sx, sy) in enumerate([(x + 115, y - 70), (x - 120, y - 40)]):
            q = (t * 0.9 + k * 0.5) % 1.0
            gy = sy + q * 70
            d.linha([(sx, gy - 22), (sx - 11, gy), (sx, gy + 12), (sx + 11, gy)], cor=AZUL, fechar=True,
                    preencher=(0.75, 0.88, 1), larg=4)


# ---------------------------------------------------------------- objetos

def celular(d: Doodle, e, t):
    x, y, s = e["x"], e["y"], e.get("tam", 1.0)
    w, h = 150 * s, 270 * s
    d.linha([(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)],
            fechar=True, preencher=(0.2, 0.2, 0.24), larg=6)
    d.linha([(x - w / 2 + 12, y - h / 2 + 22), (x + w / 2 - 12, y - h / 2 + 22), (x + w / 2 - 12, y + h / 2 - 30),
             (x - w / 2 + 12, y + h / 2 - 30)], fechar=True, preencher=e.get("tela_cor", (0.85, 0.93, 1)), larg=3,
            cor=None)
    if e.get("play"):
        r = 38 * s
        d.circulo(x, y, r, preencher=VERDE, larg=5)
        d.linha([(x - r * 0.3, y - r * 0.45), (x + r * 0.5, y), (x - r * 0.3, y + r * 0.45)], fechar=True,
                preencher=(1, 1, 1), larg=3, cor=(1, 1, 1))
    if e.get("tela"):
        d.texto(x, y, e["tela"], 46 * s, cor=TINTA, contorno=None)
    if e.get("onda_audio"):
        for i in range(7):
            hh = (18 + 30 * abs(math.sin(t * 9 + i * 1.3))) * s
            xx = x - 50 * s + i * 16 * s
            d.linha([(xx, y + 70 * s - hh / 2), (xx, y + 70 * s + hh / 2)], cor=AZUL, larg=6)


def ondas(d: Doodle, e, t):
    """Ondas de som em arco saindo de (x, y) na direção 'ang' (graus); 'fina' = ondas finas e rápidas."""
    x, y, ang = e["x"], e["y"], math.radians(e.get("ang", 0))
    cor = CORES.get(e.get("cor", "azul"), AZUL)
    alcance = e.get("alcance", 300)
    for k in range(e.get("n", 3)):
        q = ((t * e.get("vel", 0.9)) + k / e.get("n", 3)) % 1.0
        r = 30 + q * alcance
        d.c.push_group()
        d.arco(x, y, r, ang - 0.55, ang + 0.55, cor=cor, larg=e.get("larg", 10))
        d.c.pop_group_to_source()
        d.c.paint_with_alpha(1 - q ** 2)


def zigue(d: Doodle, e, t):
    """Linha em zigue-zague vibrando de p0 a p1 (desenha progressivamente a partir de 'entra')."""
    (x0, y0), (x1, y1) = e["de"], e["ate"]
    cor = CORES.get(e.get("cor", "laranja"), LARANJA)
    prog = suave(t, e.get("entra", 0), e.get("desenha", 0.6))
    if prog <= 0:
        return
    n = e.get("dentes", 12)
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    amp = e.get("amp", 22) * (1 + 0.25 * math.sin(t * 30))
    pts = []
    for i in range(int(n * prog) + 1):
        f = i / n
        s = amp * (1 if i % 2 else -1) if 0 < i < n else 0
        pts.append((x0 + ux * L * f - uy * s, y0 + uy * L * f + ux * s))
    if len(pts) > 1:
        d.linha(pts, cor=cor, larg=e.get("larg", 9))


def seta(d: Doodle, e, t):
    (x0, y0), (x1, y1) = e["de"], e["ate"]
    cor = CORES.get(e.get("cor", "tinta"), TINTA)
    prog = suave(t, e.get("entra", 0), 0.45)
    if prog <= 0:
        return
    cx, cy = e.get("curva", ((x0 + x1) / 2, (y0 + y1) / 2))
    n = 20
    pts = [((1 - u) ** 2 * x0 + 2 * (1 - u) * u * cx + u * u * x1, (1 - u) ** 2 * y0 + 2 * (1 - u) * u * cy + u * u * y1)
           for u in (i / n * prog for i in range(n + 1))]
    d.linha(pts, cor=cor, larg=e.get("larg", 12))
    if prog > 0.95:
        (ax, ay), (bx, by) = pts[-3], pts[-1]
        a = math.atan2(by - ay, bx - ax)
        d.linha([(bx - 45 * math.cos(a - 0.5), by - 45 * math.sin(a - 0.5)), (bx, by),
                 (bx - 45 * math.cos(a + 0.5), by - 45 * math.sin(a + 0.5))], cor=cor, larg=e.get("larg", 12))
    if e.get("rotulo") and prog > 0.6:
        lx, ly = e.get("rotulo_em", (cx, cy - 50))
        d.texto(lx, ly, e["rotulo"], e.get("rotulo_tam", 64), cor=cor)


def balao(d: Doodle, e, t):
    """Balão de pensamento (bolinhas até a cabeça) ou de fala ('fala': True)."""
    x, y, w, h = e["x"], e["y"], e.get("w", 420), e.get("h", 300)
    n = 22
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        bump = 1 + (0.07 * math.sin(a * 9) if not e.get("fala") else 0)
        pts.append((x + w / 2 * math.cos(a) * bump, y + h / 2 * math.sin(a) * bump))
    d.linha(pts, fechar=True, preencher=(1, 1, 1), larg=6)
    if e.get("cauda"):
        cx, cy = e["cauda"]
        for k, r in enumerate((24, 16, 10)):
            f = (k + 1) / 4
            d.circulo(x + (cx - x) * (0.55 + f * 0.5), y + h / 2 * 0.8 + (cy - y - h / 2) * f * 1.2, r,
                      preencher=(1, 1, 1), larg=5)


def orelha(d: Doodle, e, t):
    x, y, s = e["x"], e["y"], e.get("tam", 1.0)
    pts = [(x + 60 * s * math.cos(a) * (1 if math.sin(a) < 0 else 0.8), y + 90 * s * math.sin(a))
           for a in (math.pi * 0.35 + i * math.pi * 1.5 / 18 for i in range(19))]
    d.linha(pts, preencher=(1, 0.86, 0.75), larg=6)
    d.curva((x - 10 * s, y - 45 * s), (x + 35 * s, y - 40 * s), (x + 15 * s, y + 10 * s), larg=5)


def lampada(d: Doodle, e, t):
    x, y, s = e["x"], e["y"], e.get("tam", 1.0)
    brilho = 0.5 + 0.5 * math.sin(t * 8)
    for k in range(8):
        a = k * math.pi / 4 + t
        r0, r1 = 75 * s, (95 + 15 * brilho) * s
        d.linha([(x + r0 * math.cos(a), y - 10 * s + r0 * math.sin(a)), (x + r1 * math.cos(a), y - 10 * s + r1 * math.sin(a))],
                cor=AMARELO, larg=6)
    d.circulo(x, y - 10 * s, 50 * s, preencher=AMARELO, larg=6)
    d.linha([(x - 22 * s, y + 38 * s), (x + 22 * s, y + 38 * s), (x + 22 * s, y + 70 * s), (x - 22 * s, y + 70 * s)],
            fechar=True, preencher=(0.7, 0.7, 0.72), larg=5)


def microfone(d: Doodle, e, t):
    x, y, s = e["x"], e["y"], e.get("tam", 1.0)
    d.linha([(x - 12 * s, y + 40 * s), (x - 18 * s, y + 190 * s), (x + 18 * s, y + 190 * s), (x + 12 * s, y + 40 * s)],
            fechar=True, preencher=(0.25, 0.25, 0.28), larg=5)
    d.circulo(x, y, 48 * s, preencher=(0.72, 0.72, 0.76), larg=6)
    for k in (-1, 0, 1):
        d.linha([(x - 38 * s, y + k * 18 * s), (x + 38 * s, y + k * 18 * s)], larg=3, cor=(0.4, 0.4, 0.42))


def caixa_som(d: Doodle, e, t):
    x, y, s = e["x"], e["y"], e.get("tam", 1.0)
    w, h = 300 * s, 460 * s
    d.linha([(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)],
            fechar=True, preencher=(0.22, 0.22, 0.26), larg=7)
    pulso = 1 + 0.08 * abs(math.sin(t * 9))
    for cy, r in ((y - h * 0.25, 60 * s), (y + h * 0.15, 105 * s)):
        d.circulo(x, cy, r * pulso, preencher=(0.45, 0.45, 0.5), larg=6)
        d.circulo(x, cy, r * 0.35 * pulso, preencher=(0.15, 0.15, 0.18), larg=5)


def mesa(d: Doodle, e, t):
    x, y, w = e["x"], e["y"], e.get("w", 300)
    d.linha([(x - w / 2, y), (x + w / 2, y), (x + w / 2, y + 22), (x - w / 2, y + 22)], fechar=True,
            preencher=(0.72, 0.52, 0.32), larg=6)
    for lx in (x - w / 2 + 30, x + w / 2 - 30):
        d.linha([(lx, y + 22), (lx, PES - 10)], larg=8)


def xis(d: Doodle, e, t):
    x, y, r = e["x"], e["y"], e.get("tam", 60) * pop(t, e.get("entra", 0))
    if r <= 0:
        return
    d.linha([(x - r, y - r), (x + r, y + r)], cor=VERMELHO, larg=18)
    d.linha([(x + r, y - r), (x - r, y + r)], cor=VERMELHO, larg=18)


def rato(d: Doodle, e, t):
    x, y, s = e["x"], e["y"] - abs(math.sin(t * 8)) * 10, e.get("tam", 1.0)
    cinza = (0.78, 0.78, 0.8)
    d.elipse(x, y, 70 * s, 45 * s, preencher=cinza, larg=5)
    d.circulo(x - 40 * s, y - 45 * s, 26 * s, preencher=(1, 0.8, 0.85), larg=5)
    d.circulo(x - 70 * s, y - 20 * s, 34 * s, preencher=cinza, larg=5)
    d.ponto(x - 80 * s, y - 25 * s, 6)
    d.ponto(x - 104 * s, y - 14 * s, 7, (0.95, 0.5, 0.6))
    d.curva((x + 68 * s, y + 10 * s), (x + 130 * s, y - 40 * s), (x + 150 * s, y + 20 * s), larg=4)
    if e.get("fala"):
        d.texto(x - 60 * s, y - 120 * s, e["fala"], 44 * s, cor=TINTA)


def placa(d: Doodle, e, t):
    x, y = e["x"], e["y"]
    w, h = e.get("w", 320), e.get("h", 140)
    d.linha([(x, y + h / 2), (x, PES - 5)], larg=9, cor=(0.45, 0.3, 0.18))
    d.linha([(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)],
            fechar=True, preencher=(1, 0.97, 0.85), larg=6)
    d.texto(x, y, e["txt"], e.get("txt_tam", 58), contorno=None, cor=CORES.get(e.get("cor", "tinta"), TINTA))


def botao(d: Doodle, e, t):
    x, y = e["x"], e["y"]
    w, h = e.get("w", 380), e.get("h", 130)
    aperta = 1 + 0.05 * math.sin(t * 10)
    w, h = w * aperta, h * aperta
    d.linha([(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)],
            fechar=True, preencher=CORES.get(e.get("cor", "verde"), VERDE), larg=7)
    d.texto(x, y, e["txt"], e.get("txt_tam", 66), cor=(1, 1, 1), contorno=TINTA)


def interrogacao(d: Doodle, e, t):
    d.texto(e["x"], e["y"] + math.sin(t * 4) * 10, e.get("txt", "?"), e.get("tam", 160),
            cor=CORES.get(e.get("cor", "tinta"), TINTA), rot=math.sin(t * 3) * 0.12)


def texto(d: Doodle, e, t):
    d.texto(e["x"], e["y"], e["txt"], e.get("tam", 110), cor=CORES.get(e.get("cor", "tinta"), TINTA),
            rot=math.radians(e.get("rot", -4)))


def estrelas(d: Doodle, e, t):
    """Estrelinhas girando (tontura/impacto) em volta de (x, y)."""
    for k in range(4):
        a = t * 3 + k * math.pi / 2
        sx, sy = e["x"] + 150 * math.cos(a), e["y"] + 40 * math.sin(a)
        d.linha([(sx + (22 if i % 2 == 0 else 9) * math.cos(i * math.pi / 5 - math.pi / 2),
                  sy + (22 if i % 2 == 0 else 9) * math.sin(i * math.pi / 5 - math.pi / 2)) for i in range(10)],
                fechar=True, preencher=AMARELO, larg=4)


def cabeca_por_dentro(d: Doodle, e, t):
    """Crânio desenhado dentro da cabeça (ossos), para o caminho da voz 'por dentro'."""
    x, y = e["x"], e["y"]
    d.c.push_group()
    d.arco(x, y, 105, math.pi * 1.05, math.pi * 1.95, cor=(0.8, 0.78, 0.7), larg=10)
    d.c.pop_group_to_source()
    d.c.paint_with_alpha(0.8)


def _cor(v, padrao=TINTA):
    if v is None:
        return padrao
    if isinstance(v, str) and v.startswith("#") and len(v) == 7:
        return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return CORES.get(v, padrao)


def desenho(d: Doodle, e, t):
    """Objeto livre desenhado pelo roteirista com formas simples, relativas a (x, y), multiplicadas por 'tam'.
    formas: {"f": "circulo", "x", "y", "r"} | {"f": "elipse", "x", "y", "rx", "ry", "rot"} |
            {"f": "linha"|"poligono", "pts": [[x, y], ...]} | {"f": "arco", "x", "y", "r", "de", "ate"} (graus) |
            {"f": "texto", "x", "y", "txt", "tam"}; cada uma com "cor" (contorno), "preenche" e "larg".
    'mexe': "flutua" | "gira" | "pulsa" | "balanca" dá vida ao objeto."""
    x0, y0, s = e["x"], e["y"], e.get("tam", 1.0)
    mexe = e.get("mexe")
    c = d.c
    c.save()
    c.translate(x0, y0 + (math.sin(t * 3) * 12 if mexe == "flutua" else 0))
    if mexe == "gira":
        c.rotate(t * 1.5)
    elif mexe == "balanca":
        c.rotate(math.sin(t * 4) * 0.15)
    elif mexe == "pulsa":
        k = 1 + 0.06 * math.sin(t * 8)
        c.scale(k, k)
    for f in e.get("formas", [])[:60]:
        cor = None if f.get("cor") == "nenhuma" else _cor(f.get("cor"))
        pre = _cor(f["preenche"], None) if f.get("preenche") else None
        larg = f.get("larg", 6)
        tipo = f.get("f")
        try:
            if tipo == "circulo":
                d.circulo(f["x"] * s, f["y"] * s, f["r"] * s, cor=cor, larg=larg, preencher=pre)
            elif tipo == "elipse":
                d.elipse(f["x"] * s, f["y"] * s, f["rx"] * s, f["ry"] * s, cor=cor, larg=larg, preencher=pre,
                         rot=math.radians(f.get("rot", 0)))
            elif tipo in ("linha", "poligono"):
                d.linha([(px * s, py * s) for px, py in f["pts"]], cor=cor, larg=larg, fechar=tipo == "poligono",
                        preencher=pre)
            elif tipo == "arco":
                d.arco(f["x"] * s, f["y"] * s, f["r"] * s, math.radians(f["de"]), math.radians(f["ate"]),
                       cor=cor or TINTA, larg=larg)
            elif tipo == "texto":
                d.texto(f["x"] * s, f["y"] * s, f["txt"], f.get("tam", 50) * s, cor=cor or TINTA, contorno=None)
        except (KeyError, TypeError, ValueError):
            continue  # forma malformada: pula, não derruba a cena
    c.restore()


PASTA_SVG = Path(__file__).with_name("dados") / "svg"
_CACHE_SVG: dict = {}


def _ler_svg(arquivo: str) -> list:
    """SVG -> lista de (subcaminhos em pontos, preenchimento, contorno, largura), normalizada para caber numa caixa de
    220 px centrada em 0,0. Curvas viram pontos a cada ~6 px: assim passam pelo mesmo traço doodle/rough do canal."""
    if arquivo in _CACHE_SVG:
        return _CACHE_SVG[arquivo]
    from svgelements import SVG, Path as SvgPath, Shape, Close, Move

    doc = SVG.parse(str(PASTA_SVG / arquivo if not Path(arquivo).is_absolute() else arquivo))
    formas = []
    for el in doc.elements():
        if not isinstance(el, Shape):
            continue
        caminho = SvgPath(el)
        if not len(caminho):
            continue
        fill = el.fill.value if el.fill is not None and el.fill.value is not None else None
        stroke = el.stroke.value if el.stroke is not None and el.stroke.value is not None else None
        subs, atual = [], []
        for seg in caminho:
            if isinstance(seg, Move):
                if len(atual) > 1:
                    subs.append((atual, False))
                atual = [(seg.end.x, seg.end.y)]
                continue
            if isinstance(seg, Close):
                if len(atual) > 1:
                    subs.append((atual, True))
                atual = []
                continue
            n = max(2, int(seg.length(error=1e-2) / 6)) if hasattr(seg, "length") else 2
            atual += [(p.x, p.y) for p in (seg.point(i / n) for i in range(1, n + 1))]
        if len(atual) > 1:
            subs.append((atual, False))
        # svgelements: cor como inteiro 0xRRGGBBAA; alfa 0 = "none"
        cor = lambda v: None if v is None or v & 0xFF == 0 else (  # noqa: E731
            ((v >> 24) & 0xFF) / 255, ((v >> 16) & 0xFF) / 255, ((v >> 8) & 0xFF) / 255)
        formas.append((subs, cor(fill), cor(stroke), float(el.stroke_width or 0)))
    xs = [x for f in formas for s, _ in f[0] for x, _ in s]
    ys = [y for f in formas for s, _ in f[0] for _, y in s]
    if not xs:
        _CACHE_SVG[arquivo] = []
        return []
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    k = 220 / max(max(xs) - min(xs), max(ys) - min(ys), 1)
    norm = [([([((x - cx) * k, (y - cy) * k) for x, y in s], fech) for s, fech in subs], f, st, w * k)
            for subs, f, st, w in formas]
    _CACHE_SVG[arquivo] = norm
    return norm


def svg(d: Doodle, e, t):
    """Objeto vindo de arquivo SVG (dados/svg/): {arquivo, x, y, tam, mexe}. Desenho profissional no traço do canal."""
    c = d.c
    c.save()
    c.translate(e["x"], e["y"] + (math.sin(t * 3) * 12 if e.get("mexe") == "flutua" else 0))
    if e.get("mexe") == "balanca":
        c.rotate(math.sin(t * 4) * 0.15)
    elif e.get("mexe") == "pulsa":
        k = 1 + 0.06 * math.sin(t * 8)
        c.scale(k, k)
    s = e.get("tam", 1.0)
    c.scale(s, s)
    for subs, fill, stroke, w in _ler_svg(e["arquivo"]):
        for pts, fechado in subs:
            d.linha(pts, cor=stroke, larg=max(3.0, w) if stroke else 0, fechar=fechado, preencher=fill, amp=1.2)
    c.restore()


OBJETOS = {
    "svg": svg,
    "desenho": desenho,
    "celular": celular, "ondas": ondas, "zigue": zigue, "seta": seta, "balao": balao, "orelha": orelha,
    "lampada": lampada, "microfone": microfone, "caixa_som": caixa_som, "mesa": mesa, "xis": xis, "rato": rato,
    "placa": placa, "botao": botao, "interrogacao": interrogacao, "texto": texto, "estrelas": estrelas,
    "cabeca_por_dentro": cabeca_por_dentro,
}


# ---------------------------------------------------------------- cena

def _ancora(e: dict) -> tuple[float, float]:
    if "x" in e and "y" in e:
        return e["x"], e["y"]
    if "de" in e:
        return e["de"]
    return e.get("x", 540), PES


# ---------------------------------------------------------------- cenários (ambientação da cena)

def _ret(c, x0, y0, x1, y1, cor):
    c.rectangle(x0, y0, x1 - x0, y1 - y0)
    c.set_source_rgb(*cor)
    c.fill()


def _estrelas_fundo(c, n, cor, y1, seed=7):
    import random
    rnd = random.Random(seed)
    for _ in range(n):
        c.arc(rnd.uniform(-200, 1300), rnd.uniform(-300, y1), rnd.uniform(2, 5), 0, 7)
        c.set_source_rgba(*cor, rnd.uniform(0.5, 1))
        c.fill()


DECOR = (0.45, 0.45, 0.50)  # traço dos objetos de fundo: mais claro que o do elenco, para não competir


def cenario(d: "Doodle", nome: str, t: float) -> None:
    """Parede e chão (coordenadas de trabalho). Enfeites ficam nas bordas e em traço claro: o elenco é a estrela."""
    c = d.c
    parede, chao = PAREDE, CHAO
    tabela = {
        "quarto": ((0.90, 0.88, 0.97), (0.80, 0.66, 0.50)), "escola": ((0.93, 0.95, 0.89), (0.72, 0.74, 0.80)),
        "laboratorio": ((0.88, 0.96, 0.97), (0.80, 0.82, 0.85)), "cozinha": ((0.99, 0.95, 0.82), (0.86, 0.78, 0.66)),
        "rua": ((0.78, 0.89, 0.98), (0.70, 0.71, 0.74)), "parque": ((0.78, 0.91, 0.99), (0.60, 0.82, 0.45)),
        "espaco": ((0.16, 0.20, 0.40), (0.72, 0.72, 0.76)), "mar": ((0.55, 0.80, 0.95), (0.95, 0.87, 0.65)),
        "corpo": ((0.98, 0.78, 0.78), (0.90, 0.60, 0.62)), "praia": ((0.70, 0.88, 1.0), (0.97, 0.89, 0.66)),
        "cor_azul": ((0.55, 0.78, 1.0), (0.42, 0.66, 0.92)), "cor_amarelo": ((1.0, 0.88, 0.35), (0.95, 0.76, 0.25)),
        "cor_rosa": ((1.0, 0.72, 0.82), (0.93, 0.58, 0.70)), "cor_verde": ((0.62, 0.90, 0.62), (0.48, 0.78, 0.50)),
        "escritorio": ((0.92, 0.94, 0.97), (0.62, 0.66, 0.72)), "sala": ((0.98, 0.92, 0.86), (0.72, 0.56, 0.42)),
        "hospital": ((0.90, 0.97, 0.96), (0.82, 0.88, 0.90)), "academia": ((0.93, 0.93, 0.95), (0.35, 0.37, 0.42)),
        "supermercado": ((0.97, 0.97, 0.93), (0.85, 0.85, 0.82)), "onibus": ((0.85, 0.90, 0.96), (0.55, 0.58, 0.64)),
        "noite": ((0.12, 0.15, 0.32), (0.25, 0.30, 0.28)),
    }
    if nome in tabela:
        parede, chao = tabela[nome]
    _ret(c, -400, -500, W + 400, PISO, parede)
    if nome == "quarto":
        _ret(c, 440, 560, 640, 760, (0.18, 0.22, 0.45))  # janela à noite entre as cabeças
        c.arc(590, 610, 26, 0, 7); c.set_source_rgb(1, 0.95, 0.7); c.fill()
        d.linha([(440, 560), (640, 560), (640, 760), (440, 760)], cor=DECOR, fechar=True, larg=10)
        d.linha([(540, 560), (540, 760)], cor=DECOR, larg=7)
        d.linha([(150, 1000), (930, 1000), (930, 1100), (150, 1100)], cor=DECOR, fechar=True, preencher=(0.55, 0.65, 0.92), larg=6)
        d.linha([(150, 900), (150, 1100)], cor=(0.55, 0.40, 0.28), larg=18)  # cabeceira
        d.linha([(170, 955), (330, 955), (330, 1000), (170, 1000)], cor=DECOR, fechar=True, preencher=(1, 1, 1), larg=5)
    elif nome == "escola":
        d.linha([(170, 470), (910, 470), (910, 770), (170, 770)], cor=(0.55, 0.40, 0.25), fechar=True,
                preencher=(0.20, 0.38, 0.30), larg=16)
        d.linha([(230, 540), (360, 540)], cor=(0.9, 0.9, 0.9), larg=4)
        d.linha([(230, 590), (320, 590)], cor=(0.9, 0.9, 0.9), larg=4)
        d.texto(780, 560, "2+2", 50, cor=(0.92, 0.92, 0.92), contorno=None)
    elif nome == "laboratorio":
        for k, (x, cor) in enumerate(((880, (0.4, 0.8, 0.5)), (960, (0.95, 0.5, 0.6)), (1030, (0.5, 0.7, 1.0)))):
            d.linha([(x - 25, 820), (x + 25, 820), (x + 45, 930), (x - 45, 930)], cor=DECOR, fechar=True, preencher=cor, larg=5)
            d.linha([(x - 12, 760), (x - 12, 820)], cor=DECOR, larg=5)
            d.linha([(x + 12, 760), (x + 12, 820)], cor=DECOR, larg=5)
        d.linha([(820, 935), (1100, 935)], cor=DECOR, larg=10)
    elif nome == "cozinha":
        for y in range(600, 900, 60):  # azulejos
            d.linha([(-100, y), (W + 100, y)], cor=(0.88, 0.84, 0.68), larg=3, amp=0)
        d.linha([(430, 560), (650, 560), (650, 660), (430, 660)], cor=DECOR, fechar=True, preencher=(0.85, 0.70, 0.50), larg=6)  # armário
        d.linha([(540, 560), (540, 660)], cor=DECOR, larg=5)
        d.linha([(140, 920), (940, 920), (940, PISO), (140, PISO)], cor=DECOR, fechar=True, preencher=(0.95, 0.95, 0.95), larg=6)  # balcão
        d.linha([(140, 920), (940, 920)], cor=(0.55, 0.42, 0.30), larg=16)
        d.circulo(540, 880, 36, cor=DECOR, preencher=(0.3, 0.3, 0.32), larg=5)  # panela
        d.linha([(576, 872), (630, 860)], cor=DECOR, larg=8)
    elif nome == "rua":
        for x0, w, h in ((-100, 220, 420), (150, 160, 300), (760, 200, 380), (990, 200, 460)):
            d.linha([(x0, PISO), (x0, PISO - h), (x0 + w, PISO - h), (x0 + w, PISO)], cor=DECOR, preencher=(0.86, 0.88, 0.93), larg=5)
            for wy in range(PISO - h + 40, PISO - 40, 80):
                _ret(c, x0 + 30, wy, x0 + 70, wy + 40, (1, 0.92, 0.6))
    elif nome in ("parque", "praia"):
        for cx, cy in ((180, 300), (880, 220)):
            for dx, r in ((-40, 38), (0, 50), (42, 36)):
                c.arc(cx + dx, cy, r, 0, 7); c.set_source_rgb(1, 1, 1); c.fill()
        if nome == "parque":
            d.linha([(90, PISO), (90, 780)], cor=(0.45, 0.30, 0.18), larg=26)
            d.circulo(90, 700, 130, cor=DECOR, preencher=(0.40, 0.72, 0.38), larg=6)
        else:
            _ret(c, -400, PISO - 170, W + 400, PISO, (0.35, 0.65, 0.92))
            c.arc(930, 520, 60, 0, 7); c.set_source_rgb(1, 0.85, 0.3); c.fill()
    elif nome == "espaco":
        _estrelas_fundo(c, 80, (1, 1, 0.9), PISO - 20)
        d.circulo(930, 360, 70, cor=DECOR, preencher=(0.95, 0.60, 0.35), larg=5)
        d.elipse(930, 360, 120, 22, cor=(0.95, 0.85, 0.6), larg=6, rot=-0.3)
    elif nome == "mar":
        import random
        rnd = random.Random(5)
        for _ in range(14):
            x, y0 = rnd.uniform(0, W), rnd.uniform(0, PISO)
            y = (y0 - t * 60 * rnd.uniform(0.5, 1.5)) % PISO
            d.circulo(x, y, rnd.uniform(8, 18), cor=(1, 1, 1), larg=3)
        for x in (80, 1000):
            d.linha([(x + math.sin(i * 0.8 + t * 2) * 18, PISO - i * 45) for i in range(9)], cor=(0.25, 0.60, 0.35), larg=12)
    elif nome == "corpo":
        for k, (y, a) in enumerate(((520, 60), (820, 45))):
            d.linha([(-100 + i * 70, y + a * math.sin(i * 0.9)) for i in range(20)], cor=(0.85, 0.35, 0.40), larg=26)
        import random
        rnd = random.Random(9)
        for _ in range(10):
            x = (rnd.uniform(0, W) + t * 80) % (W + 200) - 100
            c.save(); c.translate(x, rnd.uniform(430, 1000)); c.scale(1, 0.6)
            c.arc(0, 0, 22, 0, 7); c.restore(); c.set_source_rgb(0.85, 0.20, 0.25); c.fill()
    # enfeites espalhados pela faixa visível (x 140..940): entre as cabeças (x ~430..650) e atrás dos corpos
    elif nome == "escritorio":
        d.linha([(140, 520), (940, 520)], cor=(0.80, 0.83, 0.88), larg=4)  # rodameio
        d.linha([(430, 640), (650, 640), (650, 790), (430, 790)], cor=DECOR, fechar=True, preencher=(1, 1, 1), larg=5)
        for k, (h, cor) in enumerate(((50, VERDE), (95, AZUL), (70, LARANJA), (120, VERMELHO))):  # quadro com gráfico
            _ret(c, 455 + k * 48, 770 - h, 490 + k * 48, 770, cor)
        d.linha([(140, 960), (940, 960)], cor=(0.55, 0.42, 0.30), larg=16)  # mesa comprida atrás
        for x in (180, 900):
            d.linha([(x, 960), (x, PISO)], cor=DECOR, larg=8)
    elif nome == "sala":
        d.linha([(430, 560), (650, 560), (650, 700), (430, 700)], cor=DECOR, fechar=True, preencher=(0.18, 0.18, 0.22), larg=8)
        _ret(c, 442, 572, 638, 688, (0.40, 0.60, 0.85))  # TV entre as cabeças
        d.linha([(540, 700), (540, 735)], cor=DECOR, larg=8)
        d.linha([(150, 920), (930, 920), (930, 1090), (150, 1090)], cor=DECOR, fechar=True, preencher=(0.55, 0.62, 0.85), larg=6)
        d.linha([(150, 1010), (930, 1010)], cor=(0.45, 0.52, 0.78), larg=6)  # sofá comprido atrás
        for x in (140, 940):
            d.circulo(x, 930, 55, cor=DECOR, preencher=(0.50, 0.57, 0.82), larg=6)
    elif nome == "hospital":
        _ret(c, 525, 560, 555, 680, VERMELHO)  # cruz entre as cabeças
        _ret(c, 480, 605, 600, 635, VERMELHO)
        d.linha([(150, 1000), (930, 1000), (930, 1050), (150, 1050)], cor=DECOR, fechar=True, preencher=(1, 1, 1), larg=6)
        d.linha([(440, 800), (640, 800), (640, 890), (440, 890)], cor=DECOR, fechar=True, preencher=(0.15, 0.2, 0.2), larg=5)
        d.linha([(450, 845), (500, 845), (515, 815), (535, 875), (550, 845), (630, 845)], cor=VERDE, larg=5)
    elif nome == "academia":
        _ret(c, -400, 520, W + 400, 560, (0.95, 0.35, 0.3))  # faixa na parede
        d.linha([(430, 700), (650, 700), (650, 880), (430, 880)], cor=DECOR, fechar=True, preencher=(0.85, 0.92, 1), larg=6)  # espelho
        for x in (430, 650):  # halteres no chão, no meio
            d.linha([(x - 45, 1090), (x + 45, 1090)], cor=DECOR, larg=10)
            for dx in (-45, 45):
                d.linha([(x + dx, 1060), (x + dx, 1120)], cor=(0.2, 0.2, 0.22), larg=22)
    elif nome == "supermercado":
        for y in (560, 720, 880, 1040):  # prateleiras na largura toda (aparecem entre e atrás dos personagens)
            d.linha([(140, y), (940, y)], cor=DECOR, larg=8)
            for k in range(13):  # produtos em tom pastel: o fundo não compete com os personagens
                cor = (VERMELHO, AMARELO, VERDE, AZUL, LARANJA)[(k + y // 10) % 5]
                _ret(c, 150 + k * 61, y - 60, 196 + k * 61, y - 4, tuple(0.55 * v + 0.45 for v in cor))
    elif nome == "onibus":
        d.linha([(-100, 470), (W + 100, 470)], cor=DECOR, larg=8)  # barra de segurar
        for x in (150, 430, 710):
            d.linha([(x, 540), (x + 230, 540), (x + 230, 720), (x, 720)], cor=DECOR, fechar=True, preencher=(0.72, 0.86, 0.98), larg=8)
            # paisagem passando pela janela (prédios deslizando)
            for k in range(3):
                bx = x + ((k * 110 - t * 260) % 330) - 60
                if x < bx < x + 200:
                    _ret(c, bx, 620 - k * 20, bx + 30, 718, (0.80, 0.84, 0.92))
        for x in (170, 450, 730):  # bancos
            d.linha([(x, 980), (x + 200, 980), (x + 200, 1060), (x, 1060)], cor=DECOR, fechar=True, preencher=(0.30, 0.45, 0.70), larg=6)
    elif nome == "noite":
        _estrelas_fundo(c, 60, (1, 1, 0.9), PISO - 60, seed=11)
        c.arc(880, 420, 60, 0, 7); c.set_source_rgb(1, 0.96, 0.75); c.fill()
    _ret(c, -400, PISO, W + 400, H + 400, chao)
    d.linha([(-100, PISO), (W + 100, PISO)], larg=5, amp=1.5)


def chuva(d: "Doodle", t: float) -> None:
    """Clima por cima da cena (opcional): gotas caindo."""
    import random
    rnd = random.Random(4)
    for _ in range(60):
        x0, fase = rnd.uniform(-200, W + 200), rnd.uniform(0, 1)
        y = ((fase + t * 1.6) % 1.0) * (PISO + 300) - 300
        d.linha([(x0, y), (x0 - 8, y + 34)], cor=(0.45, 0.6, 0.85), larg=4, amp=0)


def _entrada(c, e: dict, t: float, ax: float, ay: float) -> bool:
    """Animação de entrada do objeto: pop (padrão) | desliza | cai | cresce. Devolve False se ainda não entrou."""
    ini = e.get("entra", 0)
    anim = e.get("anim", "pop")
    if t < ini:
        return False
    if anim == "desliza":
        p = suave(t, ini, 0.45)
        c.translate((1 - p) * 700, 0)
    elif anim == "cai":
        p = min(1.0, (t - ini) / 0.45)
        c.translate(0, -(1 - p) ** 2 * 900)
        # esticar na queda, amassar ao tocar o chão e voltar balançando (squash & stretch)
        pos = t - ini - 0.45
        if p < 1:
            sx, sy = 0.9, 1.12
        else:
            k = max(0.0, 1 - pos / 0.35)
            sy = 1 - 0.22 * k * math.cos(pos * 28)
            sx = 1 / sy
        c.translate(ax, ay + 80)
        c.scale(sx, sy)
        c.translate(-ax, -ay - 80)
    else:
        esc = suave(t, ini, 0.7) if anim == "cresce" else pop(t, ini)
        # no pop, o objeto estica e amassa enquanto estoura (fica vivo em vez de só crescer)
        dt = t - ini
        onda = 0.12 * math.sin(dt * 22) * max(0.0, 1 - dt / 0.45) if anim != "cresce" else 0.0
        if esc < 0.01:  # escala zero não é matriz válida no cairo
            return False
        c.translate(ax, ay)
        c.scale(esc * (1 + onda), esc * (1 - onda))
        c.translate(-ax, -ay)
    return True


def quadro(cena: dict, n: int) -> cairo.ImageSurface:
    t = n / FPS
    sup = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    c = cairo.Context(sup)
    c.set_source_rgb(*PAREDE)
    c.paint()
    d = Doodle(c, n, cena.get("traco", ""))
    c.save()
    # transição de entrada da cena (no lugar do corte seco): soco (zoom rápido), desliza (entra de lado), iris
    trans = cena.get("transicao", "")
    if trans == "soco":
        z = 1 + 0.18 * (1 - suave(t, 0, 0.22))
        c.translate(W / 2, H / 2)
        c.scale(z, z)
        c.translate(-W / 2, -H / 2)
    elif trans == "desliza":
        c.translate(W * 0.7 * (1 - suave(t, 0, 0.25)) ** 2, 0)
    elif trans == "iris" and t < 0.3:
        c.set_source_rgb(*TINTA)
        c.paint()
        c.arc(W / 2, H * 0.45, 60 + 1400 * suave(t, 0, 0.3), 0, 2 * math.pi)
        c.clip()
        c.set_source_rgb(*PAREDE)
        c.paint()
    # câmera: leve aproximação contínua; 'susto' treme no início
    c.save()
    zoom = {"aproxima": 1 + 0.07 * suave(t, 0, cena.get("duracao", 4)), "afasta": 1.08 - 0.07 * suave(t, 0, 3)}.get(
        cena.get("camera", "aproxima"), 1.0)
    fx, fy = cena.get("foco", (540, 800))
    c.translate(fx, fy)
    c.scale(zoom, zoom)
    c.translate(-fx, -fy)
    c.translate(W / 2, PES_TELA)
    c.scale(ENQUADRA, ENQUADRA)
    c.translate(-W / 2, -PES)
    if cena.get("camera") == "lado":  # câmera passeando devagar de lado
        c.translate(40 - 80 * suave(t, 0, cena.get("duracao", 4)), 0)
    if cena.get("susto"):
        k = max(0.0, 1 - t / 0.5)
        c.translate(math.sin(t * 90) * 18 * k, math.cos(t * 77) * 12 * k)
    cenario(d, cena.get("cenario", ""), t)
    for e in cena["elementos"]:
        if e.get("sai") is not None and t >= e["sai"]:
            continue
        c.save()
        try:  # elemento malformado (campo faltando, tipo errado) some da cena em vez de derrubar o vídeo
            if e["tipo"] in ("bob", "amigo") and (e.get("corpo") or cena.get("corpo")) == "vivo":
                import bob_vivo  # corpo "vivo" (opção): linha de ação, camisa com sombra, reação de pose
                esc = e.get("escala", 1.0) * pop(t, e.get("entra", 0), 0.4)
                if esc > 0.01:
                    pose = e.get("pose_vivo") or bob_vivo.DAS_ETIQUETAS.get(e.get("pose_nome", ""), "neutro")
                    bob_vivo.desenhar(d, {"x": e.get("x", 540), "olha": e.get("olha", 1), "escala": esc,
                                          "cor": e["tipo"], "pose": pose, "fala": e.get("fala")}, t, PES)
            elif e["tipo"] in ("bob", "amigo"):
                personagem(d, {"quem": e["tipo"], **e}, t)
            elif e["tipo"] in OBJETOS:
                if e["tipo"] in ("zigue", "seta", "xis"):  # têm a entrada deles
                    OBJETOS[e["tipo"]](d, e, t)
                elif _entrada(c, e, t, *_ancora(e)):
                    OBJETOS[e["tipo"]](d, e, t)
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, cairo.Error):
            c.new_path()
        c.restore()
    if cena.get("clima") == "chuva":
        chuva(d, t)
    c.restore()
    c.restore()  # transição
    return sup


def renderizar(cena: dict, destino: Path) -> None:
    total = round(cena.get("duracao", 5) * FPS)
    destino.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(destino)],
        stdin=subprocess.PIPE)
    for n in range(total):
        sup = quadro(cena, n)
        sup.flush()
        proc.stdin.write(bytes(sup.get_data()))
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError(f"ffmpeg falhou em {destino}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--so", type=int, nargs="*", help="só estas cenas (1 = primeira)")
    ap.add_argument("--png", action="store_true", help="só um quadro por cena, para prévia")
    args = ap.parse_args()
    dados = json.loads(Path(args.arquivo).read_text(encoding="utf-8"))
    pasta = caminhos.PRODUCAO / "midia" / dados["slug"]
    for i, cena in enumerate(dados["cenas"], 1):
        if args.so and i not in args.so:
            continue
        if args.png:
            pasta.mkdir(parents=True, exist_ok=True)
            quadro(cena, round(min(cena.get("duracao", 5), 1.6) * FPS)).write_to_png(str(pasta / f"previa_{i:02d}.png"))
            print(f"previa {i:02d}")
            continue
        renderizar(cena, pasta / f"cena_{i:02d}.mp4")
        print(f"cena {i:02d} ok", flush=True)


if __name__ == "__main__":
    main()
