# paper-charts

Ferramenta local de linha de comando para localizar e recortar figuras legendadas em um artigo PDF por vez.

## Instalação

Requer Python 3.9 ou superior.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .
```

## Extrair figuras

```powershell
paper-charts extract .\artigos\artigo.pdf --output .\output\artigo
```

Ou execute como módulo Python:

```powershell
py -m paper_charts extract .\artigos\artigo.pdf --output .\output\artigo --dpi 200
```

O comando gera:

- `figures/`: recortes PNG das figuras candidatas.
- `figures.csv`: número e legenda da figura, página do PDF, caminho da imagem, confiança e coordenadas do recorte em pontos PDF.

A contagem de páginas no manifesto começa em 1. A confiança é uma heurística geométrica baseada na distância e no alinhamento horizontal entre a figura e sua legenda; serve como indicação para revisão, não como probabilidade de acerto.

## Como funciona e limitações

O extrator lê texto e layout do PDF, procura legendas iniciadas por `Figure`, `Fig.`, `Figura` ou `Figs.` e associa cada legenda a caminhos vetoriais ou imagens incorporadas próximos. A região é renderizada em PNG, preservando a nitidez de gráficos vetoriais. Textos próximos são incluídos para preservar títulos dos eixos e rótulos.

Esta primeira versão espera que o PDF tenha texto extraível e uma legenda próxima ao gráfico. PDFs digitalizados sem camada de texto, legendas com formatos incomuns, gráficos sem legenda e figuras compostas complexas podem não ser encontrados ou podem gerar recortes imprecisos. Revise as imagens e a coluna de confiança antes de usá-las na extração numérica. A ferramenta ainda não extrai os valores dos gráficos.
