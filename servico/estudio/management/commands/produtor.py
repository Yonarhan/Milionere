from django.core.management.base import BaseCommand

from estudio import producao


class Command(BaseCommand):
    help = "Gera os vídeos do nosso canal, um por vez, seguindo as metas do painel /canal"

    def add_arguments(self, parser):
        parser.add_argument("--uma-vez", action="store_true", help="gera no máximo um vídeo e sai")

    def handle(self, *args, **opts):
        producao.rodar(uma_vez=opts["uma_vez"], log=lambda m: self.stdout.write(m))
