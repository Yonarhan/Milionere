"""Bob "vivo" (opção de personagem, 28/09/2026): corpo que atua junto com o rosto.

O que dá vida, tirado das referências que o Yonarhan mandou:
- tronco com volume (camisa branca) que inclina, pernas com joelho, peso jogado para um lado;
- cabeça oval e inclinada, rosto ASSIMÉTRICO (um olho maior, pupilas olhando para o lado, sobrancelha com tensão);
- mãos pretas com dedos (abertas, fechadas, apontando);
- pose do corpo inteiro por emoção (medo encolhe, "sei lá" sobe os ombros e abre as palmas).

Coordenadas: pés em (0, 0), altura total ~720; `lado` 1 = olhando para a direita.
"""

import math

from animacao_codigo import AZUL, TINTA, Doodle

BOCA_ESCURA = (0.45, 0.08, 0.12)
LINGUA = (0.93, 0.45, 0.50)

# cada pose: inclinação do tronco (graus, + = para a frente), agachamento (0-1), abertura das pernas, braços
# (ângulo do ombro e do cotovelo em graus: 0 = para baixo, 90 = para a frente, 180 = para cima), mãos, cabeça,
# e o rosto (olhos, pupilas, sobrancelhas, boca)
POSES = {
    # braços: ângulo positivo abre para o LADO DAQUELE braço (o de trás abre para trás); negativo cruza o corpo
    "neutro": dict(tronco=0, agacha=0, pernas=40, ombros=0,
                   braco_f=(12, 8, "aberta"), braco_t=(12, 8, "aberta"), cabeca=3,
                   olhos=(1.0, 1.0), olhar=(0.3, 0), sob=("reta", "reta"), boca="sorriso"),
    "sei_la": dict(tronco=-4, agacha=0, pernas=45, ombros=28,
                   braco_f=(40, 80, "palma"), braco_t=(40, 80, "palma"), cabeca=-8,
                   olhos=(1.0, 0.85), olhar=(0.4, -0.2), sob=("sobe", "franze"), boca="torta"),
    "medo": dict(tronco=-14, agacha=0.35, pernas=110, ombros=20,
                 braco_f=(60, 110, "punho"), braco_t=(40, 120, "punho"), cabeca=-12,
                 olhos=(1.25, 0.9), olhar=(0.8, 0.1), sob=("medo", "medo"), boca="grito", olheira=True),
    "explica": dict(tronco=6, agacha=0, pernas=55, ombros=0,
                    braco_f=(95, 20, "aponta"), braco_t=(15, 25, "aberta"), cabeca=6,
                    olhos=(1.0, 1.05), olhar=(0.6, 0), sob=("sobe", "reta"), boca="fala"),
    "pensa": dict(tronco=-3, agacha=0, pernas=35, ombros=5,
                  braco_f=(150, 150, "punho"), braco_t=(15, -100, "punho"), cabeca=-10,
                  olhos=(0.9, 1.05), olhar=(0.4, -0.7), sob=("franze", "sobe"), boca="biquinho"),
    "comemora": dict(tronco=-6, agacha=0.1, pernas=70, ombros=10,
                     braco_f=(150, 25, "punho"), braco_t=(150, 25, "punho"), cabeca=-6,
                     olhos=(1.1, 1.1), olhar=(0, -0.3), sob=("sobe", "sobe"), boca="sorrisao", pula=True),
    "desconfia": dict(tronco=-8, agacha=0, pernas=40, ombros=6,
                      braco_f=(20, -110, "punho"), braco_t=(20, -110, "punho"), cabeca=10,
                      olhos=(0.75, 1.0), olhar=(0.9, 0), sob=("franze", "sobe"), boca="reta"),
    "confiante": dict(tronco=-10, agacha=0, pernas=35, ombros=4,  # mãos na cintura, olhos fechados, sorriso
                      braco_f=(38, -77, "punho"), braco_t=(38, -77, "punho"), cabeca=-14,
                      olhos=(1.0, 1.0), olhar=(0, 0), sob=("sobe", "sobe"), boca="sorriso", olhos_fechados=True),
    "cansado": dict(tronco=12, agacha=0.15, pernas=35, ombros=-10,
                    braco_f=(5, 5, "aberta"), braco_t=(5, 5, "aberta"), cabeca=14,
                    olhos=(0.7, 0.7), olhar=(0, 0.5), sob=("triste", "triste"), boca="triste", olheira=True),
}


