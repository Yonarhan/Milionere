# Produto: gerador de Shorts de ponta a ponta

*Resumo das discussões de produto de 23/09/2026. Serve de base para decidir e dividir o trabalho.*
Protótipo de interface: [prototipo-interface.html](prototipo-interface.html) (abra no navegador).

---

## 1. A visão

Um **site** (que também funciona no celular) onde qualquer pessoa cria um Short pronto para postar, de ponta a ponta:
**nicho → tema → roteiro → imagens → voz e legenda → vídeo + texto do post**.

- **O plano grátis entrega o fluxo completo**, com qualidade de postagem. Nada de versão capada.
- **O plano pago acelera e melhora**, principalmente as imagens (API do Google/Gemini), e traz extras.
- É **tão simples quanto o motor**: o caminho mínimo são 3 cliques (nicho → tema → Gerar). Tudo vem pré-configurado pelo nicho, e o avançado fica escondido.

## 2. A interface (ver o protótipo)

| Passo | O que a pessoa faz |
|---|---|
| 1. Nicho | Gospel, Astronomia, Animais… (Tecnologia, História, Mitologia, Psicologia depois) |
| 2. Formato e tema | Ex.: Gospel → Histórias de Jesus, Personagem em 30s, Provérbio, Parábola moderna, Sermão curto. Tema do catálogo, 🎲 sorteado ou escrito por ela |
| 3. Roteiro | Gerado por IA **ou** escrito por ela. Cada frase é editável. Validação ao vivo: duração, gancho, chamada final, cara de IA, versículo |
| 4. Imagens | Por cena: automática, **copiar prompt** (para gerar no Gemini ou no Bing) ou **subir a própria imagem** |
| 5. Voz, legenda, música | Já preenchidos pelo nicho. Música: "sem" (para usar o áudio do TikTok) ou da biblioteca |
| 6. Gerar | Prévia, download com e sem música, título, descrição e hashtags para copiar |

**Nicho novo = configuração, não código.** Cada nicho é um pacote (formatos, catálogo de temas, preset de voz e legenda, estilo e fontes de imagem, regras de validação), como já acontece com `formatos.json`, `biblia/temas.json`, `presets.json` e `estilos.json`.

## 3. Planos

| | Grátis | Pago | Chave própria |
|---|---|---|---|
| Roteiro validado, edição, voz, legenda, sincronização, pacote de postagem | ✅ | ✅ | ✅ |
| Imagens | Biblioteca + IA aberta (Flux/SDXL) + banco + upload | Biblioteca + **Gemini** com personagem de referência | Gemini com a chave do próprio usuário |
| Velocidade | Fila normal (minutos) | Prioridade, imagens em paralelo (~1 min) | Como o pago |
| Quantidade | X vídeos por mês | Muito mais, com lotes | Limite do plano |
| Extras | — | Animação das cenas, vozes premium, postagem e agendamento | — |

- **A mesma régua de qualidade** (as 4 camadas de validação) vale para todos os planos.
- **Chave própria** não custa nada para nós. As chaves ficam criptografadas ou só no navegador do usuário (LGPD).
- **Cobrança:** créditos e/ou assinatura, com Pix e cartão (Mercado Pago/Stripe). Preço de 3 a 5 vezes o custo por vídeo. Começar como **site/PWA**, porque as lojas de apps ficam com 15 a 30% das vendas digitais.
- **Burocracia:** CNPJ (MEI pode servir no início, confirmar com contador), nota fiscal, termos de uso, privacidade (LGPD) e regras contra golpe e deepfake.

## 4. As 4 formas de obter imagens (misturáveis por cena)

| Modo | Como | Custo para nós | Qualidade |
|---|---|---|---|
| **Manual** ⭐ | O site dá o prompt pronto por cena, o usuário gera no Gemini ou no Bing (ou usa fotos dele) e sobe | Zero | A melhor até agora (Lázaro, Pedro) |
| **Aberto** | ComfyUI do Rafael (SDXL + IP-Adapter / Flux) no nosso GPU + banco com curadoria | GPU | Boa, fraca em ação |
| **Premium** | Gemini pela API, com imagem de referência do personagem. Se falhar, cai para o aberto | API | Muito boa e rápida |
| **Chave própria** | O Gemini do usuário | Zero | Como o premium |

