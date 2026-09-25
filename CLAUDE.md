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
virar canal do Bob, configure no painel: imagens "IA no pod", estilo "doodle cena" e roteiro "narrado". O elenco vem
sozinho do preset `animacoes` (`MILIONERE_ELENCO`). O Space Atlas continua só de espaço. Gospel (do Rafael) e
animais seguem como estão.

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
- **GPU:** um pod da RunPod (RTX A4500 de 20 GB) com ComfyUI.
  - O endereço fica no `.env` em `MILIONERE_COMFY_URL`; vazio, o motor usa o ComfyUI local.
  - Modelos: Wan 2.2 I2V fp8 e Z-Image Turbo Q6 GGUF.
  - Num pod novo, rode `motor/milionere/instalar_pod.sh`. O pod **não tem Network Volume**: parar ou apagar pode
    perder os modelos.
  - O SSH deste PC ainda é recusado pelo pod; o Rafael precisa cadastrar a chave pública.
- **Roteiro:** o Claude roda pelo `claude -p`, chamado via node direto, e usa a sessão do Yonarhan. Quando a sessão
  chega ao limite, o vídeo falha com "You've hit your limit".
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
- **Música:** nada triste. No TikTok, sem música.
- **Chaves:** nunca commitar chaves de API; elas ficam em `motor/config.toml` e `.env`, os dois fora do git. Antes de
  cada commit, rodar `git grep -nE "s2EPFp1Zq|57698011-5c7|AQ\.Ab8RN|sk-ant-"`.
- **Terceiros:** não citar o repositório MoneyPrinterTurbo, só o aviso MIT em `THIRD_PARTY_NOTICES.md`.
- **Ferramentas globais:** não atualizar sem perguntar.
- **Depois de mudar código:** reiniciar o site e o produtor quando estiverem parados. O produtor carrega o código na
  memória, e o site guarda o template em cache.
- **Commits:** usar mensagens em português. Antes do push, fazer `git fetch` e `git merge origin/main`, porque o
  Rafael sobe coisas em paralelo.

## Pendências

- O Claude escolher entre 2 opções de imagem por cena. Hoje, a imagem errada é refeita à mão.
- Refinar os prompts de imagem do `doodle_cena` e, depois de ~30 imagens boas, treinar um LoRA do estilo.
- Formato longo, de ~8 min, com o mesmo estilo.
- A capa (banner) do canal Bob Curioso. As fotos de perfil estão em `videos_prontos/amostras/bob-curioso/`.
