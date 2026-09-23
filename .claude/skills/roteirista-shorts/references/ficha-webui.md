# Ficha para a WebUI (formato OBRIGATÓRIO de entrega)

O usuário preenche o vídeo na tela do MoneyPrinterTurbo (http://127.0.0.1:8501). Todo roteiro
aprovado é entregue nesta ficha, **na mesma ordem das 4 colunas da tela**, com os rótulos exatos
da interface em português. Valores vêm do preset do nicho em `presets.json` + `ajustes` do roteiro.

Tradução preset → rótulo da tela:
- video_transition_mode: None=Nenhuma Transição, FadeIn=Aparecer gradualmente, Shuffle=Transição Aleatória, ZoomIn=Aproximar
- subtitle_position: center=Centralizar, bottom=Inferior
- subtitle_display_mode: sentence=Frase completa, word_by_word=Palavra por palavra
- subtitle_animation: none=None, pop_spring=Entrada com efeito elástico
- bgm: Música de Fundo Personalizada (arquivo `<prefixo>N.mp3`) ou Sem Música de Fundo. NUNCA Aleatória.
- voice: pt-BR-AntonioNeural-Male = pt-BR-Antonio-Masculino; pt-BR-FranciscaNeural-Female = pt-BR-Francisca-Feminino

Roteiro, palavras-chave e tema vão em bloco de código (fácil de copiar). O resto em tabela.

## Modelo

### 📝 Configurações do roteiro
**Tema do vídeo**
```
<tema>
```
**Idioma do roteiro:** pt-BR
**Roteiro do vídeo** — cole e NÃO clique em "Gerar ... com IA"
```
<roteiro>
```
**Palavras-chave do vídeo**
```
<kw1>, <kw2>, ...
```

### 🎞️ Configurações do Vídeo
| Campo | Valor |
|---|---|
| Fonte do Vídeo | Pexels |
| Ajustar imagens à ordem do roteiro | ✅ marcado (a concatenação vira Sequencial sozinha) |
| Modo de Transição de Vídeo | ... |
| Proporção do Vídeo | Retrato 9:16 |
| Ajuste do enquadramento | Preencher (recorte central) |
| Duração máxima por clipe (s) | ... |
| Velocidade do clipe | 1.00x |
| Vídeos por execução | 1 |
| Codificador de vídeo | Padrão (recomendado) |

### 🔊 Configurações de Áudio
| Campo | Valor |
|---|---|
| Modo de narração | Automática |
| Serviço de voz | Azure TTS V1 (Edge TTS) |
| Voz | ... |
| Volume da narração | 100% |
| Velocidade da narração | ... |
| Fonte da música de fundo | ... |
| Volume da música de fundo | ... |

Conferir: a "Duração estimada" que aparece abaixo da velocidade tem que bater com a faixa do nicho.

### 💬 Configurações de Legendas
| Campo | Valor |
|---|---|
| Ativar Legendas | ✅ |
| Fonte | ... |
| Posição | ... |
| Exibição das legendas | ... |
| Animação de entrada | ... |
| Texto (cor) | ... |
| Tamanho da fonte | ... |
| Contorno (cor) | Preto |
| Espessura | ... |
| Fundo | ☐ desmarcado |

### 📤 Postagem
Título, descrição (com hashtags), comentário fixado, lembrete de conteúdo sintético.