## 5. Biblioteca de imagens (a principal otimização)

O gargalo é a geração de imagens. No "Pedro sobre as águas", foram **~2h30** em ciclos de "gerar → juiz reprova → gerar de novo".

**Tudo que é aprovado entra na biblioteca**, com uma ficha: descrição da cena, personagens, estilo, nicho, enquadramento, emoção, nota do juiz, uso e licença. A busca é por significado (vetores: sqlite-vec no desenvolvimento, pgvector no servidor).

Para cada cena:
```
busca as imagens mais parecidas (mesmo personagem e estilo)
  ├─ quase idêntica  → reusa com recorte, zoom e cor diferentes     (0 s de GPU)
  ├─ parecida        → gera A PARTIR dela (img2img / ControlNet)   (rápido, composição certa)
  └─ nada parecido   → gera do zero com o prompt que "já passou"   (como hoje)
juiz barato → aprova → entra na biblioteca
```

**Como a biblioteca ajuda a gerar:**
- **img2img:** redesenha a partir de uma imagem parecida. Menos passos e composição certa.
- **ControlNet (pose e profundidade):** copia a estrutura de uma cena parecida. Resolve as cenas de ação.
- **IP-Adapter:** rosto (já usado) e também estilo e luz a partir da biblioteca.
- **LoRA do canal:** com 20 a 30 imagens aprovadas do mesmo personagem, treina-se uma vez (~30 a 60 min numa GPU de 24 GB). Consistência sem referência em cada cena.
- **Prompts e seeds que passaram no juiz** viram exemplos para cenas parecidas. Não custa GPU.
- **Gemini com 2 a 3 referências** tiradas da biblioteca (plano pago).

**Encher antes do lançamento:** gerar de madrugada as 300 a 500 cenas mais comuns de cada nicho e estilo (os personagens fixos em várias situações, os lugares bíblicos, os planetas…). Na astronomia, a NASA já dá uma base grátis.

**Riscos e cuidados:**
- **Não repetir a mesma imagem no mesmo canal** por X dias, e variar recorte, zoom e cor.
- A **biblioteca compartilhada** fica só com cenas genéricas (paisagens, objetos, lugares). Personagens em cenas-chave vêm de geração nova ou da biblioteca **privada** do usuário.
- **Uploads de usuários** são privados por padrão. Só entram na biblioteca compartilhada com autorização expressa.

**Métrica principal:** % de cenas atendidas pela biblioteca ou geradas a partir dela, com nota do juiz ≥ 4.

## 6. Otimizar o pipeline para o servidor

Meta: **menos de 5 min por vídeo** (hoje, ~2h30 no pior caso).

| Otimização | Ganho esperado |
|---|---|
| Modelos rápidos (Flux schnell / SDXL Lightning, 4 a 8 passos em vez de 30) | 4 a 8 vezes mais rápido por imagem |
| Gerar 2 a 4 versões por cena de uma vez e escolher a melhor | Acaba com os ciclos de reprovação |
| Direcionar cada cena para a fonte certa (close → IA + IP-Adapter; ação → Gemini/ControlNet/banco) | Menos reprovações |
| Juiz barato primeiro (CLIP para cena e texto, ArcFace para o rosto). O juiz LLM só nos casos duvidosos | 70 a 90% menos chamadas pagas |
| Tamanho do roteiro garantido por código (evita a oscilação do Jonas: 86 → 109 palavras) | Menos reescritas |
| Manter os modelos carregados (sem ligar e desligar o ComfyUI a cada vídeo) | Minutos por vídeo |
| Cache e biblioteca | O custo cai com o uso |

