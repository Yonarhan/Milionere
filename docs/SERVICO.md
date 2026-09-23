# Serviço Milionere: planejamento técnico (Django)

*23/09/2026. Complementa o [PRODUTO.md](PRODUTO.md) (o quê e por quê). Este documento trata do como.*

## 1. Decisões de base

| Tema | Escolha | Por quê |
|---|---|---|
| Framework | **Django 5.2 LTS** + **Django REST Framework** | O time (você e o Rafael) já é pleno em Django |
| Tarefas assíncronas | **Celery + Redis** | Gerar um vídeo leva minutos e não pode rodar dentro de uma requisição |
| Banco | **PostgreSQL + pgvector** | Dados do produto e busca por significado da biblioteca de imagens, num lugar só |
| Front (MVP) | **Templates Django + HTMX + Alpine.js** | Sem SPA separada. O protótipo vira templates rápido. PWA (manifest) para o celular |
| Login | **django-allauth** (Google e e-mail) | Pronto, testado |
| Arquivos | **django-storages (S3) → Cloudflare R2** | Barato e sem cobrança de download |
| Pagamento | **Mercado Pago** (Pix e cartão). Stripe como opção | Pix é essencial no Brasil |
| Pipeline de vídeo | Pacote **`motor/milionere`** instalado no worker | A fase 0 transforma os scripts em funções que o Celery chama |

## 2. Arquitetura

```
                ┌──────────────────────────── VPS (CPU) ────────────────────────────┐
 navegador ───▶ │  nginx ─▶ Django (gunicorn): site + API + admin                   │
  (PWA)         │              │                                                    │
                │              ├─▶ PostgreSQL + pgvector                            │
                │              ├─▶ Redis (fila Celery + cache + limites)            │
                │              └─▶ R2 (vídeos, imagens, áudios)                     │
                │  worker-cpu (Celery): roteiro (LLM), voz, legenda, montagem       │
                │  beat (Celery): cotas mensais, limpeza, biblioteca de madrugada   │
                └───────────────────────────────────────────────────────────────────┘
                                   ▲ fila "gpu" (Redis)
                                   │  conexão de SAÍDA do worker: não precisa abrir porta
                ┌──────────────────┴──── Máquina com GPU ───────────────────────────┐
                │  worker-gpu (Celery) + ComfyUI já carregado (Flux/SDXL)           │
                │  → gera as imagens das cenas e o juiz visual barato               │
                └───────────────────────────────────────────────────────────────────┘
```

- **Duas filas:** `cpu` (roteiro, voz, legenda, montagem com ffmpeg) e `gpu` (só imagens). Com isso, a máquina com GPU é **qualquer PC** (o do Rafael, ou um com uma RTX 3090 usada) que se conecta ao Redis. Depois ela pode virar uma GPU na nuvem sob demanda.
- **Gemini (plano pago) roda na fila `cpu`:** é uma chamada de API, não usa a GPU.
- **Ordem da fila por plano:** o pago vai na frente (prioridade da fila no Celery ou filas separadas `gpu-pago` e `gpu-gratis`).

## 3. Apps Django

| App | Responsabilidade | Modelos principais |
|---|---|---|
| `contas` | Usuário, plano, chave própria (criptografada) | `Perfil(plano, chave_gemini_cifrada)` |
| `catalogo` | Nichos, formatos, temas e presets **editáveis no admin**. Nicho novo = cadastro, não código | `Nicho`, `Formato(receita, faixa_palavras, cenas)`, `Tema(ref, ângulo)`, `Preset(voz, velocidade, legenda, estilo)`, `Estilo`, `Personagem(descrição_visual, retrato)` |
| `projetos` | O vídeo do usuário e as cenas | `Projeto(nicho, formato, tema, status)`, `Roteiro(versão, notas_juiz)`, `Cena(ordem, fala, prompt_imagem, modo_imagem, imagem)` |
| `biblioteca` | Imagens aprovadas com ficha e vetor | `Imagem(arquivo, descrição, personagens, estilo, nota, usos, licença, embedding VectorField, privada/compartilhada, dono)` |
| `geracao` | Jobs, etapas e o que cada juiz disse (o `producao/validacao/*.json` vira banco) | `Job(projeto, etapa, status, tempo, custo)`, `Validacao(camada, ok, detalhes JSON)` |
| `creditos` | Cotas e extrato | `Lancamento(usuário, +/-, motivo, job)`: extrato imutável. O saldo é a soma |
| `pagamentos` | Checkout e webhooks | `Pedido`, `Assinatura`, webhook do Mercado Pago |
| `publicacao` (fase 5) | YouTube e TikTok | `Conta Conectada`, `Postagem(agendada_para)` |

