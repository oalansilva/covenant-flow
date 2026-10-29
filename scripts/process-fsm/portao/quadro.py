"""Adaptador GitHub do executor, isolado atrás da interface `Quadro` (design D1, D3, D7).

`GhQuadro` só roda dentro do workflow do repo do executor: lê e move o Status do Project com o token do environment
`portao` (`PORTAO_TOKEN`), comenta na issue com o mesmo token e lê os registros dos runs anteriores do próprio repo do
executor com o `GITHUB_TOKEN` do run. Testes usam um quadro falso; nada aqui roda na VM do agente.

O registro de cada run é o artefato `registro` (o pedido no input do run, o resultado, o digest do T5 e a hora). É dele
que o executor tira o digest do último T5 e o `/cancelar` pendente, nunca de comentário de issue.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import zipfile
from typing import Any, Mapping, Protocol

ARTEFATO = "registro"
ARQUIVO_REGISTRO = "registro.json"
EVENT_TYPE = "portao"
REGISTROS_MAX = 40
PAGINAS = 5  # olha os 500 runs mais recentes do executor


def nome_do_run(card: int | str, evento: str, request_id: str) -> str:
    """`run-name` do workflow; o cliente acha o run pelo `request_id` e o executor acha os runs do card pelo prefixo."""

    return f"portao #{card} {evento} {request_id}"


def prefixo_do_card(card: int | str) -> str:
    return f"portao #{card} "


class QuadroErro(RuntimeError):
    pass


class Quadro(Protocol):
    def status(self, card: int) -> str | None: ...  # None = issue fora do board

    def issue(self, card: int) -> Mapping[str, Any] | None: ...  # {"titulo": ...}; None = issue inexistente

    def mover(self, card: int, para: str) -> None: ...

    def adicionar(self, card: int, para: str) -> None: ...

    def comentar(self, card: int, corpo: str) -> str | None: ...  # URL do comentário

    def registros(self, card: int) -> list[Mapping[str, Any]]: ...


class GhQuadro:
    """Quadro real pelo `gh api`. Configuração vem do overlay do SHA fixado e do ambiente do workflow."""

    def __init__(self, overlay: Mapping[str, Any], *, executor_repo: str, environ: Mapping[str, str] | None = None) -> None:
        from overlay import board_owner_number, board_project_id, repo_owner_name, status_field_id, status_options

        env = os.environ if environ is None else environ
        self.owner, self.repo = repo_owner_name(overlay)
        self.board_owner, self.board_number = board_owner_number(overlay)
        self.project_id = board_project_id(overlay)
        self.field_id = status_field_id(overlay)
        self.options = status_options(overlay)
        self.executor_repo = executor_repo
        self.token_board = env.get("PORTAO_TOKEN", "")
        self.token_runs = env.get("GITHUB_TOKEN", "") or self.token_board
        if not (self.owner and self.repo and self.board_owner and self.board_number and self.project_id and self.field_id):
            raise QuadroErro("overlay sem repo/board/project_id/status_field_id")
        if not self.token_board:
            raise QuadroErro("PORTAO_TOKEN ausente no environment do executor")

    # ------------------------------------------------------------------ gh

    def _gh(self, args: list[str], *, token: str, entrada: bytes | None = None) -> bytes:
        env = dict(os.environ)
        env["GH_TOKEN"] = token
        env.pop("GITHUB_TOKEN", None)
        try:
            proc = subprocess.run(["gh", "api", *args], input=entrada, capture_output=True, check=False, timeout=30, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QuadroErro(f"gh api: {exc}") from exc
        if proc.returncode != 0:
            raise QuadroErro((proc.stderr or proc.stdout or b"gh api falhou").decode("utf-8", "replace").strip()[:500])
        return proc.stdout

    def _json(self, args: list[str], *, token: str | None = None) -> Any:
        saida = self._gh(args, token=token or self.token_board)
        try:
            return json.loads(saida.decode("utf-8") or "null")
        except ValueError as exc:
            raise QuadroErro(f"resposta não é JSON: {exc}") from exc

    def _graphql(self, query: str, **variaveis: Any) -> dict[str, Any]:
        args = ["graphql", "-f", f"query={query}"]
        for nome, valor in variaveis.items():
            args += ["-F" if isinstance(valor, int) else "-f", f"{nome}={valor}"]
        dados = self._json(args)
        if not isinstance(dados, dict) or dados.get("errors"):
            raise QuadroErro(f"GraphQL: {(dados or {}).get('errors') if isinstance(dados, dict) else dados}")
        return dados.get("data") or {}

    def _item(self, card: int) -> tuple[str | None, str | None]:
        query = (
            "query($owner:String!,$repo:String!,$n:Int!){repository(owner:$owner,name:$repo){issue(number:$n){"
            "projectItems(first:20){nodes{id project{number owner{...on User{login}...on Organization{login}}}"
            " fieldValueByName(name:\"Status\"){...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}"
        )
        dados = self._graphql(query, owner=self.owner, repo=self.repo, n=int(card))
        issue = ((dados.get("repository") or {}).get("issue")) or None
        if issue is None:
            raise QuadroErro(f"issue #{card} não existe em {self.owner}/{self.repo}")
        for node in ((issue.get("projectItems") or {}).get("nodes")) or []:
            project = (node or {}).get("project") or {}
            login = (project.get("owner") or {}).get("login")
            if project.get("number") == self.board_number and login in (None, self.board_owner):
                valor = (node.get("fieldValueByName") or {}).get("name")
                return str(node.get("id")), (str(valor) if valor else None)
        return None, None

    def _definir(self, item_id: str, para: str) -> None:
        opcao = self.options.get(para)
        if not opcao:
            raise QuadroErro(f"Status {para!r} sem opção no overlay")
        mutation = (
            "mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,"
            "fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}"
        )
        self._graphql(mutation, p=self.project_id, i=item_id, f=self.field_id, o=opcao)

    # ------------------------------------------------------------------ Quadro

    def status(self, card: int) -> str | None:
        item, valor = self._item(card)
        return valor if item else None

    def issue(self, card: int) -> Mapping[str, Any] | None:
        try:
            dados = self._json([f"repos/{self.owner}/{self.repo}/issues/{int(card)}"])
        except QuadroErro as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                return None
            raise
        if not isinstance(dados, dict) or dados.get("pull_request"):
            return None
        return {"titulo": dados.get("title"), "node_id": dados.get("node_id")}

    def mover(self, card: int, para: str) -> None:
        item, _valor = self._item(card)
        if not item:
            raise QuadroErro(f"#{card} não está no board")
        self._definir(item, para)

    def adicionar(self, card: int, para: str) -> None:
        dados = self.issue(card)
        if not dados or not dados.get("node_id"):
            raise QuadroErro(f"issue #{card} não existe")
        mutation = "mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}"
        criado = self._graphql(mutation, p=self.project_id, c=str(dados["node_id"]))
        item = (((criado.get("addProjectV2ItemById") or {}).get("item")) or {}).get("id")
        if not item:
            raise QuadroErro("addProjectV2ItemById não devolveu o item")
        self._definir(str(item), para)

    def comentar(self, card: int, corpo: str) -> str | None:
        entrada = json.dumps({"body": corpo}).encode("utf-8")
        dados = self._json_input([f"repos/{self.owner}/{self.repo}/issues/{int(card)}/comments", "--method", "POST", "--input", "-"], entrada)
        return str(dados.get("html_url")) if isinstance(dados, dict) and dados.get("html_url") else None

    def _json_input(self, args: list[str], entrada: bytes) -> Any:
        saida = self._gh(args, token=self.token_board, entrada=entrada)
        return json.loads(saida.decode("utf-8") or "null")

    def registros(self, card: int) -> list[Mapping[str, Any]]:
        """Registros dos runs concluídos do card, do mais novo ao mais velho (até `REGISTROS_MAX`, em até `PAGINAS` páginas)."""

        achados: list[Mapping[str, Any]] = []
        prefixo = prefixo_do_card(card)
        for pagina in range(1, PAGINAS + 1):
            runs = self._json([f"repos/{self.executor_repo}/actions/runs?event=repository_dispatch&per_page=100&page={pagina}"], token=self.token_runs)
            lista = (runs or {}).get("workflow_runs") or []
            for run in lista:
                if len(achados) >= REGISTROS_MAX:
                    return achados
                titulo = str(run.get("display_title") or run.get("name") or "")
                if not titulo.startswith(prefixo) or run.get("status") != "completed":
                    continue
                registro = self.registro_do_run(int(run["id"]))
                if registro is not None:
                    achados.append(registro)
            if len(lista) < 100:
                break
        return achados

    def registro_do_run(self, run_id: int) -> Mapping[str, Any] | None:
        artefatos = self._json([f"repos/{self.executor_repo}/actions/runs/{run_id}/artifacts"], token=self.token_runs)
        for artefato in (artefatos or {}).get("artifacts") or []:
            if artefato.get("name") != ARTEFATO or artefato.get("expired"):
                continue
            pacote = self._gh([f"repos/{self.executor_repo}/actions/artifacts/{artefato['id']}/zip"], token=self.token_runs)
            return ler_registro_zip(pacote)
        return None


def ler_registro_zip(pacote: bytes) -> Mapping[str, Any] | None:
    try:
        with zipfile.ZipFile(io.BytesIO(pacote)) as arquivo:
            dados = json.loads(arquivo.read(ARQUIVO_REGISTRO).decode("utf-8"))
    except (KeyError, ValueError, zipfile.BadZipFile):
        return None
    return dados if isinstance(dados, dict) else None
