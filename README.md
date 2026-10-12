# Modrinth Batch Downloader V5

Aplicativo desktop minimalista (Windows) para baixar projetos do Modrinth em lote: **mods, shaders, resource packs e datapacks**, analisar JARs locais, conferir dependências, detectar conflitos, atualizar mods e converter para outra versão do Minecraft.

## Executar pelo Python

1. Instale Python 3.10 ou superior no Windows (com Tkinter, que já vem no instalador oficial).
2. Extraia o ZIP para uma pasta normal.
3. Execute `run.bat` (instala `certifi`, `truststore` e `Pillow` e abre o app).

## Gerar o `.exe`

Execute `build_exe.bat`. O executável fica em `dist\ModrinthBatchDownloader.exe`. O `.exe` precisa ser compilado no Windows.

## Novidades da V5

**Downloads**
- **Downloads em paralelo** (3–5 threads, padrão 4): resolução de projetos, dependências e arquivos acontecem ao mesmo tempo. Em um teste com 50 mods simulados, 1 thread levou 15,3 s; 3 threads, 5,3 s; 4, 4,0 s; 5, 3,1 s.
- **Progresso por arquivo**: MB baixados e velocidade em MB/s em tempo real (cartão "Baixando agora"), e barra global baseada no andamento real dos downloads.
- **Verificação de hash**: SHA-1 e SHA-512 publicados pelo Modrinth são conferidos; se algo não bater, o arquivo é descartado, marcado como **corrompido** e registrado como **falha de segurança** (sem retry).
- **Retry automático** em erro de rede, timeout, 5xx e **429**: até 2–3 tentativas com espera crescente (1 s, 2 s, 4 s + jitter), respeitando `Retry-After`.
- **Atualização inteligente**: se o arquivo já existe, compara o SHA-1 com o do Modrinth (idêntico = pulado, mesmo se renomeado; diferente = baixa de novo). Ao baixar uma versão nova de um mod que já está na pasta, a antiga é guardada como `nome.jar.old` (evita ID duplicado).
- **Somente releases estáveis**: usa release; se não houver, cai para beta e, por último, alpha (com aviso no log).
- **Outros tipos de projeto**: `shader` → `shaderpacks/`, `resourcepack` → `resourcepacks/`, `datapack` → `datapacks/` (também `plugin` → `plugins/` e `modpack` → `modpacks/`). Mods continuam na raiz da pasta de destino.

**Mods ativos**
- Botão **Verificar atualizações**: calcula o SHA-1 dos JARs, pergunta ao Modrinth e lista o que tem versão nova **para o mesmo jogo e o mesmo loader** selecionados. **Atualizar todos** baixa as novas versões e reescaneia a pasta.
- **Mods x bibliotecas**: a lista "Mods" mostra o que cada mod requer (✔ instalado / ✖ ausente) e a lista "Dependências instaladas" mostra as bibliotecas e por quais mods são exigidas. Os módulos embutidos do Fabric API (jar-in-jar) e apelidos de ID (`provides`, como `cloth-config2`) contam como instalados. "Dependências ausentes" lista só o que realmente falta e quais mods o exigem.
- **Detecção de conflitos**: aviso quando há dois JARs com o mesmo mod ID ou JARs de loaders diferentes misturados na pasta (também checado após cada download).

**Relatório e acabamento**
- **Relatório final** (também no **Histórico**): baixados, pulados, incompatíveis e falhas; botões **Copiar incompatíveis** (formato `Título — link`, que pode ser colado de volta na lista de links), **Exportar log**, **Abrir pasta**.
- **Notificação do Windows** ao concluir (liga/desliga em Configurações) e botão **Abrir pasta** na tela Download.
- **Pré-visualização** ao colar links: ícone, nome, tipo e versão compatível de cada projeto.
- **Versões do Minecraft vindas da API** (lista suspensa; ainda dá para digitar). Opção de incluir snapshots.
- **Idioma PT/EN** e **tamanho da interface** (90–150%) em Configurações.
- **Ícone**: mascote novo (corvo + maçã verde). Em Configurações você escolhe uma imagem para o ícone da janela (vale na hora) e para o `.exe` (vale no próximo `build_exe.bat`).
- **Verificação de nova versão do app**: veja "Configurando a verificação de versão" abaixo.

## Configurando a verificação de versão do app

O app consulta uma URL que devolve a versão mais recente. Por padrão aponta para um repositório de exemplo (`SEU_USUARIO/modrinth-batch-downloader`) e **fica desativada até você configurar**:

- Edite `UPDATE_URL_DEFAULT` em `core.py` **ou** cole a URL em Configurações > Sobre.
- Funciona com a API de releases do GitHub (`https://api.github.com/repos/USUARIO/REPO/releases/latest`) ou com qualquer JSON como `{"version": "5.1.0", "url": "https://..."}`.

## Arquivos

- `app.py`: telas e ligação com o núcleo.
- `core.py`: API do Modrinth, downloads paralelos, hashes, retry, conflitos, atualizações (sem Tkinter).
- `i18n.py`: textos PT/EN (para adicionar idioma, copie o bloco `en`).
- `ui_kit.py`: widgets visuais (botões, cards, campos, lista suspensa, área rolável, temas).
- `assets/`: mascote e ícones (veja `LEIA-ME_ASSETS.txt`). `tools/make_mascot.py` regenera a arte padrão.
- `tests/`: testes automatizados do núcleo com um servidor Modrinth simulado: `python -m unittest discover -s tests -v`.

## Limitações

A conversão procura builds compatíveis do mesmo projeto; ela não converte o código de um loader para outro. A resolução de dependências depende dos metadados publicados pelos mods. O tema da barra de título depende do suporte do Windows. A notificação usa o toast do Windows via PowerShell (aparece como "Windows PowerShell"). Trocar o ícone do `.exe` exige recompilar, pois o ícone fica embutido no executável.