# linha de ação por pose: "arco" > 0 = peito para trás (confiante, comemorando); < 0 = corcunda (medo, cansado).
# "simples" = rosto econômico (olhos pequenos), para as poses calmas; as emoções fortes mantêm os olhos grandes.
for _nome, _arco, _simples in (("neutro", 6, True), ("sei_la", 8, False), ("medo", -22, False),
                               ("explica", -6, True), ("pensa", 4, False), ("comemora", 18, False),
                               ("desconfia", 10, False), ("confiante", 30, True), ("cansado", -28, False)):
    POSES[_nome].update(arco=_arco, simples=_simples)

TRACO_FINO = 4.5  # traço de caneta: mais fino = mais elegante
SOMBRA = (0.80, 0.86, 0.94)


def _membro(d: Doodle, p0, junta, p2, larg=TRACO_FINO, raio=38):
    """Braço/perna quase reto com a junta arredondada (cotovelo/joelho suave, sem quina e sem virar 'macarrão')."""
    la = math.hypot(junta[0] - p0[0], junta[1] - p0[1]) or 1
    lb = math.hypot(p2[0] - junta[0], p2[1] - junta[1]) or 1
    k = min(raio, la * 0.45, lb * 0.45)
    a = (junta[0] + (p0[0] - junta[0]) * k / la, junta[1] + (p0[1] - junta[1]) * k / la)
    b = (junta[0] + (p2[0] - junta[0]) * k / lb, junta[1] + (p2[1] - junta[1]) * k / lb)
    curva = [((1 - u) ** 2 * a[0] + 2 * (1 - u) * u * junta[0] + u * u * b[0],
              (1 - u) ** 2 * a[1] + 2 * (1 - u) * u * junta[1] + u * u * b[1]) for u in (i / 8 for i in range(9))]
    d.linha([p0] + curva + [p2], larg=larg)


def _arredondar(pts, r=16, passos=5):
    """Polígono com cantos arredondados (camisa, calça): cada quina vira um arco."""
    saida = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        la, lc = math.hypot(a[0] - b[0], a[1] - b[1]), math.hypot(c[0] - b[0], c[1] - b[1])
        k = min(r, la / 2, lc / 2)
        p_in = (b[0] + (a[0] - b[0]) * k / la, b[1] + (a[1] - b[1]) * k / la)
        p_out = (b[0] + (c[0] - b[0]) * k / lc, b[1] + (c[1] - b[1]) * k / lc)
        for s in range(passos + 1):  # bézier quadrática com a quina como controle
            u = s / passos
            saida.append(((1 - u) ** 2 * p_in[0] + 2 * (1 - u) * u * b[0] + u * u * p_out[0],
                          (1 - u) ** 2 * p_in[1] + 2 * (1 - u) * u * b[1] + u * u * p_out[1]))
    return saida


def _rot(px, py, ang):
    a = math.radians(ang)
    return px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a)


def _mao(d: Doodle, x, y, ang, tipo, lado):
    """Luva preta: aberta (dedos), palma (virada para cima), punho, aponta (indicador)."""
    c = d.c
    c.save()
    c.translate(x, y)
    c.rotate(math.radians(ang))
    c.set_source_rgb(*TINTA)
    c.save(); c.scale(1.0, 0.8); c.arc(0, 8, 17, 0, 2 * math.pi); c.restore(); c.fill()
    if tipo in ("aberta", "palma"):
        for k, a in enumerate((-50, -20, 10, 40)):
            dx, dy = math.sin(math.radians(a)), math.cos(math.radians(a))
            d.linha([(dx * 12, 8 + dy * 12), (dx * 32, 8 + dy * 32)], larg=8, amp=0)
        d.linha([(-14 * lado, 4), (-28 * lado, -8)], larg=8, amp=0)  # polegar
    elif tipo == "aponta":
        d.linha([(0, 10), (0, 44)], larg=9, amp=0)
    c.restore()


