# LampDesk

App de bandeja (PySide6) que controla lâmpadas Wi-Fi do ecossistema Tuya/Smart Life
pela rede local, com automações (regras Quando/Se/Então, cenas reativas Ambilight e Música,
modo foco, pomodoro). O app não é de nenhuma marca: marcas de lâmpadas só aparecem como
exemplos de compatibilidade (lista no README), nunca em textos da interface.

## Comandos

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q   # testes (o CI roda no Windows e no Linux)
python -m pyflakes lampdesk scripts tests        # lint usado pelo CI
python scripts/check_secrets.py --all            # nenhum IP local / Local Key no repositório
python -m lampdesk --demo                        # app com lâmpadas simuladas
python scripts/version.py                        # versão do commit atual
python scripts/build.py                          # executável em dist/ (PyInstaller)
```

No Linux, o Qt precisa de `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`.

## Estrutura

- `lampdesk/lamp.py`: protocolo Tuya (LiveBulb mantém conexão aberta). Sem Qt.
- `lampdesk/service.py`: ponte entre as conexões e a interface. Comandos dentro de `service.automated()`
  vêm das automações; os demais contam como mudança manual (`userCommand`). Lâmpadas em `service.locked`
  (modo foco) ignoram comandos automáticos, salvo `automated(bypass_lock=True)` (o próprio foco e o pomodoro).
- `lampdesk/automation.py`: motor das automações (camadas de luz com prioridade, piscar, fades, ciclo do dia,
  música, pomodoro). `rules.py` tem a lógica sem Qt; `winsys.py`, as leituras do Windows (ctypes/winrt).
- `lampdesk/storage.py` + `crypto.py`: configuração criptografada (DPAPI / Fernet + keyring).
- `lampdesk/paths.py`: pasta de dados, sempre fora do projeto (`LAMPDESK_HOME` sobrescreve, usado nos testes).
- `lampdesk/ui/`: `theme.py` (paletas), `glass.py` (desfoque do fundo do painel),
  `native.py` (DWM/Mica do Windows), `widgets.py` (componentes desenhados à mão),
  `popup.py` (painel), `settings.py`, `automations.py` (aba Automações), `tray.py`.
- `lampdesk/version.py`: versão calculada pelas tags do Git.

## Regras

- **Segurança:** nunca commitar IPs de rede local, Device IDs reais ou Local Keys. Use
  `192.0.2.x` (faixa de documentação) em exemplos e testes. Logs mascaram IDs com `crypto.mask`.
- **Tema:** as cores são variáveis de `theme` trocadas em tempo de execução. Leia `theme.X`
  na hora de pintar; não guarde cor em argumento padrão nem no `__init__`.
- **Textos:** toda string visível passa por `tr()` e precisa existir em `pt` e `en` (`i18n.py`).
- **Migrações de configuração:** mudanças nos exemplos e padrões de quem já usa o app ficam em
  `automation.upgrade_rules` (sobe `RULES_VERSION`); nunca apagar dados do usuário.
- **Ambiente deste PC:** automações e recursos usam o alvo `ROOM` (`storage.py`), não "Todas".
- **Windows sem teste local:** código de DWM, registro e DPAPI não roda no Linux. Mantenha-o
  protegido por `try/except` com um caminho seguro, e diga quando algo não foi testado.
- Comentários, mensagens de commit e textos em português; código no estilo dos arquivos vizinhos.

## Versões e releases

- Ninguém edita número de versão. A versão vem da última tag `vX.Y.Z`: cada commit depois dela
  soma 1 no patch (`1.1.0` → `1.1.1`).
- Cada PR mergeado na `main` (merge commit, não squash) dispara `.github/workflows/release.yml`,
  que cria a tag com o minor seguinte (`v1.2.0`), gera `LampDesk.exe` e `LampDesk-linux-x86_64`
  e publica a release com os dois anexos. A release também pode ser disparada à mão
  (`workflow_dispatch`).
- O build grava a versão em `lampdesk/_version.py` (ignorado pelo Git).

## Screenshots do README

`docs/screenshot*.png` e `docs/settings*.png` são gerados em modo demo, renderizando offscreen
(com fundo de exemplo, sem dados reais). Atualize-os quando a interface mudar de forma visível.
