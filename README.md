# Auto Edit + HyperFrames

**Edição de vídeo automatizada com IA + gráficos animados renderizados na sua máquina.**

Este repositório junta dois projetos em uma versão só:

- **[auto-edit-video](https://github.com/gabuldev/auto-edit-video)**: pipeline que pega um vídeo bruto, transcreve, decide os cortes com IA (Claude), corta com FFmpeg, adiciona legendas/overlays e gera título, descrição e hashtags. Tudo pela linha de comando.
- **[HyperFrames](https://github.com/heygen-com/hyperframes)** (HeyGen): framework que transforma HTML + CSS + animações em vídeo, renderizando quadro a quadro num Chrome headless.

O resultado: **lower thirds, CTAs, cards de destaque e legendas animadas** feitos com HTML de verdade, com o texto tirado do próprio vídeo, em vez de MP4s fixos com tela verde.

## Por que juntar os dois

O trabalho pesado vai para **o seu computador**, não para a IA:

| Quem faz | O quê |
|---|---|
| **IA (Claude)** | Só decide *o que* mostrar e *quando*. Devolve um JSON pequeno, ex.: `{"template": "cta", "vars": {"text": "Se inscreve no canal"}, "original_start": 245.8}` |
| **Sua máquina** | Transcrição (Whisper), cortes (FFmpeg), render das animações (Chrome headless + FFmpeg), composição final |

Os templates HTML são escritos **uma vez** e reaproveitados em todo vídeo. Por isso o custo em tokens fica praticamente igual ao do auto-edit original, enquanto o visual melhora bastante:

- **Texto real do vídeo** no gráfico (nome, dica, termo explicado), não um MP4 genérico
- **Canal alpha de verdade** (ProRes 4444): sem chroma key, sem borda verde, sem serrilhado
- **Resolução exata** do vídeo editado (inclusive depois de um upscale via `video_filter`)
- **Cache**: o mesmo overlay com o mesmo texto não é renderizado duas vezes

## Como funciona

O pipeline é uma state machine orquestrada por agentes LLM e ferramentas locais:

```
extract → plan → review → execute → overlay → caption → evaluate → metadata → done
  │         │       │        │         │          │          │          │
Whisper   Claude  Claude   FFmpeg   Claude +    FFmpeg/    Claude     Claude
+ Claude                           HyperFrames  HyperFrames
```

| Stage | O que faz | Onde roda |
|-------|-----------|-----------|
| **extract** | Transcreve o áudio (Whisper) + mapa de energia + correção da transcrição | Máquina + Claude |
| **plan** | Planeja os cortes (silêncios, falsos começos, vícios de linguagem) | Claude |
| **review** | Revisa o plano de cortes | Claude |
| **execute** | Aplica os cortes e normaliza o áudio | Máquina (FFmpeg) |
| **overlay** | Claude escolhe overlays e escreve os textos; os templates HyperFrames são renderizados e compostos (só long) | Claude + **Máquina (HyperFrames)** |
| **caption** | Legendas estilo CapCut com destaque palavra a palavra (só shorts), via ASS ou **HyperFrames** | Máquina |
| **evaluate** | Avalia o resultado; se rejeitar, volta ao `plan` (até 3 vezes) | Claude |
| **metadata** | Título, descrição e hashtags | Claude |

### Onde o HyperFrames entra

```
overlay_plan.json (Claude)                      hyperframes/overlays/<template>/index.html
  {"template": "lower_third",                              │
   "vars": {"title": "...", ...},   ──► data.js ──► npx hyperframes render --format mov
   "original_start": 12.4}                                 │
                                                    hf_cache/<template>-<hash>.mov  (alpha)
                                                           │
edited_video.mp4 ──────────────────────► FFmpeg overlay (no tempo certo) ──► overlaid_video.mp4
```

1. O agente de overlay devolve, para cada momento, um `template` + textos curtos em `vars`.
2. `auto_edit/hyperframes.py` copia o template, grava os dados em `data.js`, ajusta tamanho e duração da composição para os do vídeo e roda `npx hyperframes@<versão do vendor> render --format mov`.
3. O `.mov` sai com transparência e é sobreposto pelo FFmpeg exatamente no instante planejado (o tempo é remapeado do vídeo original para o vídeo já cortado).

Nas legendas o fluxo é o mesmo, só que o template `hyperframes/captions/` recebe a lista de palavras com seus tempos e gera uma camada do tamanho do vídeo inteiro.

## O que tem neste repositório

```
auto-edit-hyperframes/
├── auto_edit/                 # Core do auto-edit (CLI, pipeline, runner, workspaces)
│   └── hyperframes.py         # Ponte com o HyperFrames: copia template, injeta dados, renderiza, cacheia
├── agents/                    # Prompts dos agentes (overlayer.md conhece os templates)
├── tools/                     # Stages em Python (extract, executor, overlayer, captioner…)
├── hyperframes/               # Templates HTML usados pelo pipeline
│   ├── overlays/
│   │   ├── lower_third/       # Nome + subtítulo entrando pela esquerda
│   │   ├── cta/               # Botão "Se inscreve" com sininho
│   │   ├── highlight/         # Card com dica/termo no canto
│   │   ├── steps/             # Lista de passos que vai se montando
│   │   ├── stat/              # Número/estatística que conta até o valor
│   │   ├── compare/           # Antes × depois, mito × fato
│   │   ├── code/              # Janela de terminal/código digitando
│   │   └── chart/             # Gráfico de barras animado
│   └── captions/              # Legendas animadas palavra a palavra
├── vendor/
│   └── hyperframes/           # Código-fonte completo do HyperFrames (snapshot, Apache 2.0)
├── tests/                     # pytest
└── ralph.sh                   # Loop que orquestra os stages
```

O código do HyperFrames fica em [`vendor/hyperframes/`](vendor/) para referência, estudo e para **fixar a versão**: o auto-edit lê a versão em `vendor/hyperframes/packages/cli/package.json` e sempre executa `npx hyperframes@<essa versão>`. Assim o que roda é exatamente o código que está no repositório. Veja [`vendor/README.md`](vendor/README.md) para atualizar.

## Requisitos

| Dependência | Para quê | Obrigatória? |
|---|---|---|
| Python 3.11+ | Pipeline | Sim |
| FFmpeg **com libass** | Cortes, composição, legendas ASS | Sim |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) | Stages de IA (plan, review, overlay, evaluate, metadata) | Sim, para editar com IA |
| [Node.js 22+](https://nodejs.org) | Renderizar os templates HyperFrames (`npx`) | Para overlays/legendas animadas |
| Internet | O primeiro `npx` baixa o HyperFrames; os templates carregam GSAP e a fonte Montserrat por CDN | Para overlays/legendas animadas |

Sem Node, o pipeline continua funcionando: overlays de template são pulados com aviso e as legendas usam o ASS.

## Instalação

### Windows

```powershell
git clone https://github.com/Alemoterani/auto-edit-hyperframes.git
cd auto-edit-hyperframes
python -m venv .venv
.venv\Scripts\pip install -e ".[test]"
```

- **FFmpeg com libass**: use o build "full" do [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (`winget install Gyan.FFmpeg`) e confira que `ffmpeg` está no PATH.
- **Node.js 22+**: `winget install OpenJS.NodeJS.LTS`
- **Claude Code**: `npm install -g @anthropic-ai/claude-code`

Rode com `.venv\Scripts\auto-edit ...` (ou ative o venv com `.venv\Scripts\activate` e use `auto-edit ...`).

> O repositório tem ~250 MB por causa do código do HyperFrames em `vendor/`. Para um clone mais leve: `git clone --depth 1 ...`.

### macOS / Linux: curl | bash

```bash
curl -sSL https://raw.githubusercontent.com/Alemoterani/auto-edit-hyperframes/main/install.sh | bash
```

Detecta e instala o que falta (Python, FFmpeg, git) via Homebrew, apt, dnf ou pacman e instala em `~/.auto-edit-hyperframes/`. Instale o Node.js 22+ à parte para os overlays animados.

### macOS / Linux: Nix

```bash
nix profile install github:Alemoterani/auto-edit-hyperframes
# ou, sem instalar:
nix run github:Alemoterani/auto-edit-hyperframes -- short video.mp4 --context "..."
```

Na primeira execução o auto-edit cria um venv e instala as dependências Python (~2 GB com PyTorch/Whisper).

> O comando continua se chamando `auto-edit`. Se você também tem o auto-edit-video original instalado, deixe só um deles no PATH.

### Conferir o setup

```bash
auto-edit doctor
```

Mostra Python, FFmpeg, pacotes, agentes, overlays, **npx (hyperframes)** e o CLI de LLM. A primeira renderização baixa o HyperFrames via `npx` (uma vez só).

Desinstalar: `bash ~/.auto-edit-hyperframes/uninstall.sh` (curl | bash) ou `nix profile remove auto-edit-video` (Nix).

## Uso

### Long (horizontal) com overlays animados

```bash
auto-edit long upload/meu-video.mp4 \
  --context "Tutorial de Python para iniciantes, tom didático"
```

O agente de overlay lê a transcrição e decide onde colocar cada template. Você só precisa dar um bom `--context`: ele é usado para os cortes **e** para escrever os textos dos gráficos.

### Short (vertical) com legendas animadas

```bash
auto-edit short upload/meu-video.mp4 \
  --context "Review de produto tech, tom casual" \
  --caption-engine hyperframes
```

Sem `--caption-engine hyperframes`, as legendas usam o motor ASS original (rápido). Se o render HyperFrames falhar por qualquer motivo, o stage cai automaticamente no ASS.

### Refazer só os overlays (sem IA)

Editou o `workspace/<video>/overlay_plan.json` na mão (trocou um texto, mudou um tempo)? Recomponha sem chamar o Claude:

```bash
auto-edit apply-overlays upload/meu-video.mp4
```

### Outros comandos

```bash
auto-edit batch upload/pasta/ --type short --context "..."              # vários vídeos
auto-edit merge upload/clips/ --name final --type long --context "..."  # concatena + edita
auto-edit resume upload/meu-video.mp4 --from overlay                    # retoma de um stage
auto-edit status upload/meu-video.mp4                                   # estado do pipeline
```

## Templates disponíveis

| Template | `vars` | Quando o agente usa | Duração |
|---|---|---|---|
| `lower_third` | `title`, `subtitle` | Quem fala se apresenta; convidado, ferramenta ou produto citado pela primeira vez | 4 s |
| `cta` | `text` | Pedido de inscrição/seguir/curtir | 3–4 s |
| `highlight` | `label`, `text` | Termo ou lição-chave sendo explicada, quando nenhum explicativo abaixo encaixa melhor | 4–6 s |

### Templates explicativos (motion graphics)

Ilustram **o que você está explicando**. O agente escolhe pelo formato do que é dito e usa só dados que aparecem na fala — nunca inventa números, passos ou código.

| Template | `vars` | Quando o agente usa | Duração |
|---|---|---|---|
| `steps` | `title`, `items` (2–5) | Você lista passos, dicas ou motivos ("primeiro…, depois…") — os itens aparecem um a um | 5–10 s |
| `stat` | `value`, `prefix`, `suffix`, `decimals`, `label` | Um número marcante — o valor conta de 0 até ele (formato brasileiro: `R$ 1.250,50`) | 4–5 s |
| `compare` | `title`, `left_label`, `left`, `right_label`, `right` | Um contraste: antes × depois, errado × certo, mito × fato | 5–7 s |
| `code` | `code`, `language`, `caption` | Um comando, atalho ou trecho de código — aparece sendo digitado | 4–7 s |
| `chart` | `title`, `bars`, `unit`, `highlight` | Comparação entre quantidades (preços, taxas, tempos) — barras crescem até o valor | 5–7 s |

No vídeo horizontal eles ficam **à direita** (sem cobrir o rosto); no vertical ficam **no topo** (sem cobrir as legendas). No máximo um explicativo a cada ~30 s.

```json
{"template": "stat", "vars": {"value": 1250.5, "prefix": "R$ ", "decimals": 2, "label": "perdidos por ano em juros do cartão"}, "original_start": 42.0, "duration": 5}
{"template": "compare", "vars": {"left_label": "Mito", "left": "O salário vai ser cortado", "right_label": "Fato", "right": "Só muda o calendário"}, "original_start": 88.3, "duration": 6}
```

Todos aceitam `"accent": "#RRGGBB"` em `vars` para mudar a cor. Exemplo de `overlay_plan.json`:

```json
{
  "overlays": [
    {"template": "lower_third", "vars": {"title": "Ana Souza", "subtitle": "Dev Python"}, "original_start": 4.1, "duration": 4},
    {"template": "highlight", "vars": {"label": "Dica", "text": "Rode os testes antes do commit"}, "original_start": 120.4, "duration": 5},
    {"template": "cta", "vars": {"text": "Se inscreve no canal"}, "original_start": 245.8, "duration": 4}
  ]
}
```

Os MP4s com tela verde antigos (`assets/overlays/ctas.mp4` etc.) continuam funcionando com `"file": "ctas.mp4"`.

### Criar ou mudar um template

Um template é uma pasta em `hyperframes/overlays/<nome>/` com um `index.html`. O contrato é pequeno:

1. **Raiz da composição**: `<div id="root" data-composition-id="main" data-start="0" data-duration="…" data-width="…" data-height="…">`. O auto-edit reescreve duração e tamanho a cada render; escreva qualquer valor razoável.
2. **Dados**: carregue `<script src="data.js"></script>` e leia `window.AE_DATA`, com valores padrão para o template abrir sozinho no navegador.
3. **Animação**: crie uma timeline GSAP pausada e registre em `window.__timelines.main`. O HyperFrames controla o tempo quadro a quadro.
4. **Fundo transparente** (`background: transparent`) e tamanhos relativos (`%`, `vmin`) para funcionar em 16:9 e 9:16.

Para pré-visualizar, abra o `index.html` no navegador (usa os valores padrão) ou rode `npx hyperframes preview hyperframes/overlays/<nome>`. Depois, descreva o novo template em [`agents/overlayer.md`](agents/overlayer.md) para o agente saber quando usá-lo. Use os templates existentes como modelo.

Referência completa do formato: [`vendor/hyperframes/docs/reference/html-schema.mdx`](vendor/hyperframes/docs/reference/html-schema.mdx).

## Desempenho

O render é quadro a quadro num Chrome headless, então é mais lento que o FFmpeg puro. Por padrão o auto-edit usa **1 processo de Chrome** por render (`AUTO_EDIT_HF_WORKERS=1`) para não sobrecarregar a máquina; em um PC estável e com folga, `AUTO_EDIT_HF_WORKERS=auto` usa todos os núcleos e fica bem mais rápido. Medido num PC Windows comum com `auto`:

| O quê | Tempo |
|---|---|
| Um overlay de 3–4 s (primeira vez) | ~30 s |
| O mesmo overlay de novo (cache) | instantâneo |
| Legendas HyperFrames | ~3 min a cada 30 s de short |
| Legendas ASS (padrão) | segundos |

A camada de legendas em ProRes ocupa ~300 MB por minuto e é apagada logo depois da composição. O cache de overlays fica em `workspace/<video>/hf_cache/`.

## Planejamento de conteúdo (`auto-edit plan`)

Além de editar, o auto-edit ajuda a **planejar** o que tu vai postar. Plans semanais ou mensais geram tópicos (longs + shorts), datas de gravação/publicação e talking points — usando IA + um perfil livre que tu escreve sobre teu canal.

O fluxo fecha o loop entre **planejamento → gravação → edição**: cada vídeo editado é vinculado a um slot do plano, e o `status` cruza isso com as datas pra dizer o que tá pronto, atrasado ou pendente.

### Setup (uma vez)

```bash
# Criar diretório e templates
auto-edit plan path

# Editar teu perfil (texto livre — o planner usa como contexto)
$EDITOR ~/.auto-edit/profile/identity.md
$EDITOR ~/.auto-edit/profile/channel_history.md

# (Opcional) apontar pra pasta onde tu joga as gravações
export AUTO_EDIT_INBOX="/Volumes/XPG/Movies/precisa-editar"
```

### Gerar um plano

```bash
# Plano semanal (3 longs + 6 shorts por padrão)
auto-edit plan new -w next \
  -c "essa semana: foco em IA + 3D" \
  -s "long sobre auto-edit pipeline; setup Bambulab"

# Plano mensal (12 + 24)
auto-edit plan new -m next -c "..." -s "..."

# Atalhos
auto-edit plan new -w current      # semana atual
auto-edit plan new -m 2026-06      # mês explícito
```

### Ver, editar, listar

```bash
auto-edit plan show               # default: semana atual
auto-edit plan show -w 2026-W19   # semana específica
auto-edit plan edit               # abre yaml no $EDITOR
auto-edit plan list               # todos os plans existentes
```

### Vincular vídeos ao plano (ingest)

```bash
# Lista slots pendentes, tu escolhe um, depois escolhe a pasta
auto-edit plan ingest

# Auto-pareia pastas nomeadas como 2026-W19_S2_xxx ou
# que casam com o `source_folder` do yaml; o resto cai no interativo
auto-edit plan ingest --run    # já edita tudo no fim
```

### Acompanhar progresso

```bash
auto-edit plan status            # default: semana atual
auto-edit plan status --all      # todos os plans
```

| Status | Quando |
|---|---|
| `planned` | Nenhum workspace existe vinculado ao slot |
| `recorded` | Workspace existe, pipeline em andamento |
| `edited` | Pipeline terminou |
| `published` | Tu marcou manualmente no yaml |
| ⚠ late | `publish_at < hoje` E ainda não foi editado |

### Loop bidirecional (inbox → planner)

Se `$AUTO_EDIT_INBOX` aponta pra uma pasta com subpastas de gravações, o `plan new` lê os nomes dessas subpastas e o planner sugere slots que **cobrem o que tu já filmou** — em vez de inventar tópicos do zero. Cada slot ganha um campo `source_folder` que o `ingest` usa pra parear automaticamente sem renomear.

### Onde mora tudo

```
~/.auto-edit/                       # sobrescrito por $AUTO_EDIT_HOME
├── profile/                        # markdowns livres lidos pelo planner
│   ├── identity.md
│   ├── channel_history.md
│   └── ... (qualquer .md vai como contexto)
└── plans/
    ├── 2026-W19.yaml
    └── 2026-06.yaml
```

Plans ficam fora do repo opensource — dado pessoal.

### Vincular um vídeo direto (sem ingest)

```bash
auto-edit short video.mp4 --plan-id S2     # forma curta (se único)
auto-edit short video.mp4 --plan-id 2026-W19/S2
auto-edit merge folder/ --type long --plan-id L1
```

Sem `--plan-id`, se houver slots pendentes, a CLI pergunta interativamente. Use `--no-plan-prompt` pra desligar o prompt.

## Claude Code Extension

### MCP Server (recomendado)

O auto-edit-video funciona como extensão do Claude Code via MCP. Adicione ao seu `~/.claude.json` ou `.claude/settings.json`:

```json
{
  "mcpServers": {
    "auto-edit-video": {
      "command": "auto-edit",
      "args": ["mcp-server"]
    }
  }
}
```

Requer a dependência MCP: `pip install auto-edit-video[mcp]`

Depois disso, o Claude Code ganha acesso direto a tools como `edit_short`, `edit_long`, `pipeline_status`, `resume_pipeline` e `doctor`. Basta conversar normalmente:

> "Edita o vídeo video.mp4 como short, contexto é review de produto tech"

### Slash Commands

O projeto também inclui slash commands para usar dentro do Claude Code (quando estiver no diretório do projeto):

| Comando | O que faz |
|---------|-----------|
| `/edit-video` | Guia interativo para iniciar uma edição |
| `/edit-status` | Dashboard de todos os pipelines ativos |
| `/edit-preview` | Preview textual do que vai ser cortado |
| `/review-cuts` | Aprovar/editar o cut plan antes de executar |
| `/fix-stage` | Diagnostica e corrige um stage com falha |

## Opções

### Modelo Whisper

| Modelo | Velocidade | Precisão | Uso |
|--------|-----------|----------|-----|
| `tiny` | Muito rápido | Básica | Áudio limpo, fala clara |
| `base` | Rápido | Boa | Testes rápidos |
| **`small`** | **Moderado** | **Muito boa** | **Recomendado (default)** |
| `medium` | Lento | Excelente | Áudio ruidoso, múltiplos falantes |
| `large` | Muito lento | Máxima | Quando precisão é crítica |

### Legendas (shorts)

```bash
auto-edit short video.mp4 \
  --caption-engine hyperframes   # ass (padrão, rápido) ou hyperframes (animado)
  --highlight-color "&H0045FF&"  # cor de destaque (formato ASS BBGGRR), vale para os dois motores
  --highlight-border 2.5         # espessura do destaque (ASS)
  --font-size 14                 # tamanho da fonte (ASS)
```

### Variáveis de ambiente úteis

| Variável | Efeito |
|---|---|
| `AUTO_EDIT_HF_WORKERS` | Processos de Chrome por render HyperFrames (padrão `1`; `auto` = todos os núcleos) |
| `AUTO_EDIT_OVERLAYS_STRICT=1` | Falha o stage `overlay` se um overlay planejado não puder ser gerado (MP4 ausente ou render HyperFrames com erro), em vez de só avisar |
| `AUTO_EDIT_ASSETS_OVERLAYS` | Pasta com seus MP4s de overlay com tela verde |
| `AUTO_EDIT_FFMPEG` | FFmpeg específico (com libass) para as legendas ASS |
| `AUTO_EDIT_LLM` / `AUTO_EDIT_LLM_FALLBACK` | CLI de LLM principal e reserva (`claude`, `cursor`…) |
| `AUTO_EDIT_LLM_TIMEOUT` | Timeout das chamadas de LLM em segundos (padrão 600) |

### LLM Backend

```bash
auto-edit short video.mp4                                     # Claude (padrão)
auto-edit short video.mp4 --cli claude --cli-fallback cursor  # com fallback
```

## Fluxo de dados por stage

```
upload/video.mp4
  → workspace/video/
      transcription.json          ← extract
      cut_plan.json               ← plan
      reviewed_plan.json          ← review
      edited_video.mp4            ← execute (cortes + loudnorm)
      overlay_plan.json           ← overlay (agente: templates + textos)
      hf_cache/*.mov              ← overlay/caption (renders HyperFrames com alpha)
      overlaid_video.mp4          ← overlay [long]
      captions.ass / captions.srt ← caption
      captioned_video.mp4         ← caption [short]
      post_cut_transcription.json ← caption (tempos remapeados)
      assessment.json             ← evaluate
      metadata.json               ← metadata
  → output/video_final.mp4        ← done
  → output/video.txt              ← done (título + descrição + hashtags)
```

## Funcionalidades técnicas

- **Overlays com alpha**: renders HyperFrames entram sem chroma key; MP4s com tela verde continuam com chroma key
- **Overlays no tempo certo**: cada overlay começa a tocar no instante em que aparece (antes, overlays depois de t=0 ficavam congelados no último quadro)
- **Versão do HyperFrames fixada** pelo código em `vendor/hyperframes`
- **Fallback seguro**: sem Node ou com erro de render, overlays são pulados com aviso e legendas voltam ao ASS
- **Codec fallback**: `h264_videotoolbox` → `libx264` → `libx265`
- **Normalização de áudio**: EBU R128 (`loudnorm`) após os cortes
- **Correção de transcrição com IA** e **timestamps remapeados** sem re-rodar o Whisper
- **Persistência de erros** no `pipeline.json` e **retomada** de qualquer stage

## Testes

```bash
pip install -e ".[test]"
python -m pytest tests/ -q
```

Os testes do HyperFrames não abrem o Chrome (o render é simulado). Para testar de ponta a ponta, rode `auto-edit long` num vídeo curto.

## Créditos e licenças

Este repositório combina dois projetos com licenças diferentes. Ao redistribuir, mantenha as duas.

### HyperFrames: Apache 2.0

Copyright HeyGen. Código em [`vendor/hyperframes/`](vendor/hyperframes/), licença em [`vendor/hyperframes/LICENSE`](vendor/hyperframes/LICENSE). O snapshot não foi modificado, exceto pela remoção das fixtures de teste em Git LFS e das regras de LFS do `.gitattributes` (ver [`vendor/README.md`](vendor/README.md)).

### auto-edit-video: PolyForm Noncommercial 1.0.0

Required Notice: Copyright (c) 2026 Gabriel Sampaio (gabuldev) <contato@gabul.dev>

O código do auto-edit (tudo fora de `vendor/`) é **source available** sob a
[PolyForm Noncommercial License 1.0.0](LICENSE) — não é uma licença open source
no sentido da OSI, porque restringe o uso comercial.

**O que você pode fazer (grátis):**

- ✅ Usar, estudar e modificar o código para **fins não-comerciais**
- ✅ Uso pessoal, hobby, pesquisa, educação e organizações sem fins lucrativos
- ✅ Redistribuir com suas mudanças (mantendo esta licença e os avisos de copyright)

**O que requer licença comercial paga:**

- 💼 Qualquer uso com finalidade comercial (produtos, serviços, uso em empresa
  com fins lucrativos)
- 💼 Oferecer o `auto-edit-video` (ou este `auto-edit-hyperframes`) — ou um derivado — como serviço/produto pago

#### Versão hosted & licença comercial

A **versão hospedada (SaaS) é um produto pago oficial e exclusivo** do
mantenedor. Se você precisa usar o projeto comercialmente ou quer a versão
hosted, entre em contato para adquirir uma licença comercial:

📧 **contato@gabul.dev**

> Modelo de *dual licensing*: o código fica público sob a PolyForm Noncommercial
> para a comunidade, enquanto o mantenedor (Gabriel Sampaio / gabuldev) oferece
> licenças comerciais e a versão hosted paga à parte. Veja
> [`CONTRIBUTING.md`](CONTRIBUTING.md) para os termos de contribuição.
