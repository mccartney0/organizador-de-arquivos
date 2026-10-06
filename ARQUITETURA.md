# Organizador HD Local

## Ambiente detectado

O computador conectado usa Windows 11 Home Single Language 64 bits, Python 3.14.3, Node.js 22.19.0 e não possui .NET SDK nem FFmpeg/ffprobe disponíveis. A aplicação será uma desktop nativa em Python com Tkinter/ttk e SQLite, sem dependências externas obrigatórias, para funcionar imediatamente no ambiente detectado.

## Princípios de segurança

1. A primeira operação é somente leitura: a varredura não move, renomeia, apaga nem altera arquivos.
2. Renomeações e movimentações são exibidas como prévia antes de serem executadas.
3. A quarentena é reversível e fica em uma pasta `_Organizador_HD_Quarentena` no mesmo volume, com manifesto JSON para restauração.
4. A exclusão permanente exige seleção explícita e confirmação adicional; nunca ocorre automaticamente durante a análise.
5. O banco SQLite fica na pasta de dados do usuário e armazena somente metadados, não cópias dos vídeos.
6. Operações demoradas executam em thread de trabalho, com progresso e cancelamento.

## Funcionalidades planejadas

- Varredura recursiva de qualquer pasta escolhida, com atualização incremental do índice.
- Classificação por tipo (vídeo, imagem, áudio, documento, compactado, executável e outros), extensão, tamanho, data de modificação e nome.
- Busca, filtros e ordenação por qualquer coluna.
- Agrupamento de nomes similares por nome normalizado e similaridade de texto.
- Identificação de duplicados exatos por SHA-256, primeiro agrupando por tamanho para evitar hashes desnecessários.
- Comparador com recomendação do arquivo maior/mais recente e visualização dos candidatos antes da decisão.
- Renomeação individual e em lote com prévia, substituição de texto, prefixo/sufixo e tratamento de colisões.
- Quarentena reversível para liberar espaço sem apagar imediatamente.
- Exportação CSV do índice e do relatório de grupos.

## Pilha

- Python 3.14+
- Tkinter/ttk para a interface
- SQLite3 para o índice local
- pathlib, os.scandir, hashlib e threading para operações eficientes
- Biblioteca padrão somente; ffprobe é opcional e não é necessário para o primeiro índice

## Limites deliberados

A aplicação não decide sozinha qual vídeo apagar. Ela apresenta evidências — tamanho, datas, nomes e hash — e deixa a ação final para o usuário. Para acervos muito grandes, a tabela pode ser filtrada e exportada sem tentar abrir miniaturas ou carregar o conteúdo dos vídeos.

## Fluxo recomendado

1. Escolher a pasta do HD.
2. Escanear e revisar o resumo por categoria e tamanho.
3. Filtrar vídeos e ordenar por tamanho.
4. Verificar duplicados exatos quando necessário.
5. Abrir grupos similares, comparar candidatos e marcar o que deve ir para quarentena.
6. Revisar o plano e executar a quarentena ou renomeação.
7. Reescanear para confirmar o espaço e a organização final.

## Status

Arquitetura definida para implementação no computador conectado.