**Camadas trocáveis** (o que permite grátis e pago no mesmo código):
```
LLM:     claude-cli (dev) | claude-api | gemini | workers-ai
Imagem:  manual | biblioteca | comfy-local | comfy-remoto | gemini | chave-propria
Voz:     edge (só dev) | piper | kokoro
```

**Peças que não podem ir para o produto:**
- `claude -p` com a assinatura: é uso pessoal. No produto, usar API.
- **Edge TTS:** acesso não oficial. Trocar por Piper ou Kokoro.
- **NVI:** tem direitos autorais. Usar a Bíblia Portuguesa Mundial (domínio público), como o Rafael já fez.
- **yt-dlp** para caçar ideias: só para uso interno.

**Teste de qualidade fixo:** 10 temas de referência (Lázaro, Pedro, Jonas, planeta de vidro…). Toda mudança roda os 10 e compara aprovação na 1ª tentativa, notas do juiz, aprovação de imagens, tempo e custo. Otimização que piora a nota não entra.

## 7. Infraestrutura e GPU

```
Site/PWA (Cloudflare Pages)
   ↓
API + fila (FastAPI)               ← login, créditos, limites por plano
   ↓
Workers de GPU (ComfyUI em Docker, modelos carregados)
   ↓
Arquivos (Cloudflare R2)
```

**VRAM por peça (estimativas):** SDXL ~8 GB (10 a 12 com IP-Adapter) · Flux schnell ~8 GB (Q4) a 16 GB · juiz CLIP/ArcFace 1 a 2 GB · animação Wan 2.2 5B 16 a 24 GB (só pago) · voz e ffmpeg rodam na CPU.

| GPU | Serve para |
|---|---|
| 6 GB (GTX 1060) | Só desenvolvimento |
| 12 GB | Funciona com versões comprimidas, com troca de modelos |
| **16 GB (mínimo)** | Imagens sem aperto, sem animação |
| **24 GB (ideal): RTX 3090 usada, 4090, L4/A10G** | Tudo carregado, inclusive animação |

**Capacidade estimada:** ~1 min de GPU por vídeo (12 cenas × 2 versões, modelos rápidos, 4090). Uma GPU de 24 GB faz de **500 a 1.000 vídeos por dia**. 1.000 usuários grátis × 10 vídeos por mês ≈ 330 por dia, o que **uma placa aguenta**. *Medir com o teste de qualidade.*

**Onde rodar:**
1. **Agora:** no PC do Rafael.
2. **Lançamento:** PC próprio com uma **RTX 3090 usada (24 GB)** como trabalhador que busca tarefas numa fila na nuvem.
3. **Crescimento:** GPU **sob demanda** (RunPod Serverless, Modal), paga por segundo.
4. **Escala:** várias GPUs sob demanda, ou máquinas alugadas 24 horas.

## 8. Roadmap

| Fase | Entrega |
|---|---|
| 0. Base | ✅ Repositório, `.gitattributes`, pipeline do Rafael. ⬜ Caminhos configuráveis e camadas trocáveis (LLM, imagem, voz) |
| 1. Qualidade e velocidade | Teste com 10 temas, biblioteca v1, modelos rápidos, versões múltiplas, juiz barato, Gemini de volta como premium e socorro. Meta: menos de 5 min por vídeo |
| 2. Servidor | Docker com ComfyUI, fila, GPU sob demanda, R2 |
| 3. Site (MVP) | O fluxo do protótipo funcionando de verdade |
| 4. Planos | Login, créditos, Pix e cartão, limites |
| 5. Extras | Postagem e agendamento no YouTube e no TikTok, novos nichos, animação |

## 9. Decisões em aberto

- Nome e marca do produto (hoje, "Milionere Estúdio" no protótipo).
- Limite do plano grátis (vídeos por mês) e preço do pago. Depende do custo real medido na fase 1.
- Qual LLM grátis escreve o roteiro no plano grátis (Gemini texto, Workers AI…) sem perder qualidade.
- Comprar a GPU de 24 GB agora ou começar direto sob demanda.
- Quem cuida de quê: pipeline e imagens, site, pagamentos, conteúdo e nichos.
