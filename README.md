# Organizador HD Local

Aplicação desktop local para analisar e limpar acervos grandes de arquivos, com foco em milhares de vídeos. Ela foi construída para o Windows 11 detectado no computador conectado, usando Python 3.14.3 e Tkinter, sem dependências externas obrigatórias.

## Como abrir

Dê duplo clique em `iniciar_organizador_hd.bat`. A janela da aplicação será aberta diretamente no computador. O arquivo `organizador_hd.py` é o código principal e `ARQUITETURA.md` descreve as decisões de segurança.

## Fluxo recomendado para um HD cheio

Escolha a pasta raiz do acervo e clique em **Analisar HD**. A primeira etapa percorre subpastas em modo somente leitura e cria um índice SQLite local. Enquanto a análise estiver em andamento, nenhum arquivo é movido, apagado, renomeado ou aberto.

Depois de concluída a análise, use **Relatório** para ver categorias, extensões mais frequentes e os maiores arquivos. Para trabalhar só com vídeos, marque **Somente vídeos** e ordene a tabela pela coluna **Tamanho**. A busca procura em nome, extensão e caminho.

Para descobrir duplicados exatos, abra a aba **Duplicados exatos** e clique em **Calcular hashes SHA-256**. Esta aba **não usa o nome como critério**: um grupo só é confirmado quando os arquivos têm o mesmo conteúdo completo, comprovado pelo mesmo SHA-256, depois da etapa de candidatos com o mesmo tamanho. O programa evita recalcular hashes que continuam válidos e detecta mudanças feitas fora dele por tamanho e data. Use **Recalcular todos** quando quiser repetir a leitura completa mesmo sem mudança aparente.

Para nomes parecidos, abra **Nomes similares** e clique em **Encontrar nomes similares**. Essa aba é propositalmente separada: o agrupamento usa nome normalizado e similaridade textual, portanto é apenas uma sugestão e **não prova que o conteúdo seja igual**. Use **Comparar grupo selecionado** para examinar tamanho, data, hash e caminho antes de agir.

Para renomear, selecione arquivos na aba **Arquivos** e clique em **Renomear selecionados**. A prévia detecta colisões, preserva extensões e permite substituir texto, aplicar prefixo, sufixo e numeração. A confirmação final é necessária.

Para liberar espaço com possibilidade de desfazer, selecione os arquivos e use **Enviar para quarentena**. A aplicação cria `_Organizador_HD_Quarentena` dentro da pasta analisada, move os arquivos mantendo a estrutura relativa e grava `manifest.jsonl`. Na aba **Quarentena / restauração**, é possível restaurar os itens aos caminhos originais, desde que o destino não esteja ocupado.

## Proteções

A aplicação não apaga permanentemente arquivos durante o fluxo normal. Ela não escolhe sozinha o que deve ser removido. A recomendação de manter o maior arquivo é apenas um auxílio para comparação; confira resolução, duração e conteúdo em seu player antes de colocar algo em quarentena.

## Análise opcional de vídeos

O computador conectado possui `ffprobe` e `ffmpeg` disponíveis. Na aba **Arquivos**, selecione vídeos e clique em **Analisar vídeos selecionados** ou clique em **Analisar todos os vídeos**. A operação ocorre em segundo plano e exibe resolução, duração, codec de vídeo/áudio, FPS, bitrate e contêiner na tabela. A análise não move, renomeia, exclui nem regrava o vídeo.

Nas telas de comparação, as mesmas informações aparecem para cada arquivo. O botão **Analisar vídeo** força uma nova leitura do item selecionado. O botão **Miniatura** gera uma imagem PNG somente quando solicitado; se já existir uma versão em cache, ela é reutilizada. O cache fica em `%LOCALAPPDATA%\\OrganizadorHD\\thumbnails`, separado do acervo original. Essas tabelas agora aceitam seleção múltipla, **Selecionar tudo**, **Limpar seleção**, renomeação em massa, quarentena em massa e exclusão em massa.

Na aba **Duplicados exatos**, selecione vários grupos ou use **Selecionar tudo**. As ações **Quarentena dos duplicados** e **Excluir duplicados** mantêm automaticamente o maior arquivo de cada grupo e agem apenas nos demais. Na aba **Nomes similares**, as ações em massa afetam todos os arquivos dos grupos escolhidos, com aviso explícito, pois nome semelhante não prova conteúdo igual.

Se `ffprobe` ou `ffmpeg` não forem encontrados, a aplicação continua funcionando com classificação, hashes, comparação, renomeação e quarentena; apenas os controles de vídeo ficam indisponíveis até que o FFmpeg seja instalado e o programa seja reiniciado. Arquivos corrompidos ou incompatíveis aparecem com erro de análise, sem interromper os demais vídeos.

## Arquivos de dados

O índice fica em `%LOCALAPPDATA%\OrganizadorHD\index.sqlite3`. A tabela principal contém os metadados dos arquivos; a tabela `video_metadata` guarda a análise de vídeos e a referência do cache de miniaturas. O índice contém metadados e hashes calculados, não cópias dos arquivos. O CSV exportado inclui também resolução, duração, codecs, FPS, bitrate, contêiner e erros de análise.

## Observações

A varredura básica continua sem depender do FFmpeg/ffprobe e não abre nem decodifica vídeos. A análise avançada é opcional, usa os executáveis somente nos vídeos solicitados e ocorre em worker separado. A comparação por tamanho, data, nome, SHA-256 e metadados de vídeo cobre os cenários de limpeza sem alterar o conteúdo.

## Teste rápido

Para validar a instalação sem tocar em seu acervo, crie uma pasta de teste com alguns arquivos pequenos, analise essa pasta, renomeie uma cópia e envie outra para quarentena. Confirme a restauração pela aba correspondente antes de usar em seu HD principal.