def _braco(d: Doodle, sx, sy, ombro, cotovelo, mao, lado, t):
    """Braço em duas partes por ângulos (0 = para baixo, 90 = para a frente)."""
    L1, L2 = 120, 110
    a1 = math.radians(ombro)
    ex, ey = sx + lado * math.sin(a1) * L1, sy + math.cos(a1) * L1
    a2 = math.radians(ombro + cotovelo)
    hx, hy = ex + lado * math.sin(a2) * L2, ey + math.cos(a2) * L2
    d.linha([(sx, sy), (ex, ey), (hx, hy)], larg=6)
    _mao(d, hx, hy, -lado * math.degrees(a2), mao, lado)


def _olho(d: Doodle, x, y, esc, olhar, sob, lado, piscando):
    rx, ry = 24 * esc, 30 * esc
    if piscando:
        d.linha([(x - rx, y), (x + rx, y)], larg=5)
    else:
        d.elipse(x, y, rx, ry, preencher=(1, 1, 1), larg=5)
        px, py = x + olhar[0] * rx * 0.55, y + olhar[1] * ry * 0.5
        d.ponto(px, py, 10 * esc)
    by = y - ry - 16
    if sob == "sobe":
        d.curva((x - rx, by + 4), (x, by - 16), (x + rx, by + 2), larg=5)
    elif sob == "franze":  # sobrancelha baixa e tensa (desconfiança/brabeza)
        d.linha([(x - rx * lado, by + 2), (x + rx * lado, by + 12)], larg=6)
    elif sob == "medo":
        d.curva((x - rx * lado, by + 10), (x, by - 8), (x + rx * lado, by - 14), larg=5)
    elif sob == "triste":  # ponta de dentro mais alta
        d.linha([(x - rx * lado, by), (x + rx * lado, by + 12)], larg=5)
    else:
        d.linha([(x - rx, by), (x + rx, by)], larg=5)


def _boca(d: Doodle, x, y, tipo, t, lado):
    if tipo == "fala":
        ab = abs(math.sin(t * 11)) * 0.8 + abs(math.sin(t * 5.3)) * 0.3
        d.elipse(x, y, 24, 6 + 20 * ab, preencher=BOCA_ESCURA, larg=5)
    elif tipo == "grito":  # boca aberta de pavor, com dentes
        pts = [(x + 34 * math.cos(a), y + 26 * math.sin(a) + (6 if math.sin(a) > 0 else 0)) for a in
               (i * 2 * math.pi / 24 for i in range(24))]
        d.linha(pts, fechar=True, preencher=BOCA_ESCURA, larg=5)
        d.linha([(x - 20, y - 14), (x + 18, y - 14), (x + 14, y - 5), (x - 16, y - 5)], cor=None, fechar=True, preencher=(1, 1, 1))
    elif tipo == "sorrisao":
        d.linha([(x - 38, y - 6)] + [(x + 38 * math.cos(math.pi * i / 12), y - 6 + 34 * math.sin(math.pi * i / 12))
                                     for i in range(13)], fechar=True, preencher=BOCA_ESCURA, larg=5)
        d.elipse(x + 6, y + 16, 16, 8, cor=None, preencher=LINGUA)
    elif tipo == "torta":  # "hum" torto de lado
        d.curva((x - 22, y + 4), (x, y - 4), (x + 20, y + 8), larg=5)
    elif tipo == "triste":
        d.curva((x - 20, y + 8), (x, y - 6), (x + 20, y + 8), larg=5)
    elif tipo == "biquinho":
        d.circulo(x + 10 * lado, y, 7, preencher=BOCA_ESCURA, larg=4)
    elif tipo == "reta":
        d.linha([(x - 20, y), (x + 16, y - 3)], larg=5)
    else:
        d.curva((x - 24, y - 4), (x, y + 12), (x + 24, y - 4), larg=5)