## 4. O fluxo de um vídeo (tarefas Celery)

```
POST /api/projetos/                       → cria Projeto (status=rascunho)
POST /api/projetos/{id}/roteiro/gerar     → task roteiro.gerar         [cpu]  LLM + camadas 1 e 2
PATCH /api/cenas/{id}                     → usuário edita a fala ou sobe a imagem (validação camada 1 ao vivo)
POST /api/projetos/{id}/gerar             → chain:
      voz.sintetizar           [cpu]  por cena → tempos exatos (sem precisar de legenda automática)
      imagens.resolver         [cpu]  manual > biblioteca > (gemini [cpu] | comfy [gpu]) por cena
      imagens.juiz             [gpu/cpu] CLIP/ArcFace primeiro, LLM só nos casos duvidosos
      video.montar             [cpu]  ffmpeg: clipes + legenda + voz (+ música) → R2
      post.pacote              [cpu]  título, descrição, hashtags, créditos
GET  /api/projetos/{id}/status            → HTMX consulta a cada 2 s (depois: SSE)
```
- **Débito de créditos:** reserva no início e confirma no fim. Se o job falhar, devolve.
- **Idempotência:** cada etapa grava o resultado. Se o job cair no meio, retoma da etapa que parou (como o `--retomar` do pipeline de hoje).

## 5. Contrato com o motor (o que a fase 0 entrega)

O Django **não chama scripts**, chama funções do pacote `motor/milionere`:

```python
from milionere import roteirista, validar, provedores, produzir
r = roteirista.escrever(formato, tema)               # dict com cenas
erros = validar.camada1(r, formato, tema)
provedores.gerar_cenas(r, estilo, pasta, so=[...])   # manual | comfy | gemini, conforme o plano
video = produzir.render(r, ...)                      # (fase 1: função pura, hoje é CLI)
```

A configuração vem de variáveis de ambiente (`MILIONERE_VOZ`, `MILIONERE_LLM`, `MILIONERE_IMAGEM`, `MILIONERE_PLANO`). O Django define essas variáveis por job, conforme o plano do usuário.

## 6. Infra: ambientes e deploy

| Ambiente | Onde | O que roda |
|---|---|---|
| Dev | PC de cada um | `docker compose up` (web, worker, redis, postgres). O worker-gpu é o PC do Rafael |
| Staging/MVP | 1 VPS pequena (Hetzner, DigitalOcean, ou Oracle Always Free) | web, worker-cpu, beat, redis, postgres. R2 para arquivos |
| GPU | PC com RTX 3090/4090 **ou** RunPod/Modal | worker-gpu + ComfyUI em Docker (`motor/Dockerfile.gpu` como base) |
| Produção | A mesma VPS maior + backups do Postgres | Mais workers-cpu conforme a fila |

**Docker Compose (esqueleto):**
```yaml
services:
  web:        build: ./servico   command: gunicorn config.wsgi -w 3
  worker-cpu: build: ./servico   command: celery -A config worker -Q cpu -c 2
  beat:       build: ./servico   command: celery -A config beat
  redis:      image: redis:7
  db:         image: pgvector/pgvector:pg16
# máquina de GPU (compose separado):
  worker-gpu: build: ./motor -f Dockerfile.gpu   command: celery -A config worker -Q gpu -c 1
```

**Observabilidade:** Sentry (erros), Flower (fila do Celery), e o modelo `Job` registra tempo e custo por etapa. É o painel da métrica "custo por vídeo".

**Segurança:** segredos só em variáveis de ambiente, nunca no Git. Chave própria do usuário cifrada (Fernet). Limite de requisições (django-ratelimit) e antiabuso no plano grátis (1 conta por e-mail verificado ou Google). LGPD: termos, privacidade e exclusão de conta.

