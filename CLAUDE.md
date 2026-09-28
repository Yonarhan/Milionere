# Milionere: contexto para um chat novo

Ferramenta interna do Yonarhan e do Rafael (developerRcs) para produzir **Shorts e TikToks sem rosto**, para renda
extra. Repositório: github.com/Yonarhan/Milionere (branch `main`). A conversa com o Yonarhan é em português.

## Foco atual: canal "Bob Curioso" (animações doodle de qualquer tema)

Decidido em 25/09/2026. Shorts de 45 a 60 s em desenho doodle, sempre com o mesmo elenco:
- **Bob:** protagonista, cabeça redonda branca;
- **o Amigo:** coadjuvante que reage, cabeça redonda azul;
- **cenário:** parede branca e chão bege.

A fórmula completa está em **`docs/animacoes.md`**; leia antes de mexer. Em resumo:
- **Roteiro "narrado":** a narração vem corrida primeiro (110 a 150 palavras, com conectores, perguntas e uma quebra
  de expectativa). Depois ela é dividida em 10 a 18 cenas, trocando de imagem a cada 2 a 4 s, mesmo no meio da frase.
- **Cada imagem encena a fala:** emoção e pose, a ideia virando objeto, uma piada de 1 a 3 palavras, o coadjuvante
  reagindo.
- **O roteirista está aprovado** pelo Yonarhan: não refatorar sem ele pedir.
- **Pilotos aprovados** (em `producao/roteiros/`): `2026-09-25_propria-voz.json` e
  `2026-09-25_ultimo-minuto-da-vida-v2.json`.