# poses do Bob "de palito" (etiquetas) -> pose do Bob vivo mais próxima
DAS_ETIQUETAS = {
    "explica": "explica", "fala": "explica", "segura": "explica", "come": "explica", "calmo": "neutro",
    "chocado": "medo", "nervoso": "medo", "eita": "medo", "tonto": "medo", "empurra": "medo", "corre": "medo",
    "surpreso": "sei_la", "confuso": "sei_la", "encolhe": "sei_la",
    "feliz": "comemora", "rindo": "comemora", "encantado": "comemora", "deslumbrado": "comemora",
    "orgulhoso": "confiante", "joinha": "confiante", "zoeira": "confiante", "apaixonado": "confiante",
    "pensando": "pensa", "sussurro": "pensa", "curioso": "pensa",
    "vergonha": "cansado", "triste": "cansado", "cansado": "cansado", "bocejo": "cansado", "dormindo": "cansado",
    "chorando": "cansado", "bravo": "desconfia", "desconfiado": "desconfia",
}
FORTES = {"medo", "sei_la", "comemora", "desconfia", "cansado"}  # emoções que o Bob "vira" durante a cena


def _misturar(a: dict, b: dict, k: float) -> dict:
    """Transição entre poses: números e tuplas numéricas interpolam; o resto troca no meio."""
    saida = {}
    for chave in set(a) | set(b):
        va, vb = a.get(chave, b.get(chave)), b.get(chave, a.get(chave))
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
            saida[chave] = va + (vb - va) * k
        elif isinstance(va, tuple) and isinstance(vb, tuple) and len(va) == len(vb):
            saida[chave] = tuple(x + (y - x) * k if isinstance(x, (int, float)) and isinstance(y, (int, float))
                                 else (y if k > 0.5 else x) for x, y in zip(va, vb))
        else:
            saida[chave] = vb if k > 0.5 else va
    return saida


def pose_no_tempo(e: dict, t: float) -> dict:
    """Pose do quadro: emoção forte começa no neutro e VIRA a emoção (reação) entre 0,25 s e 0,6 s."""
    alvo = {**POSES["neutro"], **POSES.get(e.get("pose", "neutro"), {})}
    if e.get("pose") in FORTES and e.get("reage", True):
        x = min(1.0, max(0.0, (t - 0.25) / 0.35))
        k = x * x * (3 - 2 * x)
        k = k + 0.08 * math.sin(min(1.0, max(0.0, (t - 0.6) / 0.3)) * math.pi)  # passa um pouco e assenta
        return _misturar(POSES["neutro"], alvo, k)
    return alvo


