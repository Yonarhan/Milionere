"""Animação Manim (Space Atlas): a luz do Sol leva 8 min 19 s para chegar à Terra.

    python animacoes/luz_do_sol.py            # gera animacoes/saida/luz_do_sol.mp4 (1080x1920, 30 fps, ~5 s)

Vertical e com o miolo livre para a legenda do vídeo (o render coloca a legenda por cima).
Distância média Terra-Sol ~149,6 milhões de km; luz a ~300 mil km/s -> ~499 s: o cronômetro termina em 8:19.
"""

import random
from pathlib import Path

import manimpango
from manim import (DOWN, RIGHT, UP, Circle, DashedLine, Dot, FadeIn, GrowFromCenter, Scene, Text, UpdateFromAlphaFunc,
                   ValueTracker, VGroup, config, linear, rate_functions)

AQUI = Path(__file__).resolve().parent
FONTE = AQUI.parents[1] / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"
manimpango.register_font(str(FONTE))
FAMILIA = "Be Vietnam Pro"

config.pixel_width, config.pixel_height, config.frame_rate = 1080, 1920, 30
config.frame_width, config.frame_height = 9, 16
config.background_color = "#05070D"
config.media_dir = str(AQUI / "saida" / "_manim")
config.output_file = "luz_do_sol"

SOL, TERRA, LUZ = "#FDB813", "#2E86FF", "#FFF4C2"
SEGUNDOS_REAIS = 499  # 8 min 19 s


def estrelas(n: int = 140) -> VGroup:
    random.seed(7)
    return VGroup(*[Dot([random.uniform(-4.4, 4.4), random.uniform(-7.9, 7.9), 0], radius=random.uniform(0.008, 0.03),
                        color="#FFFFFF", fill_opacity=random.uniform(0.25, 0.9)) for _ in range(n)])


class LuzDoSol(Scene):
    def construct(self):
        self.add(estrelas())
        topo, base = UP * 5.2, DOWN * 5.6
        sol = VGroup(*[Circle(radius=1.15 + k * 0.28, color=SOL, fill_opacity=0.10 - k * 0.025, stroke_width=0)
                       for k in range(4)], Circle(radius=1.15, color=SOL, fill_color=SOL, fill_opacity=1, stroke_width=0))
        sol.move_to(topo)
        terra = Circle(radius=0.32, color=TERRA, fill_color=TERRA, fill_opacity=1, stroke_width=0).move_to(base)
        brilho_terra = Circle(radius=0.5, color=TERRA, fill_opacity=0.18, stroke_width=0).move_to(base)
        nome_sol = Text("Sol", font=FAMILIA, font_size=34, color="#FFFFFF").next_to(sol, DOWN, buff=0.25)
        nome_terra = Text("Terra", font=FAMILIA, font_size=34, color="#FFFFFF").next_to(terra, DOWN, buff=0.2)
        trilha = DashedLine(topo + DOWN * 1.5, base + UP * 0.45, dash_length=0.12, color="#8A93A6", stroke_width=2)

        t = ValueTracker(0)
        relogio = Text("0:00", font=FAMILIA, font_size=86, color=LUZ).move_to(UP * 2.2 + [2.3, 0, 0])

        def atualiza_relogio(m):
            s = round(t.get_value() * SEGUNDOS_REAIS)
            novo = Text(f"{s // 60}:{s % 60:02d}", font=FAMILIA, font_size=86, color=LUZ).move_to(m.get_center())
            m.become(novo)

        relogio.add_updater(atualiza_relogio)
        pulso = VGroup(Dot(radius=0.13, color=LUZ), Circle(radius=0.3, color=LUZ, fill_opacity=0.25, stroke_width=0))
        pulso.move_to(trilha.get_start())

        def anda(m, a):
            m.move_to(trilha.get_start() + (trilha.get_end() - trilha.get_start()) * a)
            t.set_value(a)

        self.play(FadeIn(sol, scale=0.8), FadeIn(nome_sol), run_time=0.5)
        self.play(GrowFromCenter(terra), FadeIn(brilho_terra), FadeIn(nome_terra), FadeIn(trilha), FadeIn(relogio),
                  run_time=0.4)
        self.add(pulso)
        self.play(UpdateFromAlphaFunc(pulso, anda), run_time=3.0, rate_func=linear)
        relogio.clear_updaters()
        distancia = Text("150 milhões de km", font=FAMILIA, font_size=32, color="#FFFFFF").next_to(relogio, DOWN, buff=0.2)
        distancia.to_edge(RIGHT, buff=0.35)  # não passa da borda nem cruza a trilha da luz
        self.play(FadeIn(distancia, shift=UP * 0.2), brilho_terra.animate.scale(1.5).set_opacity(0.35),
                  run_time=0.5, rate_func=rate_functions.ease_out_sine)
        self.wait(0.8)


if __name__ == "__main__":
    LuzDoSol().render()
    feito = next((AQUI / "saida" / "_manim").rglob("luz_do_sol.mp4"))
    destino = AQUI / "saida" / "luz_do_sol.mp4"
    destino.parent.mkdir(exist_ok=True)
    destino.write_bytes(feito.read_bytes())
    print(f"PRONTO {destino}")
