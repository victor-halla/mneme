# Decisões de arquitetura

Registro curto e datado das decisões que mudaram o desenho do Mneme. Cada entrada diz o que foi
decidido, por quê e, quando houver, o que ficou descartado. Decisão revista vira entrada nova que
aponta para a anterior, em vez de reescrever a história.

## 2026-09-19 — Markdown e Git são a fonte canônica

Mem0 e Codebase Memory são derivados reconstruíveis e nenhum dos dois pode ser fonte de verdade.
Razão: derivado se refaz, canônico não. Consequência prática: todo dado que importa precisa existir
como arquivo versionado antes de existir em qualquer índice.

## 2026-09-19 — `~/.hermes` nunca é base canônica

O diretório do harness pertence ao runtime, não ao conhecimento. A migração copia conhecimento,
projetos e recursos; skills, cron e sessões permanecem no harness.

## 2026-09-20 — Pacote e instância em repositórios separados

O pacote (código, schemas, skill, testes) é reutilizável e público. A instância (fatos, entidades,
projetos, recursos) é por instalação, vive fora do checkout e é privada quando o conteúdo for
confidencial. Razão: release de software não se mistura com fato pessoal, e o mesmo pacote precisa
servir vários agentes. Descartado: guardar dados e código na mesma árvore.

## 2026-09-20 — A máquina de desenvolvimento não guarda a instância

Máquina de desenvolvimento recebe o pacote, não os dados. Os dados ficam na máquina que opera o
agente, em `~/mneme`, com repositório privado. Razão: reduz superfície e evita cópia de dado pessoal
em máquina secundária.

## 2026-09-20 — Pacote público com licença MIT

O pacote é publicado para outras pessoas usarem e colaborarem. A instância nunca é pública.

## 2026-09-20 — Push sempre com autorização explícita

`git.allow_push: false` é o padrão e nenhum comando empurra conteúdo sozinho, nem `--force`. Razão:
histórico com dado pessoal não se reescreve por acidente.

## 2026-09-20 — Mem0 é opcional, com dois protocolos

O Mem0 cloud (`https://api.mem0.ai`, `/v3/memories/add/` e `/v3/memories/search/`,
`Authorization: Token`) é o padrão; o servidor OSS (`/memories`, `/search`, `X-API-Key`) é a
alternativa, e `providers.mem0.api` declara qual usar quando o host não deixa claro. Com
`enabled: false` o Mneme funciona inteiro: nada de rede, nada enfileirado, busca local por FTS.
Razão: memória semântica é conveniência e não pode virar dependência obrigatória.

## 2026-09-20 — Binários por rclone, em qualquer backend

O transporte de binários é o rclone, então qualquer backend suportado por ele serve: Google Drive,
S3, WebDAV, OneDrive, Backblaze ou um diretório local. O cache local é `assets/drive`, ignorado pelo
Git e descartável; a fonte é o backend. `--drive-root-folder-id` só é enviado a remote do tipo
drive, e remote do Drive sem pasta configurada é recusado, porque copiaria a raiz inteira da conta.
Descartado: implementar a API do Google à mão, que amarraria o pacote a um fornecedor.

## 2026-09-20 — Instalação assistida que nunca sobrescreve

`brain setup` pergunta os valores que variam por máquina, instala runtime, skill e CLI, e cria ou
adota a instância. Sem terminal interativo não escreve nada: mostra o comando. Instância existente é
adotada, e só as chaves informadas mudam. Razão: instalação é o momento em que erro custa dado.

## 2026-09-20 — Skill e instruções entre harnesses

A skill é um `SKILL.md` no padrão aberto Agent Skills, então a mesma pasta serve Hermes e Claude Code
(`install_skill.sh --harness claude`); o contrato de instruções da instância é `AGENTS.md`. Razão: o
dado não pertence a harness nenhum, e conhecimento não deve ser reescrito por ferramenta.

## 2026-09-20 — Bootstrap versionado, isolado e sem privilégios

O caminho principal de instalação é um `install.sh` público e autocontido. Ele baixa o pacote, valida o
SHA-256 quando informado, cria um venv por release, testa o runtime em staging e só então troca o symlink
`current`. CLI e skill também são preparadas antes da promoção. Razão: o usuário não precisa manter um
checkout nem alterar o Python do sistema, e uma falha de download ou dependência não substitui a versão
ativa. O checkout continua sendo o caminho de desenvolvimento. Descartados: `pip --user` como instalação
principal e atualização por cópia incremental da skill, que deixava arquivos removidos para trás.

## 2026-09-20 — Dado pessoal que não pode ser versionado tem destino fora do Git

Identificador, contato, endereço, dado de saúde e documento não entram no Git, nem em repositório
privado. O valor fica em um arquivo local por host, declarado em `privacy.sensitive_file` e com modo 600;
o cérebro guarda o fato e a referência, nunca o valor. Razão: versão não é o único critério de exposição,
e o repositório privado ainda é copiado, clonado e indexado; separar o valor do fato mantém o
conhecimento útil sem transportar o dado. O arquivo é por host porque cada máquina tem seu próprio
contexto de exposição e não há sincronização desse conteúdo. Descartados: guardar o valor em pasta
privada do harness, que é runtime e não base de conhecimento; e criar seção nova no cérebro para o
valor, que apenas renomearia o problema.