def desenhar(d: Doodle, e: dict, t: float, pes_y: float) -> None:
    """Corpo com LINHA DE AÇÃO: a espinha é uma curva (quadril para a frente, peito e cabeça para trás, ou corcunda),
    a camisa acompanha a curva e tem sombra suave de um lado; traço fino; sem faixa de calça; rosto econômico nas
    poses calmas."""
    p = pose_no_tempo(e, t)
    lado = e.get("olha", 1)
    c = d.c
    c.save()
    pulo = -abs(math.sin(t * 6)) * 40 if p.get("pula") and t > 0.6 else 0
    c.translate(e.get("x", 540), pes_y)
    c.scale(e.get("escala", 1.0), e.get("escala", 1.0))
    c.save(); c.scale(1, 0.14); c.arc(0, 0, 85, 0, 2 * math.pi); c.set_source_rgba(0, 0, 0, 0.12); c.fill(); c.restore()
    c.translate(0, pulo)
    agacha = p["agacha"] * 120
    respira = math.sin(t * 2.3) * 3
    arco = p["arco"] + math.sin(t * 1.7 + e.get("x", 0)) * 2  # a curva "respira" de leve
    atras = -lado  # direção "para trás" de quem olha para `lado`
    # espinha: quadril -> ombros, curva quadrática; o quadril vai para a frente quando o peito vai para trás
    Q = (-atras * arco * 0.9, -290 + agacha)
    ang = math.radians(p["tronco"] * lado)
    up = (math.sin(ang), -math.cos(ang))
    alt = 280 + respira
    T = (Q[0] + up[0] * alt + atras * arco * 1.3, Q[1] + up[1] * alt)
    C = (Q[0] + up[0] * alt * 0.5 + atras * arco * 2.2, Q[1] + up[1] * alt * 0.5)

    def espinha(u):
        return ((1 - u) ** 2 * Q[0] + 2 * (1 - u) * u * C[0] + u * u * T[0],
                (1 - u) ** 2 * Q[1] + 2 * (1 - u) * u * C[1] + u * u * T[1])

    def normal(u):
        dx = 2 * (1 - u) * (C[0] - Q[0]) + 2 * u * (T[0] - C[0])
        dy = 2 * (1 - u) * (C[1] - Q[1]) + 2 * u * (T[1] - C[1])
        n = math.hypot(dx, dy) or 1
        return (-dy / n, dx / n), (dx / n, dy / n)

    us = [i / 10 for i in range(11)]
    esq, dir_ = [], []
    for u in us:
        (nx, ny), _ = normal(u)
        w = 36 + 8 * u  # um pouco mais largo nos ombros
        sx, sy = espinha(u)
        esq.append((sx - nx * w, sy - ny * w))
        dir_.append((sx + nx * w, sy + ny * w))
    camisa = _arredondar(esq + dir_[::-1], 14)
    # pernas saindo direto da camisa (sem faixa de calça)
    (n0x, n0y), _ = normal(0)
    for k in (-1, 1):
        topo = (Q[0] + n0x * 20 * k, Q[1] + n0y * 20 * k + 4)
        pe = (k * p["pernas"] * 0.7 + (10 if k == lado else 0), 0)
        joelho = ((topo[0] + pe[0]) / 2 + lado * (8 + agacha * 0.45), (topo[1] + pe[1]) / 2)
        _membro(d, topo, joelho, pe)
        d.curva(pe, (pe[0] + lado * 8, pe[1] + 3), (pe[0] + lado * 22, pe[1]), larg=TRACO_FINO + 1)
    (nTx, nTy), (tTx, tTy) = normal(1)
    wT = 44
    sobe = p["ombros"] * 0.7
    # ombro da frente = o lado da normal que aponta para onde ele olha
    frente_sinal = 1 if nTx * lado > 0 else -1
    ombro_f = (T[0] + nTx * wT * frente_sinal, T[1] + nTy * wT * frente_sinal - sobe + 10)
    ombro_t = (T[0] - nTx * wT * frente_sinal, T[1] - nTy * wT * frente_sinal - sobe + 10)
    ang_topo = math.degrees(math.atan2(tTx, -tTy))
    _braco_vivo(d, ombro_t, p["braco_t"], -lado, ang_topo)
    # camisa: branco + sombra suave do lado de trás + contorno fino
    d.linha(camisa, cor=None, fechar=True, preencher=(1, 1, 1))
    c.save()
    d._tracar(camisa, True)
    c.clip()
    sombra = []
    for u in us:
        (nx, ny), _ = normal(u)
        sx, sy = espinha(u)
        s = -frente_sinal
        sombra.append((sx + nx * s * 10, sy + ny * s * 10))
    for u in us[::-1]:
        (nx, ny), _ = normal(u)
        sx, sy = espinha(u)
        s = -frente_sinal
        sombra.append((sx + nx * s * 60, sy + ny * s * 60))
    d.linha(sombra, cor=None, fechar=True, preencher=SOMBRA)
    c.restore()
    d.linha(camisa, fechar=True, larg=TRACO_FINO)
    # pescoço na direção da espinha e cabeça tombando junto com a curva
    pesc = (T[0] + tTx * 58, T[1] + tTy * 58)
    d.curva(T, ((T[0] + pesc[0]) / 2 + atras * 3, (T[1] + pesc[1]) / 2), pesc, larg=TRACO_FINO)
    c.save()
    c.translate(pesc[0] + tTx * 62, pesc[1] + tTy * 62)
    c.rotate(math.radians(ang_topo + (p["cabeca"] + p["arco"] * 0.5) * lado * 0.6
                          + math.sin(t * 5) * (2.5 if e.get("fala") else 0.6)))
    d.elipse(0, 0, 64, 66, preencher=AZUL if e.get("cor") == "amigo" else (1, 1, 1), larg=TRACO_FINO + 0.5)
    fx = lado * 14
    fechados = p.get("olhos_fechados")
    piscando = (t + e.get("x", 0) * 0.01) % 3.1 < 0.1
    if p.get("simples"):  # rosto econômico: olhos pequenos (ou arcos fechados), boca simples
        for k in (-1, 1):
            ox = fx + k * 20
            if fechados or piscando:
                d.arco(ox, -8, 11, math.pi * 1.15, math.pi * 1.85, larg=3.5)
            else:
                d.ponto(ox + lado * 3, -10, 6)
        d.curva((fx - 16 + lado * 4, 22), (fx + lado * 4, 34), (fx + 16 + lado * 4, 22), larg=3.5)
        if e.get("fala"):
            ab = abs(math.sin(t * 11)) * 0.8
            d.elipse(fx + lado * 4, 28, 11, 3 + 9 * ab, preencher=BOCA_ESCURA, larg=3)
    else:
        olhar = (p["olhar"][0] * lado + (0.25 if (t * 0.7) % 2.3 < 0.25 else 0) * lado, p["olhar"][1])
        for k, (esc_o, sob) in enumerate(zip(p["olhos"], p["sob"])):
            ox = fx + (k * 2 - 1) * 25 * lado
            _olho(d, ox, -12, esc_o * 0.82, olhar, sob, lado if k else -lado, piscando or fechados)
            if p.get("olheira"):
                d.curva((ox - 10, 14), (ox, 18), (ox + 10, 14), larg=2.5)
        c.save()
        c.translate(fx + lado * 4, 32)
        c.scale(0.65, 0.65)
        _boca(d, 0, 0, "fala" if e.get("fala") and p["boca"] in ("sorriso", "fala") else p["boca"], t, lado)
        c.restore()
    c.restore()
    _braco_vivo(d, ombro_f, p["braco_f"], lado, ang_topo)
    c.restore()


