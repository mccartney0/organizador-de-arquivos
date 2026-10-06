# Auditoria de duplicados

## Diagnóstico da versão anterior

A aba **Duplicados exatos** usa exclusivamente o campo `sha256`. Ela não compara nomes. O fluxo agrupa primeiro por tamanho para economizar leituras e depois compara o hash SHA-256 do conteúdo completo. Portanto, dois arquivos com nomes diferentes, extensões diferentes ou locais diferentes aparecem como duplicados exatos se o conteúdo for idêntico; arquivos com nomes iguais ou parecidos, mas conteúdos diferentes, não aparecem nessa aba.

A aba **Nomes similares** é separada. Ela normaliza nomes, remove alguns marcadores e aproxima textos. Um grupo dessa aba não é uma prova de duplicidade e não deve ser tratado como duplicado sem revisão.

## Problemas identificados

A implementação anterior calculava hash de todos os candidatos com o mesmo tamanho, mesmo quando já havia hash válido. Isso repetia leituras caras em vídeos grandes. Além disso, um hash já calculado não tinha o tamanho e a data usados para provar que o arquivo não havia sido alterado depois. A interrupção durante a leitura podia retornar um digest parcial, que não deveria ser gravado como hash válido. A interface também não deixava explícita a diferença entre arquivos candidatos por tamanho, grupos confirmados por hash e grupos apenas semelhantes por nome.

## Melhorias adotadas

1. A tabela passa a registrar `hash_size` e `hash_mtime` junto com o hash. Um hash só será considerado válido quando esses metadados ainda coincidirem com o arquivo atual.
2. O cálculo de hash ignora candidatos que já têm hash válido, mas permite recalcular quando tamanho ou data mudarem. A aplicação também atualiza metadados no banco antes de consultar os grupos, para detectar alterações feitas fora dela.
3. A interrupção durante a leitura não grava um hash parcial.
4. O botão **Recalcular todos** permite repetir a confirmação por SHA-256 mesmo quando o tamanho e a data não mudaram, útil para mídias ou sistemas de arquivos com timestamps pouco confiáveis.
4. A aba de duplicados mostra texto explicativo: a confirmação é por SHA-256, não por nome.
5. O resumo informa grupos confirmados por conteúdo e quantidade de candidatos ainda pendentes.
6. A aba de nomes similares permanece separada e passa a deixar explícito que seus grupos são sugestões por nome, não duplicados exatos.
7. Ações destrutivas continuam exigindo confirmação e a quarentena permanece como alternativa reversível.

## Interpretação correta

| Tela | Critério | Pode afirmar que o conteúdo é igual? |
|---|---|---:|
| Duplicados exatos | Mesmo tamanho + mesmo SHA-256 do conteúdo completo | Sim, salvo erro físico de leitura ou alteração durante a análise |
| Nomes similares | Nome normalizado e similaridade textual | Não |
| Arquivos selecionados | Comparação manual de metadados e hash disponível | Não automaticamente |

## Melhorias futuras recomendadas

Para acervos extremamente grandes, pode ser acrescentada uma etapa opcional de comparação rápida por amostras antes do SHA-256 completo, mantendo o SHA-256 como confirmação final. Também seria útil integrar duração, resolução, codec e taxa de bits por vídeo com FFprobe opcional, sem fazer essa dependência obrigatória. Miniaturas e comparação visual devem ser opcionais, pois podem consumir muito espaço temporário e processamento.