**Um canal do Bob por nicho** (decidido em 25/09/2026): o Bob Curioso fica com as curiosidades gerais e o Space
Atlas vira animação do Bob com curiosidades de astronomia. Os próximos nichos seguem o mesmo modelo. Para um nicho
virar canal do Bob, configure no painel: imagens "animação em código" e roteiro "viral" (ou, no modo antigo, "IA no
pod" + estilo "doodle cena" + roteiro "narrado"). O elenco vem sozinho do preset `animacoes` (`MILIONERE_ELENCO`).
O Space Atlas continua só de espaço. Gospel (do Rafael) e animais seguem como estão. Plano (28/09/2026): canal PT e
um canal em inglês (mesmas cenas, fala traduzida); depois, talvez um app de "prompt -> animação".

## Animação em código: o padrão desde 28/09/2026 (sem GPU, sem pod)

As cenas do Bob são **desenhadas e animadas em Python** (cairo) no processador deste PC; a montagem é a de sempre.
Um Short sai em ~8 min (dá para chegar a ~3 min, ver pendências) por ~US$ 0,16 a 0,29 de Claude.

Ciclo de um vídeo (`producao._codigo` no painel, ou os scripts de teste):
1. **Roteiro** (`servico_pipeline._roteiro_generico`, modo `MILIONERE_ROTEIRO=viral`): o narrado + regras de
   retenção (`BLOCO_VIRAL`): gancho que contraria uma crença REAL, mistério até o fim, mini-gancho no meio,
   implicação no cotidiano, situação concreta (lugar + momento), final em ciclo, 6 tipos de gancho. Juiz com critérios
   de viralidade. O roteirista aprovado não mudou: o viral é um bloco a mais, só com a opção ligada.
2. **Etiquetas** (`cenas_etiqueta.py`): o Claude (Sonnet) escreve por cena só uma etiqueta curta (molde, pose,
   figurino, objeto, texto, lugar, efeito). O código monta tudo pelos **moldes** (solo, dupla, close, objeto, pensa,
   segura, gigante, divide, lista), varia entradas/câmera/transições, não repete molde seguido e deixa texto em no
   máximo ~1/3 das cenas. **Objeto novo** é desenhado UMA vez pelo Opus (`MILIONERE_MODELO_CENAS`) e salvo em
   `dados/objetos_doodle.json`; SVG de ilustrador também serve (`dados/svg/`, campo `"svg"` na biblioteca).
3. **Desenho** (`animacao_codigo.py`): traço "limpo" (padrão; "doodle" e "rough" são opção), 22 cenários
   (`cenario()`: quarto, sala, cozinha, escritório, ônibus, supermercado, academia, hospital, espaço, corpo...),
   figurinos, objetos prontos, transições (soco, desliza, íris), esticar e amassar. O **Bob "vivo"**
   (`bob_vivo.py`, padrão; `MILIONERE_CORPO=palito` volta ao antigo): linha de ação (espinha curva), camisa com
   sombra, traço fino, cabeça pequena, mãos pretas, e reação de pose (começa neutro e vira a emoção na cena).
   Checagem por código (`cenas_codigo.consertar`): nada fora da tela, texto não cobre cabeça nem objeto.
4. **Voz e montagem** (`produzir.py`): OmniVoice `bob-agudo` (com limpeza de ruído), legenda karaokê pequena no chão
   (`AJUSTES_LEGENDA`), cenas de `producao/midia/<slug>/cena_NN.mp4` e **capa** automática
   (`thumbnail.py`, `<data>_<slug>_thumb.jpg`).

Arquivos de trabalho: `producao/cenas_codigo/<slug>.json` (etiquetas + cenas). O diretor livre com o Opus
(`cenas_codigo.dirigir`, com revisão visual) segue disponível para comparar. Pautas inspiradas em formatos virais
gringos (tema e formato, roteiro sempre nosso): `dados/pautas_inspiradas.json`.

## Como funciona

- **Painel:** Django em `servico/` (app `estudio`).
  - `http://127.0.0.1:8000/canal` é o Estúdio de Animações, só com o canal `animacoes`.
  - `/canal?todos=1` mostra todos os canais.
  - O produtor (`manage.py produtor`) gera um vídeo por vez. É ligado por `producao.ligar_produtor()` e grava o log em
    `servico/media/produtor.log`.
- **Motor:** `motor/milionere/`.
  - Roteiro e juiz: `servico_pipeline.py`, `nativo.py` e `guia.py`.
  - Imagens: `imagens.py`. Animação: `animar.py` (Wan 2.2).
  - Montagem: `produzir.py` e `sincronizar.py`.
  - Presets e estilos: `dados/presets.json` e `dados/estilos.json` (estilo `doodle_cena`; o elenco fica no preset
    `animacoes`).
- **GPU:** um pod da RunPod (RTX A4500 de 20 GB) com ComfyUI. **A animação em código não usa o pod**; ele só serve
  ao gospel e aos canais em "IA no pod" (deixar desligado no resto do tempo).
  - O endereço fica no `.env` em `MILIONERE_COMFY_URL`; vazio, o motor usa o ComfyUI local.
  - Modelos: Wan 2.2 I2V fp8 e Z-Image Turbo Q6 GGUF.
  - Num pod novo, rode `motor/milionere/instalar_pod.sh`. O pod **não tem Network Volume**: parar ou apagar pode
    perder os modelos.
  - O SSH deste PC ainda é recusado pelo pod; o Rafael precisa cadastrar a chave pública.
- **Voz:** Edge TTS por padrão. No canal `animacoes`, a voz é do OmniVoice (motor do VoiceStudio), na GPU deste PC:
  desde 27/09/2026 o Yonarhan usa a **Bob · jovem agudo** (a **Bob · jovem** segue como opção). Os .wav de referência
  ficam fora do git (`*.wav`): copiar à mão para outra máquina.
  - As referências clonadas ficam em `motor/milionere/dados/vozes/` (`vozes.json` e os .wav escolhidos no elenco).
  - `voz_omnivoice.py` roda no Python do OmniVoice (`MILIONERE_OMNIVOICE_PYTHON`, padrão
    `~/omnivoice-teste/.venv`). Ele gera a narração e alinha cada palavra (MMS do torchaudio) para a legenda karaokê.
  - Leva ~1,8 s por segundo de fala na GTX 1060. O Edge continua disponível no painel.
- **Roteiro:** o Claude roda pelo `claude -p` e usa a sessão do Yonarhan. Desde a versão 2.1.2xx do Claude Code o
  `llm.py` chama o `claude.exe` nativo direto (sem cmd.exe). Quando a sessão chega ao limite, o vídeo falha com
  "You've hit your limit". O custo de cada chamada fica no cartão (`medidor.py`).
- **Tempos medidos:** ~28 s por imagem e 1 a 5 min por cena animada. Um Short de 15 imagens com 3 animadas leva ~15 min.

## Objetivo permanente: refinar a geração de vídeo

Sempre que houver trabalho no canal de animações, um dos objetivos é **melhorar a qualidade do vídeo gerado**:
- a qualidade dos **objetos e ícones** que saem do roteiro (a ideia da fala virando coisa);
- a **ambientação** (cenário, lugar, clima da cena);
- a **expressão e a pose** dos personagens, e a consistência do elenco;
- o **texto na imagem**, as **animações** e a **montagem**.

Na prática:
- ao olhar um vídeo ou uma imagem, apontar o que ficou fraco e transformar isso em regra no prompt, na checagem ou
  no juiz;
- propor melhorias mesmo quando o pedido for outro;
- comparar sempre com os vídeos aprovados (a voz e a morte).

## Regras (combinadas com o Yonarhan)

- **Recurso novo entra como opção**, ao lado do que já funciona. Não remover nem trocar o comportamento atual sem
  pedido.
- **Não gerar vídeo de teste por conta própria.** Validar por código; ele gera um vídeo completo para conferir.
  Exceção: quando ele pede explicitamente.
- **Fatos com flexibilidade:** sem ficha de fatos nem fonte obrigatória. O juiz só barra erro grosseiro; a dúvida
  vira aviso no cartão de revisão.
- **O juiz não pode segurar o vídeo:** há teto de tempo e, no fim, segue a melhor versão com avisos.
- **Música:** nada triste. No TikTok, sem música. Recusadas: Investigations, Sneaky Snitch e Monkeys Spinning
  Monkeys (em `motor/storage/bgm/recusadas/`). Trilha nova só depois de ele ouvir e aprovar.
- **Visual:** limpo, arredondado e sofisticado (nada de linha tremida ou dupla), pouco texto na tela, expressões
  ricas, sempre ilustrar o que está sendo falado; o Bob veste o papel citado (figurino).
- **Temas:** o gancho parte de uma crença ou experiência real do público (o bocejo foi reprovado por isso).
- **Chaves:** nunca commitar chaves de API; elas ficam em `motor/config.toml` e `.env`, os dois fora do git. Antes de
  cada commit, rodar `git grep -nE "s2EPFp1Zq|57698011-5c7|AQ\.Ab8RN|sk-ant-"`.
- **Terceiros:** não citar o repositório MoneyPrinterTurbo, só o aviso MIT em `THIRD_PARTY_NOTICES.md`.
- **Ferramentas globais:** não atualizar sem perguntar.
- **Depois de mudar código:** reiniciar o site e o produtor quando estiverem parados. O produtor carrega o código na
  memória, e o site guarda o template em cache.
- **Commits:** usar mensagens em português. Antes do push, fazer `git fetch` e `git merge origin/main`, porque o
  Rafael sobe coisas em paralelo.

## Pendências

- Acelerar a animação em código: voz antes das cenas (renderizar só o tempo da fala), render em paralelo e voz junto
  com o desenho (~8 min -> ~3 min por vídeo).
- Bob vivo: Amigo e figurinos no corpo novo; mais poses de ação.
- Versão em inglês automática e versão do TikTok com mais de 60 s; postagem nos dois canais (`postar.py`).
- Escolher as músicas de curiosidade (Pixabay / Biblioteca do YouTube).
- O Claude escolher entre 2 opções de imagem por cena (modo "IA no pod"). Hoje, a imagem errada é refeita à mão.
- Refinar os prompts de imagem do `doodle_cena` e, depois de ~30 imagens boas, treinar um LoRA do estilo.
- Formato longo, de ~8 min, com o mesmo estilo.
- A capa (banner) do canal Bob Curioso. As fotos de perfil estão em `videos_prontos/amostras/bob-curioso/`.