def desenhar_blocos(d: Doodle, e: dict, t: float, pes_y: float) -> None:
    """Versão anterior (tronco retangular + faixa de calça). Proporções da referência: cabeça pequena num pescoço comprido, camisa estreita e comprida com faixa de calça,
    braços longos saindo dos CANTOS de cima da camisa, pernas longas saindo da calça; o tronco gira no quadril."""
    p = {**POSES["neutro"], **POSES.get(e.get("pose", "neutro"), {})}
    lado = e.get("olha", 1)
    esc = e.get("escala", 1.0)
    c = d.c
    c.save()
    pulo = -abs(math.sin(t * 6)) * 40 if p.get("pula") else 0
    c.translate(e.get("x", 540), pes_y)
    c.scale(esc, esc)
    c.save(); c.scale(1, 0.14); c.arc(0, 0, 90, 0, 2 * math.pi); c.set_source_rgba(0, 0, 0, 0.12); c.fill(); c.restore()
    c.translate(0, pulo)
    agacha = p["agacha"] * 120
    balanco = math.sin(t * 1.7 + e.get("x", 0)) * 3
    # quadril (base da calça) um pouco para a frente quando o tronco inclina para trás: a curva do corpo
    qx = balanco * lado - p["tronco"] * lado * 0.8
    qy = -330 + agacha
    # pernas longas com joelho, saindo da calça
    for k in (-1, 1):
        pe = (k * p["pernas"] * 0.8 + (10 if k == lado else 0), 0)
        topo = (qx + k * 22, qy)
        joelho = ((topo[0] + pe[0]) / 2 + lado * (10 + agacha * 0.45), (topo[1] + pe[1]) / 2 - 4)
        _membro(d, topo, joelho, pe)
        d.curva(pe, (pe[0] + lado * 8, pe[1] + 3), (pe[0] + lado * 24, pe[1]), larg=7)  # pé com ponta arredondada
    # parte de cima gira em volta do quadril
    ang = p["tronco"] * lado
    resp = math.sin(t * 2.3) * 3
    R = lambda x, y: (qx + _rot(x, y, ang)[0], qy + _rot(x, y, ang)[1])  # noqa: E731
    calca = [R(-40, 0), R(40, 0), R(42, -55), R(-42, -55)]
    camisa = [R(-42, -55), R(42, -55), R(46, -270 - resp), R(-46, -270 - resp)]
    sobe = p["ombros"] * 0.7
    ombro_f = R(46 * lado, -262 - resp - sobe)
    ombro_t = R(-46 * lado, -262 - resp - sobe)
    pescoco_base = R(0, -270 - resp)
    pescoco_topo = R(4 * lado, -330 - resp)
    _braco_vivo(d, ombro_t, p["braco_t"], -lado, ang)
    d.linha(_arredondar(calca, 10), fechar=True, preencher=(1, 1, 1), larg=6)
    d.linha(_arredondar(camisa, 18), fechar=True, preencher=(1, 1, 1), larg=6)
    d.curva(pescoco_base, ((pescoco_base[0] + pescoco_topo[0]) / 2 - lado * 3, (pescoco_base[1] + pescoco_topo[1]) / 2),
            pescoco_topo, larg=6)
    # cabeça pequena, inclinada
    c.save()
    c.translate(pescoco_topo[0] + lado * 4, pescoco_topo[1] - 68)
    c.rotate(math.radians(p["cabeca"] * lado + ang * 0.5 + math.sin(t * 5) * (2.5 if e.get("fala") else 0.6)))
    d.elipse(0, 0, 70, 74, preencher=AZUL if e.get("cor") == "amigo" else (1, 1, 1), larg=6)
    fx = lado * 16
    piscando = (t + e.get("x", 0) * 0.01) % 3.1 < 0.1
    olhar = (p["olhar"][0] * lado + (0.25 if (t * 0.7) % 2.3 < 0.25 else 0) * lado, p["olhar"][1])
    for k, (esc_o, sob) in enumerate(zip(p["olhos"], p["sob"])):
        ox = fx + (k * 2 - 1) * 27 * lado
        _olho(d, ox, -14, esc_o * 0.92, olhar, sob, lado if k else -lado, piscando or p.get("olhos_fechados"))
        if p.get("olheira"):
            d.curva((ox - 11, 14), (ox, 18), (ox + 11, 14), larg=3)
    c.save()
    c.translate(fx + lado * 4, 34)
    c.scale(0.7, 0.7)
    _boca(d, 0, 0, "fala" if e.get("fala") and p["boca"] in ("sorriso", "fala") else p["boca"], t, lado)
    c.restore()
    c.restore()
    _braco_vivo(d, ombro_f, p["braco_f"], lado, ang)
    c.restore()


