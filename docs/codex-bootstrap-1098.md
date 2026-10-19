# Bootstrap do coletor Codex — #1098

Em 17/10/2026, Alan aprovou explicitamente preparar e testar a correção de infraestrutura antes de concluir o Design, preservando as verificações e aprovações humanas. Não houve T7/T8, submissão do Design, commit, push, release ou alteração da confiança da conta.

## Correção preparada

- Host deixa de ser uma comparação exclusiva com `codex_exec`: o formato, a origem e as garantias continuam verificados.
- Qualificação separada por superfície, com revalidação da origem. Uma prova de exec não qualifica TUI/app; uma cópia da qualificação de outra superfície também é recusada.
- Receipts vinculam o host de nascimento. Formatos legados de exec continuam legíveis, sem permitir reclassificá-los como TUI.
- O diretório efetivo vem do `turn_context` atual; o diretório inicial da sessão é histórico após rebind nativo. O turno do nascimento é revalidado na coleta. Todos os turnos e a metadata de nascimento do filho precisam continuar no worktree esperado.
- `workdir`/`--root` não reconfiguram o chat. Divergência continua `worktree_mismatch`, agora com os diretórios observados e recuperação precisa.

## Validação

118 testes passaram: test_codex_evidence.py, test_codex_proxy.py, test_codex_review.py e test_codex_adapter.py.

Ensaio real nesta sessão `codex-tui/0.163.0`: filho nativo `/root/qualification_1098_native`, contexto isolado solicitado, sem ferramentas ou trabalho de produto. A coleta antes do nascimento recusou `birth_mismatch`. Após o retorno, coleta, verificação, qualificação e proxy retornaram sucesso. Modelo/esforço observados coincidiram com a captura (`gpt-6.1-sol`, `high`). Nenhuma sessão externa foi aberta.

O ensaio usou `/source`, sandbox `danger-full-access`. Não comprova isolamento read-only, interação visual do operador, app/IDE, conclusão do Design ou vínculo efetivo ao worktree do card. App/IDE possuem apenas testes de contrato; faltam ensaios reais.

Prova privada original (sem copiar rollout/transcript):
`/srv/apps/dev/criptofarol/source/.cursor/tmp/codex-bootstrap-1098/d382e438-f456-48ba-b3fa-69ceefbdafc4.evidence.json`

O receipt de qualificação instalado no worktree referencia essa mesma prova original da superfície; não constitui prova de uma etapa do card. A origem íntegra continua obrigatória em todo preflight.

## Procedência e estado

Nucleus: `/srv/apps/dev/covenant-flow-worktrees/card-1098-codex-agentes-nativos`, base `14aa9d6`, branch do mesmo card. Consumidor: `/srv/apps/dev/criptofarol/crypto-worktrees/card-1098-codex-agentes-nativos`, atualizado por fast-forward para `bf7cd245`, preservando OpenSpec e crítica existentes.

Os três arquivos alterados (coletor, testes, documentação) foram copiados byte a byte do nucleus para o worktree consumidor. O manifesto do consumidor foi regenerado para o delta local. O pin-base continua `v1.1.22`; esta é uma alteração local de bootstrap não publicada, não uma nova versão pinada. Distribuição/commit/review/release seguem pendentes; `/source` e a instalação da conta não foram modificados.

## Retomada necessária

1. O operador revisa o diff do adaptador no worktree e registra confiança nele. Não reutilizar automaticamente a aprovação do adaptador anterior:

```bash
cd /srv/apps/dev/criptofarol/crypto-worktrees/card-1098-codex-agentes-nativos
python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record --client codex
```

2. Sair da interface atual e retomar **o mesmo chat** no worktree, pela opção nativa confirmada em `codex resume --help`:

```bash
codex resume 01a14a14-8ad0-78b2-8278-c14aec2b4bf8 --cd /srv/apps/dev/criptofarol/crypto-worktrees/card-1098-codex-agentes-nativos
```

Não executar esse comando como uma sessão externa delegada pelo agente. A retomada é do operador na interface atual. O efeito sobre o `turn_context` ainda deve ser observado; o comando sozinho não comprova o rebind.

3. Na retomada, conferir cwd autoritativo, preflight, captura nova e nascimento nativo antes de trabalhar no Design. O card permanece em Design. O autor precisa atualizar o OpenSpec para o escopo ampliado do issue, seguido da crítica exigida e publicação; os artefatos antigos não foram promovidos a aprovados.

A revisão read-only permanece bloqueada neste turno gravável. A mudança não altera FSM, Guard, permissões nem evidências para transformá-la em aprovação.

## Resumo sanitizado do ensaio

```json
{
  "attempt_id": "d382e438-f456-48ba-b3fa-69ceefbdafc4",
  "parent_thread": "01a14a14-8ad0-78b2-8278-c14aec2b4bf8",
  "child_thread": "01a14a19-71a9-7472-9e32-df3202fb6500",
  "host": "codex-tui",
  "host_version": "0.163.0",
  "driver": "codex/rollout-v1",
  "requested": {
    "model": "gpt-6.1-sol",
    "reasoning_effort": "high"
  },
  "turns": [
    {
      "observed": {
        "model": "gpt-6.1-sol",
        "reasoning_effort": "high"
      },
      "sandbox": "danger-full-access",
      "turn_id": "01a14a19-71d2-7a71-b16f-dd156712d916"
    }
  ],
  "status": "completed",
  "payload_returned": true,
  "qualification": true,
  "integrity_sha256": "19da10f07b0ea025e69f095af0789cd07a01ea11a1b6350c58e19765f740c551",
  "scope": "Driver qualification only in source; not Design, QA, read-only review or proof of worktree rebinding.",
  "collector_sha256": "e448e234f285217aa224a820628e9680018ccd67031a8d3c16a8d2777747a44b"
}
```
