import uuid

from django.db import models

ETAPAS_VIDEO = [("roteiro", "Roteiro"), ("voz", "Voz e legenda"), ("imagens", "Imagens"),
                ("montagem", "Montagem"), ("post", "Pacote de postagem")]


class Job(models.Model):
    """Um trabalho do pipeline pedido pela tela: escrever um roteiro ou gerar um vídeo."""

    class Tipo(models.TextChoices):
        ROTEIRO = "roteiro", "Roteiro"
        VIDEO = "video", "Vídeo"

    class Status(models.TextChoices):
        FILA = "fila", "Na fila"
        RODANDO = "rodando", "Rodando"
        OK = "ok", "Pronto"
        ERRO = "erro", "Erro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FILA)
    etapa = models.CharField(max_length=20, blank=True)
    mensagem = models.CharField(max_length=300, blank=True)
    entrada = models.JSONField(default=dict)
    saida = models.JSONField(default=dict, blank=True)
    erro = models.TextField(blank=True)
    custos = models.JSONField(default=dict, blank=True)  # medidor: US$, R$, tokens e tempo por etapa
    criado = models.DateTimeField(auto_now_add=True)
    atualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado"]

    def __str__(self):
        return f"{self.get_tipo_display()} {str(self.id)[:8]} · {self.get_status_display()}"

    def etapas(self) -> list[dict]:
        if self.tipo != self.Tipo.VIDEO:
            return []
        chaves = [k for k, _ in ETAPAS_VIDEO]
        atual = chaves.index(self.etapa) if self.etapa in chaves else -1
        out = []
        for i, (k, nome) in enumerate(ETAPAS_VIDEO):
            if self.status == self.Status.OK or i < atual:
                estado = "feito"
            elif i == atual:
                estado = "erro" if self.status == self.Status.ERRO else "rodando"
            else:
                estado = "pendente"
            out.append({"chave": k, "nome": nome, "estado": estado})
        return out