def _braco_vivo(d: Doodle, ombro, spec, lado, ang_tronco):
    """Braço longo saindo do canto da camisa; os ângulos acompanham a inclinação do tronco."""
    ombro_ang, cotovelo, mao = spec
    L1, L2 = 150, 140
    a1 = math.radians(ombro_ang) + math.radians(ang_tronco) * lado * 0.5
    ex, ey = ombro[0] + lado * math.sin(a1) * L1, ombro[1] + math.cos(a1) * L1
    a2 = a1 + math.radians(cotovelo)
    hx, hy = ex + lado * math.sin(a2) * L2, ey + math.cos(a2) * L2
    _membro(d, ombro, (ex, ey), (hx, hy))
    _mao(d, hx, hy, -lado * math.degrees(a2), mao, lado)


def desenhar_antigo(d: Doodle, e: dict, t: float, pes_y: float) -> None:
    """e: {x, pose, olha, cor ('bob' branco / 'amigo' azul), escala, fala}"""
    p = {**POSES["neutro"], **POSES.get(e.get("pose", "neutro"), {})}
    lado = e.get("olha", 1)
    esc = e.get("escala", 1.0)
    c = d.c
    c.save()
    # vida: o peso balança de leve, respiração, pulo na comemoração
    balanco = math.sin(t * 1.7 + e.get("x", 0)) * 2.5
    pulo = -abs(math.sin(t * 6)) * 40 if p.get("pula") else 0
    c.translate(e.get("x", 540), pes_y)
    c.scale(esc, esc)
    # sombra
    c.save(); c.scale(1, 0.16); c.arc(0, 0, 110, 0, 2 * math.pi); c.set_source_rgba(0, 0, 0, 0.12); c.fill(); c.restore()
    c.translate(0, pulo)
    agacha = p["agacha"] * 110
    quadril = (balanco * lado, -300 + agacha)
    # pernas com joelho (o joelho vai para a frente quando agacha)
    for k in (-1, 1):
        pe = (k * p["pernas"] + (12 if k == lado else 0), 0)
        joelho = ((quadril[0] + pe[0]) / 2 + lado * (18 + agacha * 0.5), (quadril[1] + pe[1]) / 2 - 6)
        d.linha([(quadril[0] + k * 22, quadril[1]), joelho, pe], larg=6)
        d.linha([pe, (pe[0] + lado * 26, pe[1])], larg=7)
    # tronco com volume, inclinado
    resp = math.sin(t * 2.3) * 3
    ang = p["tronco"] * lado
    cantos = [(-58, 0), (58, 0), (62, -230 - resp), (-62, -230 - resp)]
    tronco = [(quadril[0] + _rot(x, y, ang)[0], quadril[1] + _rot(x, y, ang)[1]) for x, y in cantos]
    ombro_d = tronco[2] if lado > 0 else tronco[3]
    ombro_t = tronco[3] if lado > 0 else tronco[2]
    sobe = -p["ombros"]
    ombro_d = (ombro_d[0], ombro_d[1] + sobe)
    ombro_t = (ombro_t[0], ombro_t[1] + sobe)
    _braco(d, ombro_t[0] - lado * 6, ombro_t[1] + 14, p["braco_t"][0], p["braco_t"][1], p["braco_t"][2], -lado, t)
    d.linha(tronco, fechar=True, preencher=(1, 1, 1), larg=6)
    # pescoço e cabeça oval, inclinada, com o rosto deslocado para onde olha
    topo = ((tronco[2][0] + tronco[3][0]) / 2, (tronco[2][1] + tronco[3][1]) / 2)
    cab_x, cab_y = topo[0] + lado * 6, topo[1] - 118
    d.linha([topo, (topo[0] + lado * 4, topo[1] - 16)], larg=6)
    c.save()
    c.translate(cab_x, cab_y)
    c.rotate(math.radians(p["cabeca"] * lado + math.sin(t * 5) * (2.5 if e.get("fala") else 0.6)))
    d.elipse(0, 0, 112, 120, preencher=AZUL if e.get("cor") == "amigo" else (1, 1, 1), larg=6)
    fx = lado * 30
    piscando = (t + e.get("x", 0) * 0.01) % 3.1 < 0.1
    # pupilas dão umas olhadinhas rápidas (sacadas) em vez de ficarem congeladas
    olhar = (p["olhar"][0] * lado + (0.25 if (t * 0.7) % 2.3 < 0.25 else 0) * lado, p["olhar"][1])
    for k, (esc_o, sob) in enumerate(zip(p["olhos"], p["sob"])):
        ox = fx + (k * 2 - 1) * 40 * lado
        _olho(d, ox, -18, esc_o, olhar, sob, lado if k else -lado, piscando)
        if p.get("olheira"):
            d.curva((ox - 16, 22), (ox, 28), (ox + 16, 22), larg=3)
    _boca(d, fx + lado * 6, 52, "fala" if e.get("fala") and p["boca"] in ("sorriso", "fala") else p["boca"], t, lado)
    c.restore()
    _braco(d, ombro_d[0] + lado * 6, ombro_d[1] + 14, p["braco_f"][0], p["braco_f"][1], p["braco_f"][2], lado, t)
    c.restore()
