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


# ------------------------------------------------------------------ produção do nosso canal (painel /canal)

class Canal(models.Model):
    """Meta de produção automática de um nicho do nosso canal."""

    nicho = models.CharField(max_length=20, primary_key=True)
    ativo = models.BooleanField(default=False)
    meta_dia = models.PositiveSmallIntegerField(default=3)
    musica = models.CharField(max_length=5, default="sem")  # com | sem: UM vídeo por produção, escolhido no painel
    # ia: imagens geradas (ComfyUI/Gemini/Cloudflare) | nativo: fotos, pinturas e vídeos de acervos grátis + ffmpeg
    imagens = models.CharField(max_length=10, default="ia")
    modo = models.CharField(max_length=10, default="unitario")  # unitario | serie | misto (o que o automático gera)
    serie_max = models.PositiveSmallIntegerField(default=3)  # teto de partes; a IA usa só as que a história aguenta
    serie_cada = models.PositiveSmallIntegerField(default=3)  # misto: 1 série a cada N vídeos únicos
    # opções do vídeo (padrão = como já funcionava)
    legenda = models.CharField(max_length=12, default="padrao")  # padrao (a do preset) | karaoke | word_by_word
    efeitos = models.BooleanField(default=False)  # whoosh nas trocas de cena + impacto no início (sons.py)
    volume = models.BooleanField(default=False)
    voz = models.CharField(max_length=60, blank=True, default="")  # vazio = a voz do preset do nicho  # áudio final a -14 LUFS

    def __str__(self):
        return f"{self.nicho} · {self.meta_dia}/dia · {'ativo' if self.ativo else 'parado'}"


class Pauta(models.Model):
    """Um tema esperando a vez: do catálogo, digitado por nós ou sugerido pela IA."""

    nicho = models.CharField(max_length=20)
    formato = models.CharField(max_length=30)
    formato_nome = models.CharField(max_length=80, blank=True)
    titulo = models.CharField(max_length=200)
    tema_id = models.CharField(max_length=60, blank=True)  # id do catálogo (o gospel precisa: traz a referência bíblica)
    origem = models.CharField(max_length=10, default="catalogo")  # catalogo | manual | ia
    prioridade = models.SmallIntegerField(default=1)
    usado = models.BooleanField(default=False)
    falhas = models.PositiveSmallIntegerField(default=0)
    criado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-prioridade", "criado"]
        constraints = [models.UniqueConstraint(fields=["nicho", "formato", "titulo"], name="pauta_unica")]

    def __str__(self):
        return f"{self.nicho}/{self.formato}: {self.titulo}"


class Serie(models.Model):
    """Uma história em 2 a 5 partes. Cada parte é uma Producao; a série vai para a revisão como um bloco só."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pauta = models.ForeignKey(Pauta, null=True, blank=True, on_delete=models.SET_NULL)
    nicho = models.CharField(max_length=20)
    formato = models.CharField(max_length=30)
    tema = models.CharField(max_length=200)
    max_partes = models.PositiveSmallIntegerField(default=3)
    automatica = models.BooleanField(default=False)  # pedida pelo produtor: tema curto demais cai para vídeo único
    titulo = models.CharField(max_length=200, blank=True)
    plano = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, default="fila")  # os mesmos de Producao.Status
    etapa = models.CharField(max_length=20, blank=True)
    mensagem = models.CharField(max_length=300, blank=True)
    avisos = models.JSONField(default=list, blank=True)  # juiz visual da série: personagem que mudou de cara
    log = models.TextField(blank=True)
    custos = models.JSONField(default=dict, blank=True)
    erro = models.TextField(blank=True)
    motivo = models.CharField(max_length=300, blank=True)
    criado = models.DateTimeField(auto_now_add=True)
    iniciado = models.DateTimeField(null=True, blank=True)
    terminado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado"]

    def __str__(self):
        return f"série {self.nicho} · {self.titulo or self.tema} · {self.status}"


class Producao(models.Model):
    """Um vídeo do canal, do tema até a postagem (sozinho ou uma parte de uma Serie)."""

    class Status(models.TextChoices):
        FILA = "fila", "Na fila"
        GERANDO = "gerando", "Gerando"
        REVISAR = "revisar", "Para revisar"
        APROVADO = "aprovado", "Aprovado"
        REPROVADO = "reprovado", "Reprovado"
        POSTADO = "postado", "Postado"
        FALHOU = "falhou", "Falhou"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pauta = models.ForeignKey(Pauta, null=True, blank=True, on_delete=models.SET_NULL)
    serie = models.ForeignKey(Serie, null=True, blank=True, on_delete=models.CASCADE, related_name="partes")
    parte = models.PositiveSmallIntegerField(null=True, blank=True)
    nicho = models.CharField(max_length=20)
    formato = models.CharField(max_length=30)
    tema = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FILA)
    etapa = models.CharField(max_length=20, blank=True)
    mensagem = models.CharField(max_length=300, blank=True)
    log = models.TextField(blank=True)
    titulo = models.CharField(max_length=200, blank=True)
    post = models.TextField(blank=True)
    videos = models.JSONField(default=list, blank=True)  # [{"nome", "url", "variante": "com" | "sem"}]
    custos = models.JSONField(default=dict, blank=True)
    erro = models.TextField(blank=True)
    motivo = models.CharField(max_length=300, blank=True)  # por que reprovamos (vira lição para o roteirista)
    cancelar = models.BooleanField(default=False)
    avisos = models.JSONField(default=list, blank=True)  # o que o juiz apontou e ficou sem resolver (vai para a revisão)  # pedido do painel; o produtor confere a cada 3 s e interrompe
    postado_youtube = models.DateTimeField(null=True, blank=True)
    postado_tiktok = models.DateTimeField(null=True, blank=True)
    criado = models.DateTimeField(auto_now_add=True)
    iniciado = models.DateTimeField(null=True, blank=True)
    terminado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado"]

    def __str__(self):
        return f"{self.nicho} · {self.tema} · {self.get_status_display()}"


class Produtor(models.Model):
    """Estado do processo `manage.py produtor` (linha única)."""

    pausado = models.BooleanField(default=False)
    llm = models.CharField(max_length=10, default="claude-cli")
    intervalo_min = models.PositiveSmallIntegerField(default=20)  # descanso entre um vídeo e o próximo
    batimento = models.DateTimeField(null=True, blank=True)
    falhas_zeradas_em = models.DateTimeField(null=True, blank=True)  # a trava de 3 falhas/dia conta a partir daqui

    @classmethod
    def get(cls) -> "Produtor":
        return cls.objects.get_or_create(pk=1)[0]
