"""Animação Manim (Space Atlas): o Sol some e a Terra sai da órbita em linha reta (pela tangente).

    python animacoes/orbita_reta.py            # gera animacoes/saida/orbita_reta.mp4 (1080x1920, 30 fps, ~4,5 s)

Física: sem a gravidade do Sol, a Terra segue reto na velocidade que tinha (~30 km/s), na direção tangente à
órbita. Na vida real isso começaria ~8 min depois (a gravidade também viaja na velocidade da luz); aqui o tempo
está comprimido. Órbita na parte de cima da tela: a legenda do vídeo passa embaixo.
"""

import random
from pathlib import Path

import numpy as np
import manimpango
from manim import (DOWN, UP, Circle, DashedLine, Dot, FadeIn, FadeOut, Scene, Text, UpdateFromAlphaFunc,
                   VGroup, config, linear, rate_functions)

AQUI = Path(__file__).resolve().parent
manimpango.register_font(str(AQUI.parents[1] / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"))
FAMILIA = "Be Vietnam Pro"

config.pixel_width, config.pixel_height, config.frame_rate = 1080, 1920, 30
config.frame_width, config.frame_height = 9, 16
config.background_color = "#05070D"
config.media_dir = str(AQUI / "saida" / "_manim")
config.output_file = "orbita_reta"

SOL, TERRA = "#FDB813", "#2E86FF"
CENTRO, RAIO = np.array([0.0, 2.6, 0.0]), 2.9
INICIO, SOLTA = np.radians(-70), np.radians(55)  # arco antes de o Sol sumir; solta no alto à direita (sai pro alto)


def estrelas(n: int = 140) -> VGroup:
    random.seed(11)
    return VGroup(*[Dot([random.uniform(-4.4, 4.4), random.uniform(-7.9, 7.9), 0], radius=random.uniform(0.008, 0.03),
                        color="#FFFFFF", fill_opacity=random.uniform(0.25, 0.9)) for _ in range(n)])


def ponto(theta: float) -> np.ndarray:
    return CENTRO + RAIO * np.array([np.cos(theta), np.sin(theta), 0.0])


class OrbitaReta(Scene):
    def construct(self):
        self.add(estrelas())
        sol = VGroup(*[Circle(radius=0.75 + k * 0.22, color=SOL, fill_opacity=0.10 - k * 0.025, stroke_width=0)
                       for k in range(4)], Circle(radius=0.75, fill_color=SOL, fill_opacity=1, stroke_width=0))
        sol.move_to(CENTRO)
        orbita = Circle(radius=RAIO, color="#8A93A6", stroke_width=2, stroke_opacity=0.7).move_to(CENTRO)
        terra = VGroup(Circle(radius=0.42, color=TERRA, fill_opacity=0.18, stroke_width=0),
                       Circle(radius=0.24, fill_color=TERRA, fill_opacity=1, stroke_width=0)).move_to(ponto(INICIO))
        rastro = VGroup()

        self.play(FadeIn(sol, scale=0.85), FadeIn(orbita), FadeIn(terra), run_time=0.5)

        def gira(m, a):
            m.move_to(ponto(INICIO + (SOLTA - INICIO) * a))
        self.play(UpdateFromAlphaFunc(terra, gira), run_time=1.5, rate_func=linear)

        # o Sol some: a órbita perde o sentido e some junto
        self.play(FadeOut(sol, scale=0.3), orbita.animate.set_stroke(opacity=0.12), run_time=0.45,
                  rate_func=rate_functions.ease_in_quad)

        saida = ponto(SOLTA)
        direcao = np.array([-np.sin(SOLTA), np.cos(SOLTA), 0.0])  # tangente no sentido do giro
        fim = saida + direcao * 9.0
        rastro = DashedLine(saida, saida + direcao * 0.01, dash_length=0.1, color="#9FC6FF", stroke_width=3)
        self.add(rastro)

        def reta(m, a):
            atual = saida + (fim - saida) * a
            m.move_to(atual)
            rastro.become(DashedLine(saida, atual, dash_length=0.1, color="#9FC6FF", stroke_width=3))
        rotulo = Text("em linha reta, a ~30 km/s", font=FAMILIA, font_size=34, color="#FFFFFF")
        rotulo.move_to(CENTRO + DOWN * (RAIO + 0.75))  # centralizado abaixo da órbita, acima da faixa da legenda
        self.play(UpdateFromAlphaFunc(terra, reta), FadeIn(rotulo, shift=UP * 0.2), run_time=1.6,
                  rate_func=rate_functions.ease_in_sine)
        self.wait(0.4)


if __name__ == "__main__":
    OrbitaReta().render()
    feito = next((AQUI / "saida" / "_manim").rglob("orbita_reta.mp4"))
    destino = AQUI / "saida" / "orbita_reta.mp4"
    destino.write_bytes(feito.read_bytes())
    print(f"PRONTO {destino}")
