# Elgin Lamp

Controle suas lâmpadas inteligentes **Elgin** direto da bandeja do Windows (e do Linux), **pela rede local**: sem nuvem, sem abrir app no celular.

![Painel do Elgin Lamp](docs/screenshot.png)

As lâmpadas Wi-Fi da Elgin usam a plataforma **Tuya** (a mesma do app Smart Life). O app fala com elas pelo protocolo local da Tuya, via [tinytuya](https://github.com/jasonacox/tinytuya), usando o **IP**, o **Device ID** e o **Local Key** de cada lâmpada.

## Recursos

- **Painel na bandeja**: clique no ícone para abrir o painel, que fecha sozinho ao clicar fora.
  - Liga/desliga, **brilho**, **temperatura do branco** (quente ↔ frio) e **cor** (RGB).
  - Escolha uma lâmpada ou **todas** de uma vez.
  - **Cenas** prontas (Leitura, Relaxar, Foco, Noite, Cinema) e personalizáveis.
  - **Timer**: "desligar em 15/30/60/120 min".
- **Rotinas**: horário fixo com dias da semana, **nascer/pôr do sol** com deslocamento em minutos, e as ações ligar, desligar ou aplicar cena.
- **Menu do clique direito**: liga/desliga cada lâmpada, liga/desliga todas e aplica cenas.
- **Clique do meio** no ícone: liga/desliga todas.
- **Iniciar com o Windows** (opção nas configurações).
- **Português e inglês**.
- **Busca na rede** (descobre IP e protocolo) e **importação da nuvem Tuya** (descobre os Local Keys).

## Segurança: seu IP e suas chaves não vão para o projeto

| O quê | Onde fica |
|---|---|
| IP, Device ID, Local Key, rotinas e cenas | `%APPDATA%\ElginLamp\config.dat` (Windows) ou `~/.config/elgin-lamp/config.dat` (Linux) |
| Criptografia no Windows | **DPAPI**: o arquivo só abre na sua conta de usuário, neste PC |
| Criptografia no Linux | **Fernet (AES)**, com a chave no chaveiro do sistema (Secret Service/KWallet) |
| Logs | `elgin-lamp.log` na mesma pasta, sem IP nem chaves (IDs aparecem mascarados como `••••a9c3`) |

Nada é gravado na pasta do projeto. Além disso:

- O `.gitignore` bloqueia `*.dat`, `.env` e os arquivos que o `tinytuya wizard` gera (`devices.json`, `tinytuya.json`, `snapshot.json`), que contêm chaves.
- O hook de pre-commit (`scripts/check_secrets.py`) **impede commits** com IPs de rede local (`192.168.x.x`, `10.x.x.x`, `172.16–31.x.x`), Local Keys ou esses arquivos. Para ativar:

  ```bash
  git config core.hooksPath .githooks
  ```

- O CI do GitHub roda a mesma checagem no repositório inteiro.

> **É perigoso vazar?** O IP local sozinho (192.168.x.x) é de baixo risco, porque só vale dentro da sua rede. Já o **Local Key + Device ID** permitem que qualquer pessoa **na sua rede** controle a lâmpada. Por isso o arquivo inteiro é criptografado.

## Instalação no Windows

### Opção A: baixar o `.exe` pronto

Cada push no GitHub roda o workflow **CI**, que gera o executável. Abra a aba **Actions** do repositório, entre na última execução verde e baixe o artefato **ElginLamp-windows**. Ele contém o `ElginLamp.exe`, que não precisa de instalação.

> O Windows SmartScreen pode avisar que o app é de "editor desconhecido", porque o executável não é assinado. Clique em **Mais informações › Executar assim mesmo**.

### Opção B: gerar o `.exe` no seu PC

Requer [Python 3.10+](https://www.python.org/downloads/) (marque "Add to PATH" na instalação).

```bat
build_windows.bat
```

O script cria um ambiente virtual, instala as dependências, roda os testes e gera `dist\ElginLamp.exe`.

### Opção C: rodar com Python

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pythonw -m elgin_lamp
```

Para testar a interface **sem lâmpada** (lâmpadas simuladas): `python -m elgin_lamp --demo`.

## Primeiro uso

1. Abra o app. Ele aparece na bandeja, perto do relógio (se não aparecer, procure na setinha **^** de ícones ocultos e arraste para a barra).
2. Clique em **Adicionar lâmpada** e preencha:
   - **IP local**, por exemplo `192.168.0.10`. Use **Buscar na rede** para descobrir.
   - **Device ID** e **Local Key**: veja a seção abaixo.
   - **Protocolo**: deixe em **Automático**.
3. Clique em **Testar conexão** e depois em **Salvar**.

> **Dica:** no seu roteador, reserve um IP fixo (reserva DHCP) para cada lâmpada. Se o IP mudar, use **Buscar na rede** de novo: o app atualiza o IP da lâmpada já cadastrada.

## Como obter o Device ID e o Local Key

O Local Key é gerado quando a lâmpada é pareada e fica guardado na nuvem Tuya. Você precisa buscá-lo **uma vez**. Depois disso, o controle é 100% local.

1. **Pareie a lâmpada no app Smart Life** (ou Tuya Smart). Se ela estiver no app da Elgin, tente o passo 4 com essa conta; se não funcionar, remova a lâmpada do app da Elgin e pareie no Smart Life (continua funcionando com Alexa/Google).
2. Crie uma conta em **[iot.tuya.com](https://iot.tuya.com)**. O tipo de conta pode ser pessoal ("Skip" no formulário da empresa).
3. Vá em **Cloud › Development › Create Cloud Project**:
   - *Industry*: Smart Home. *Development Method*: Smart Home.
   - *Data Center*: **Western America** (padrão para contas do Brasil). Se não achar as lâmpadas, tente outro.
   - Aceite os serviços sugeridos (precisa ter **IoT Core**).
4. No projeto, abra **Devices › Link App Account › Add App Account**. Vai aparecer um QR Code: no Smart Life, vá em **Eu/Perfil › ícone de leitor** (canto superior) e escaneie.
5. Na aba **Overview** do projeto, copie o **Access ID/Client ID** e o **Access Secret/Client Secret**.
6. No Elgin Lamp, vá em **Configurações › Lâmpadas › Importar da nuvem Tuya**:
   - Região: `us` (Western America). Use `eu` para Central Europe, e assim por diante.
   - Cole o Access ID e o Secret.
   - Informe o Device ID de qualquer lâmpada (aparece em *Devices* no site da Tuya, ou no Smart Life em *lâmpada › ✎ › Informações do dispositivo › ID virtual*).
   - O app busca os nomes e os Local Keys e encontra os IPs na rede. Marque as lâmpadas e importe.

As credenciais da nuvem **não são salvas**: só os dados das lâmpadas, criptografados.

> **Atenção:** se você **parear a lâmpada de novo**, o Local Key muda. Basta importar outra vez.
> O plano gratuito do IoT Core expira depois de alguns meses, mas só é necessário para buscar as chaves, não para o uso diário.

**Alternativa via terminal:** `python -m tinytuya wizard`, rodado numa pasta **fora** do projeto, gera um `devices.json` com tudo. Copie os valores para o app e apague o arquivo.

## Linha de comando

Usa as lâmpadas já cadastradas no app, então nenhum IP ou chave aparece no comando. Serve para atalhos e para o Agendador de Tarefas.

```bat
python -m elgin_lamp.cli status
python -m elgin_lamp.cli on --lamp Sala
python -m elgin_lamp.cli off
python -m elgin_lamp.cli toggle --lamp Quarto
python -m elgin_lamp.cli brightness 40
```

## Linux

```bash
pip install -r requirements.txt
python -m elgin_lamp
```

- No **GNOME**, o ícone da bandeja precisa da extensão *AppIndicator and KStatusNotifierItem Support*. KDE, XFCE e Cinnamon já suportam.
- "Iniciar com o sistema" cria `~/.config/autostart/elgin-lamp.desktop`.
- A opção de GPS existe só no Windows. No Linux, escolha a cidade ou digite latitude/longitude.

## Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "Sem conexão" | O PC precisa estar na mesma rede da lâmpada. Confira o IP (**Buscar na rede**). |
| "Buscar na rede" não acha nada | Permita o app no **Firewall do Windows** em redes **privadas** (a busca escuta as portas UDP 6666, 6667 e 7000). Verifique se a rede do Windows está como "Privada". |
| Conecta mas não obedece / erro de chave | O Local Key mudou (a lâmpada foi pareada de novo): importe outra vez. Confira também o protocolo (3.3, 3.4 ou 3.5). |
| Funciona às vezes | Lâmpadas Tuya aceitam poucas conexões locais simultâneas. Feche outras integrações locais (Home Assistant/LocalTuya) para testar. |
| Rotina não rodou | As rotinas rodam com o app aberto. Ative **Iniciar com o sistema**. Se o PC estava em suspensão, a rotina ainda roda até 10 min depois do horário. |
| Configuração "não pôde ser lida" | O arquivo foi criado em outro usuário/PC (o DPAPI não abre). Uma cópia foi guardada e o app começou do zero. |

Os logs ficam em `%APPDATA%\ElginLamp\elgin-lamp.log`. Para log detalhado, use `--verbose`.

## Estrutura

```
elgin_lamp/
  app.py          bandeja, instância única, rotinas
  lamp.py         protocolo Tuya (tinytuya) + lâmpada simulada (--demo)
  service.py      threads/fila de comandos sem travar a interface
  storage.py      modelo de dados + arquivo criptografado
  crypto.py       DPAPI (Windows) / Fernet + keyring (Linux)
  scheduler.py    rotinas, nascer/pôr do sol (astral)
  discovery.py    busca na rede + importação da nuvem Tuya
  geo.py          cidades offline + GPS do Windows
  autostart.py    iniciar com o sistema
  i18n.py         português/inglês
  cli.py          linha de comando
  ui/             painel, componentes, configurações, ícone da bandeja
scripts/          check_secrets.py (anti-vazamento), make_icon.py
tests/            pytest
```

## Desenvolvimento

```bash
pip install -r requirements-dev.txt
git config core.hooksPath .githooks
python -m pytest -q
python -m elgin_lamp --demo
```