## 7. Estrutura do repositório

```
milionere/
├── motor/                 ← pipeline + voz/legenda/interface (pacote milionere/ e app/ do motor)
│   └── milionere/         ← fase 0: roteirista, validar, provedores, sincronizar, renderizar…
│       └── dados/         ← presets, formatos, estilos, bíblia, referências (vão para o banco na fase 3)
├── servico/               ← projeto Django (config/, contas/, catalogo/, projetos/, biblioteca/, geracao/…)
├── docs/                  ← PRODUTO.md, SERVICO.md, protótipo
├── producao/              ← roteiros e validações dos nossos canais
└── .claude/skills/        ← só as instruções para o Claude
```

## 8. Marcos do serviço

| Marco | Entrega | Quem |
|---|---|---|
| **S0** | Fase 0 do motor: pacote, caminhos por `.env`, camadas trocáveis | Claude + revisão do Rafael |
| **S1** | Esqueleto Django: compose, allauth, apps vazias, admin do catálogo (importa os JSONs atuais) | Você |
| **S2** | Projetos e Cenas + tela do protótipo em HTMX (sem gerar ainda) | Você |
| **S3** | Celery: tarefas de roteiro, voz e montagem na fila `cpu`. O primeiro vídeo gerado pelo site | Você + Claude |
| **S4** | Fila `gpu` com o ComfyUI e o juiz. Worker no PC do Rafael | Rafael |
| **S5** | Biblioteca (pgvector) + modo manual (upload e prompt pronto) | Rafael + Claude |
| **S6** | Créditos, limites do grátis, Mercado Pago, Gemini no plano pago | Você |
| **S7** | Deploy na VPS + R2 + Sentry. Beta fechado com 10 a 20 pessoas | Todos |

## 9. Pendências de decisão

- Hospedagem da VPS (custo e região) e se começa com a GPU própria ou na nuvem.
- LLM do plano grátis (API paga barata, Gemini texto, Workers AI). O `claude -p` é só para desenvolvimento.
- Troca do Edge TTS pelo Azure oficial antes da cobrança (já decidido: ver PRODUTO.md, seção 9).


## 10. Sistema de guia da IA (implementado 23/09/2026)

| Peça | Arquivo | O que faz |
|---|---|---|
| Medidor | `motor/milionere/medidor.py` | Toda chamada de IA e imagem anota tokens, modelo, US$/R$ e tempo por etapa. Vai para `Job.custos` e aparece no admin e na tela |
| Banco de roteiros | `motor/milionere/banco_roteiros.py` | Roteiros aprovados (exemplos) + erros que o juiz apontou, por nicho; busca por significado; desempenho real (views/retenção) pesa nos exemplos |
| Guia | `motor/milionere/guia.py` | Bloco que entra em todo prompt de roteiro: 3 exemplos aprovados parecidos + erros mais comuns do nicho + aprendizados. `checar()` = camada 1 por código (grátis) |
| Roteirista guiado | `servico_pipeline._roteiro_generico` | escreve (guiado) → código → juiz (só se o código aprovou) → reescreve só o apontado (máx. 3) → aprovado vira exemplo, reprovação vira lição |
| Papéis e modelos | `caminhos.py` | `MILIONERE_MODELO_ROTEIRO` (padrão sonnet) e `MILIONERE_MODELO_JUIZ` (padrão haiku); `MILIONERE_JUIZ_ROTEIRO=0` desliga o juiz |

**Medição real (buraco negro, aprovado na 1ª):** R$ 1,51 em valor de API, 193 s. O roteirista consumiu 35,7 mil tokens de
entrada e 10,3 mil de saída porque o `claude -p` embute ~9 mil tokens de instruções do Claude Code por chamada e usa pensamento
estendido. **Chamando a API direto** (fase 1: camada `MILIONERE_LLM=api`), o mesmo roteiro ficaria em torno de 7 mil tokens de
entrada e 1,5 mil de saída: estimativa de ~R$ 0,20 (Sonnet 5 escrevendo + Haiku julgando), fora a economia do cache de prompt.
