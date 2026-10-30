"""The DEV test of a card (#1144): plan, lock, report and the `qa_dev_ok` guard of T14.

`plan` and `report` are operator tools the parent runs around the `qa-dev` children; T14 only reads
what they leave. Everything stays out of git, under `~/.local/state/covenant-flow/qa-dev/`. The issue
is the source of truth of the verdict, so another session can resume from it. No model takes part in
the verdict: it is computed here, from the block files. Tests inject fakes; no GitHub in pytest.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overlay import qa_dev_settings, repo_slug, try_load_overlay  # noqa: E402
from t14 import _http_health, _run  # noqa: E402

REPO_ROOT = ROOT.parents[1]
STATE_ENV = "COVENANT_QA_DEV_STATE"
PASS, FAIL, NAO_TESTADO = "PASS", "FAIL", "NAO_TESTADO"
NADA_PARA_TESTAR, INCONCLUSIVO = "NADA_PARA_TESTAR", "INCONCLUSIVO"
RESULTADOS = (PASS, FAIL, NAO_TESTADO)
VEREDITOS_QUE_MOVEM = frozenset({PASS, NAO_TESTADO, NADA_PARA_TESTAR})
MARCADOR = re.compile(
    r"^<!-- covenant-flow:qa-dev veredito=(PASS|FAIL|NAO_TESTADO|NADA_PARA_TESTAR|INCONCLUSIVO)"
    r" sha=([0-9a-fA-F]{7,40}) run=([A-Za-z0-9._-]+) -->\s*$",
    re.MULTILINE,
)
RUN_ID = re.compile(r"[A-Za-z0-9._-]+\Z")
CODIGO = re.compile(r"[a-z][a-z0-9_]*\Z")
GRUPO_POR_BLOCO = 3
CHAMADAS_POR_BLOCO = 60
TENTATIVAS_SAUDE = 3
ESPERA_SAUDE_S = 150  # 3 attempts inside 5 minutes (D9)
FOLGA_TRAVA_MIN = 15
LIMITE_COMENTARIO = 60000  # GitHub refuses over 65536 characters
RESUMO_COMPACTO = 280
FALTA_POR_CODIGO = {
    "senha_recusada": "o login no DEV recusou a senha: atualize a senha no cofre e rode o teste de novo.",
    "conta_bloqueada": "o login no DEV devolveu 403: a conta está suspensa, banida ou com senha temporária vencida.",
    "cofre_indisponivel": "o helper de sessão não conseguiu ler o cofre.",
    "segredo_ausente": "o segredo do login no DEV não está no cofre.",
    "navegador": "o navegador do teste não abriu: rode `setup-dev.sh --check` e corrija o que ele apontar.",
    "cliente_sem_navegador": "este cliente não tem o navegador do teste: abra a sessão do card no Claude Code.",
}


class QaDevError(RuntimeError):
    """A visible stop of `plan` or `report`, with no partial effect on the issue."""


@dataclass
class Io:
    """Side effects, injectable: tests never reach GitHub, systemd or the network."""

    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    health_get: Callable[[str], bool] = _http_health
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    status_provider: Callable[[str], str | None] | None = None


@dataclass(frozen=True)
class Config:
    repo: str
    dev_url: str
    dev_source: Path | None
    servicos: tuple[str, ...]
    settings: Mapping[str, Any]
    root: Path
    state: Path

    @property
    def validade_trava_s(self) -> int:
        return (int(self.settings["teto_total_min"]) + FOLGA_TRAVA_MIN) * 60


def state_dir() -> Path:
    return Path(os.environ.get(STATE_ENV) or (Path.home() / ".local" / "state" / "covenant-flow" / "qa-dev"))


def _service_name(name: str) -> str:
    text = str(name).strip()
    return text if text.endswith(".service") else f"{text}.service"


def continuous_services(env: Mapping[str, Any]) -> tuple[str, ...]:
    """`services` minus `oneshot_services`: a oneshot unit is inactive between runs by design (D9)."""
    oneshot = {_service_name(item) for item in (env.get("oneshot_services") or [])}
    return tuple(name for name in (_service_name(item) for item in (env.get("services") or [])) if name not in oneshot)


def config_from_overlay(overlay: Mapping[str, Any], *, root: Path = REPO_ROOT, state: Path | None = None) -> Config:
    env = (overlay.get("environments") or {}).get("dev") or {}
    source = str(env.get("source") or "").strip()
    return Config(
        repo=repo_slug(overlay),
        dev_url=str(env.get("url") or "").rstrip("/"),
        dev_source=Path(source) if source else None,
        servicos=continuous_services(env),
        settings=qa_dev_settings(overlay),
        root=Path(root),
        state=Path(state) if state is not None else state_dir(),
    )


def load_config(root: Path = REPO_ROOT, state: Path | None = None) -> Config:
    overlay = try_load_overlay(root)
    if not overlay:
        raise QaDevError("overlay ausente ou inválido")
    return config_from_overlay(overlay, root=root, state=state)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_private(path: Path, text: str) -> None:
    """Atomic write, 0600: nothing under the state dir is meant for another account."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)


def _write_json(path: Path, data: Any) -> None:
    _write_private(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


@contextmanager
def _exclusive(state: Path) -> Iterator[None]:
    """Serializes read-decide-write of the shared state: two T14 cannot both take the lock."""
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(state / ".exclusivo", "w", encoding="utf-8") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def pegar_trava(state: Path, card: str, run: str, validade_s: int, agora: float) -> dict[str, Any] | None:
    """Take or renew the lock. Returns None when taken, or the other card's live lock."""
    path = state / "lock"
    with _exclusive(state):
        atual = _read_json(path)
        if isinstance(atual, dict) and str(atual.get("card")) != str(card) and float(atual.get("vence") or 0) > agora:
            return atual
        _write_json(path, {"card": str(card), "run": run, "inicio": agora, "vence": agora + validade_s})
    return None


def soltar_trava(state: Path, card: str) -> bool:
    """Release this card's lock; another card's lock stays."""
    path = state / "lock"
    with _exclusive(state):
        atual = _read_json(path)
        if isinstance(atual, dict) and str(atual.get("card")) != str(card):
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def listar_criterios(body: str) -> list[dict[str, str]]:
    """C1…Cn from the top-level items of `## Entra`, so no criterion is lost to a model's reading."""
    itens: list[str] = []
    dentro = False
    for linha in (body or "").splitlines():
        if re.match(r"^##\s+Entra\b", linha):
            dentro = True
            continue
        if not dentro:
            continue
        if re.match(r"^#{1,2}\s", linha):
            break
        item = re.match(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$", linha)
        if item:
            itens.append(item.group(1).strip())
        elif itens and linha.strip() and linha[0].isspace():
            itens[-1] = f"{itens[-1]} {linha.strip()}"
    return [{"id": f"C{numero}", "texto": texto} for numero, texto in enumerate(itens, 1)]


def casa_caminho(caminho: str, padrao: str) -> bool:
    if padrao.endswith("/**"):
        return caminho.startswith(padrao[:-2])
    return fnmatch.fnmatchcase(caminho, padrao)


def so_sem_produto(arquivos: Iterable[str] | None, padroes: Iterable[str]) -> bool:
    """NADA_PARA_TESTAR only when every file matches; no list (failed listing) never classifies."""
    lista = list(arquivos or [])
    globs = list(padroes)
    return bool(lista) and bool(globs) and all(any(casa_caminho(item, padrao) for padrao in globs) for item in lista)


def arquivos_do_pr(cfg: Config, pr: str | None, io: Io) -> list[str] | None:
    if not pr:
        return None
    try:
        proc = _run(
            ["gh", "api", f"repos/{cfg.repo}/pulls/{pr}/files", "--paginate", "--jq", ".[] | .filename, (.previous_filename // empty)"],
            timeout=30,
            runner=io.run,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    arquivos = [linha.strip() for linha in (proc.stdout or "").splitlines() if linha.strip()]
    return arquivos if proc.returncode == 0 and arquivos else None


def _hora(io: Io) -> str:
    return datetime.fromtimestamp(io.now()).strftime("%H:%M")


def checar_dev(cfg: Config, io: Io) -> list[str]:
    """Reasons the DEV is not usable: health over 3 attempts, then each continuous service."""
    url = f"{cfg.dev_url}/api/health"
    for tentativa in range(TENTATIVAS_SAUDE):
        if io.health_get(url):
            break
        if tentativa + 1 < TENTATIVAS_SAUDE:
            io.sleep(ESPERA_SAUDE_S)
    else:
        return [f"DEV fora do ar às {_hora(io)}"]
    parados: list[str] = []
    for servico in cfg.servicos:
        try:
            ativo = _run(["systemctl", "is-active", servico], timeout=15, runner=io.run).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ativo = False
        if not ativo:
            parados.append(f"serviço {servico} parado às {_hora(io)}")
    return parados


def _sha_dev(cfg: Config, io: Io) -> str:
    if cfg.dev_source is None:
        return ""
    try:
        proc = _run(["git", "-C", str(cfg.dev_source), "rev-parse", "HEAD"], timeout=20, runner=io.run)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def prototipo(cfg: Config, card: str) -> str | list[dict[str, str]]:
    """The approved prototype, already in `develop` on the DEV source, or `N/A`."""
    if cfg.dev_source is None:
        return "N/A"
    pastas = sorted(item for item in (cfg.dev_source / "frontend" / "public" / "prototypes").glob(f"card-{card}-*") if item.is_dir())
    achados: list[dict[str, str]] = []
    for pasta in pastas:
        paginas = [pasta / "index.html"] if (pasta / "index.html").is_file() else sorted(pasta.glob("*.html"))
        pagina = paginas[0].name if paginas else ""
        achados.append({"pasta": pasta.name, "url": f"{cfg.dev_url}/prototypes/{pasta.name}/{pagina}"})
    return achados or "N/A"


def _argv(comando: str, root: Path) -> list[str]:
    """Consumer commands from the overlay, relative to the tree of this engine."""
    partes = shlex.split(comando or "")
    if not partes:
        return []
    alvo = Path(partes[0]) if Path(partes[0]).is_absolute() else root / partes[0]
    if alvo.suffix == ".py":
        return [sys.executable, str(alvo), *partes[1:]]
    return [str(alvo) if alvo.exists() else partes[0], *partes[1:]]


def abrir_sessao(cfg: Config, io: Io) -> tuple[str | None, str | None]:
    """(`sim`|`nao`, None) or (None, error code). The helper prints no value, only the code."""
    argv = _argv(str(cfg.settings.get("session_cmd") or ""), cfg.root)
    if not argv:
        return None, "session_cmd_ausente"
    try:
        proc = _run(argv, timeout=60, runner=io.run)
    except (OSError, subprocess.TimeoutExpired):
        return None, "sessao_falhou"
    saida = (proc.stdout or "").strip()
    ok = re.fullmatch(r"sessao_ok admin=(sim|nao)", saida)
    if ok and proc.returncode == 0:
        return ok.group(1), None
    codigo = saida.split()[0] if saida.split() else ""
    return None, codigo if CODIGO.match(codigo) else "sessao_falhou"


def _comentar(cfg: Config, card: str, corpo: Path, io: Io) -> None:
    proc = _run(["gh", "issue", "comment", str(card), "--repo", cfg.repo, "--body-file", str(corpo)], timeout=60, runner=io.run)
    if proc.returncode != 0:
        raise QaDevError(f"comentário não postado: {(proc.stderr or proc.stdout or 'gh falhou').strip()}")


def soltar(cfg: Config, card: str, io: Io, *, motivo: str | None = None) -> dict[str, Any]:
    """Tool failure (D9): no report, the lock goes, and the issue says what is missing."""
    solta = soltar_trava(cfg.state, card)
    if not (cfg.state / "lock").exists():  # a lock still there is another card's, and so is the session
        (cfg.state / "storage-state.json").unlink(missing_ok=True)
    resposta: dict[str, Any] = {"status": "solta" if solta else "sem_trava", "card": card}
    if motivo:
        texto = FALTA_POR_CODIGO.get(motivo, f"falha de ferramenta `{motivo}`.")
        corpo = cfg.state / str(card) / "falha-ferramenta.md"
        _write_private(corpo, f"Teste no DEV parado, sem relatório: {texto}\n\nO card fica em `QA`.\n")
        _comentar(cfg, card, corpo, io)
        resposta["comentario"] = True
    return resposta


def _caminho_fail_abertos(cfg: Config) -> Path:
    return cfg.state / "fail-abertos.json"


def fail_abertos(cfg: Config, card: str, io: Io) -> list[dict[str, Any]]:
    """Open FAIL of the other cards. A canceled card leaves the record; an unread Status keeps it."""
    provedor = io.status_provider
    if provedor is None:
        from guard import github_status_provider as provedor  # noqa: PLC0415
    caminho = _caminho_fail_abertos(cfg)
    with _exclusive(cfg.state):
        registro = _read_json(caminho)
        registro = registro if isinstance(registro, dict) else {}
        for numero in list(registro):
            if numero == str(card):
                continue
            try:
                vivo = provedor(numero)
            except Exception:  # noqa: BLE001 - any read failure keeps the entry visible
                vivo = None
            if vivo == "Cancelado":
                del registro[numero]
        _write_json(caminho, registro)
    return [{"card": numero, **dados} for numero, dados in sorted(registro.items()) if numero != str(card)]


def _atualizar_fail_abertos(cfg: Config, card: str, run: str, criterios: list[dict[str, Any]], arquivos: list[str]) -> None:
    caminho = _caminho_fail_abertos(cfg)
    falhos = [{"id": item["id"], "texto": item["texto"]} for item in criterios if item["resultado"] == FAIL]
    with _exclusive(cfg.state):
        registro = _read_json(caminho)
        registro = registro if isinstance(registro, dict) else {}
        if falhos:
            registro[str(card)] = {"run": run, "criterios": falhos, "arquivos": arquivos}
        else:
            registro.pop(str(card), None)
        _write_json(caminho, registro)


def pasta_do_run(cfg: Config, card: str, run: str) -> Path:
    if not RUN_ID.match(run):
        raise QaDevError(f"run inválido: {run!r}")
    return cfg.state / str(card) / run


def _novo_run(io: Io) -> str:
    return datetime.fromtimestamp(io.now(), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _issue_body(cfg: Config, card: str, io: Io) -> str:
    proc = _run(["gh", "api", f"repos/{cfg.repo}/issues/{card}", "--jq", ".body"], timeout=20, runner=io.run)
    if proc.returncode != 0:
        raise QaDevError(f"issue #{card} ilegível: {(proc.stderr or 'gh falhou').strip()}")
    return proc.stdout or ""


def _pr_do_recibo(cfg: Config, card: str) -> str | None:
    recibo = _read_json(cfg.state / "recibos" / f"{card}.json")
    return str(recibo["pr"]) if isinstance(recibo, dict) and recibo.get("pr") else None


def _reteste(cfg: Config, card: str, de: str, leitura: str | None, tocados: list[str]) -> dict[str, Any]:
    anterior = _read_json(pasta_do_run(cfg, card, de) / "resultado.json")
    if not isinstance(anterior, dict) or not isinstance(anterior.get("criterios"), list):
        raise QaDevError(f"run {de} sem resultado.json: não há o que retestar")
    alvo = [item["id"] for item in anterior["criterios"] if item.get("resultado") == FAIL]
    if not leitura:  # a contested FAIL reruns only the failed criteria; a fix adds what its diff touched
        alvo += [item for item in tocados if item not in alvo]
    return {"de": de, "leitura": leitura, "criterios": alvo, "anteriores": anterior["criterios"]}


def plan(
    cfg: Config,
    card: str,
    io: Io,
    *,
    pr: str | None = None,
    reteste_de: str | None = None,
    leitura: str | None = None,
    tocados: Iterable[str] = (),
) -> dict[str, Any]:
    """Take the lock, list the criteria and decide what the run is, before any login or model."""
    run = _novo_run(io)
    pasta = pasta_do_run(cfg, card, run)
    ocupante = pegar_trava(cfg.state, card, run, cfg.validade_trava_s, io.now())
    if ocupante is not None:
        return {"status": "qa_dev_ocupado", "card": card, "trava": ocupante}
    try:
        reteste = _reteste(cfg, card, reteste_de, leitura, list(tocados)) if reteste_de else None
        criterios = listar_criterios(_issue_body(cfg, card, io))
        arquivos = arquivos_do_pr(cfg, pr or _pr_do_recibo(cfg, card), io)
        sha = _sha_dev(cfg, io)
        if not sha:
            raise QaDevError("SHA do DEV ilegível")
    except (QaDevError, OSError, subprocess.TimeoutExpired):
        soltar_trava(cfg.state, card)
        raise
    plano: dict[str, Any] = {
        "status": "pronto",
        "card": card,
        "run": run,
        "pasta": str(pasta),
        "sha": sha,
        "url": cfg.dev_url,
        "criterios": criterios,
        "criterios_a_testar": reteste["criterios"] if reteste else [item["id"] for item in criterios],
        "arquivos": arquivos or [],
        "prototipo": prototipo(cfg, card),
        "admin": None,
        "fail_abertos": [],
        "impedimentos": [],
        "reteste": reteste,
        "espera_max_min": cfg.settings["espera_max_min"],
        "teto_total_min": cfg.settings["teto_total_min"],
        "telas_regressao": list(cfg.settings["telas_regressao"]),
        "bloco_max_criterios": GRUPO_POR_BLOCO,
        "bloco_max_chamadas": CHAMADAS_POR_BLOCO,
    }
    if reteste is None and so_sem_produto(arquivos, cfg.settings["caminhos_sem_produto"]):
        plano.update(status="nada_para_testar", telas_regressao=[], criterios_a_testar=[])
    else:
        plano["impedimentos"] = checar_dev(cfg, io)
        if plano["impedimentos"]:
            plano["status"] = "inconclusivo"
        else:
            admin, codigo = abrir_sessao(cfg, io)
            if codigo:
                soltar(cfg, card, io, motivo=codigo)
                return {"status": "falha_ferramenta", "card": card, "codigo": codigo}
            plano["admin"] = admin
            plano["fail_abertos"] = fail_abertos(cfg, card, io)
    (pasta / "evidencia").mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_json(pasta / "plano.json", plano)
    return plano


def _normalizar(resultado: Any) -> str:
    texto = str(resultado or "").strip().upper().replace("Ã", "A").replace(" ", "_")
    return texto if texto in RESULTADOS else ""


def _ler_blocos(pasta: Path) -> list[dict[str, Any]]:
    def ordem(caminho: Path) -> tuple[int, str]:
        numero = re.search(r"(\d+)", caminho.stem)
        return (int(numero.group(1)) if numero else 10**6, caminho.stem)

    blocos: list[dict[str, Any]] = []
    for caminho in sorted(pasta.glob("bloco-*.json"), key=ordem):
        dados = _read_json(caminho)
        if not isinstance(dados, dict):
            raise QaDevError(f"bloco inválido: {caminho}")
        blocos.append(dados)
    return blocos


def juntar(plano: Mapping[str, Any], blocos: list[dict[str, Any]], impedimentos: list[str]) -> list[dict[str, Any]]:
    """One line per criterion. The last block wins: a repeated block replaces the one it repeats."""
    conhecidos = {item["id"]: item["texto"] for item in plano.get("criterios") or []}
    achados: dict[str, dict[str, Any]] = {}
    for bloco in blocos:
        for item in bloco.get("criterios") or []:
            ident = str(item.get("id") or "")
            if ident not in conhecidos:
                raise QaDevError(f"critério fora do plano: {ident!r}")
            resultado = _normalizar(item.get("resultado"))
            if not resultado:
                raise QaDevError(f"{ident}: resultado inválido {item.get('resultado')!r}")
            evidencias = [str(nome) for nome in (item.get("evidencias") or [])]
            if resultado == FAIL and not evidencias:
                raise QaDevError(f"{ident}: FAIL sem evidência")
            achados[ident] = {"resultado": resultado, "motivo": str(item.get("motivo") or ""), "texto_resultado": str(item.get("texto") or ""), "evidencias": evidencias}
    reteste = plano.get("reteste") or {}
    herdados = {item["id"]: item for item in reteste.get("anteriores") or [] if item["id"] not in (reteste.get("criterios") or [])}
    motivo_vazio = impedimentos[0] if impedimentos else "sem bloco"
    linhas: list[dict[str, Any]] = []
    for ident, texto in conhecidos.items():
        linha: dict[str, Any] = {"id": ident, "texto": texto, "run_origem": None}
        if ident in achados:
            linha.update(achados[ident])
            if linha["resultado"] == NAO_TESTADO and not linha["motivo"]:
                linha["motivo"] = "sem motivo no bloco"
        elif ident in herdados:
            antigo = herdados[ident]
            linha.update(
                resultado=antigo.get("resultado"),
                motivo=antigo.get("motivo") or "",
                texto_resultado=antigo.get("texto_resultado") or "",
                evidencias=[],
                run_origem=antigo.get("run_origem") or reteste.get("de"),
            )
        else:
            linha.update(resultado=NAO_TESTADO, motivo=motivo_vazio, texto_resultado="", evidencias=[])
        linhas.append(linha)
    return linhas


def veredito(criterios: list[Mapping[str, Any]], *, nada: bool, ambiente_falhou: bool) -> str:
    """D5, in this order."""
    resultados = [item["resultado"] for item in criterios]
    if FAIL in resultados:
        return FAIL
    if nada:
        return NADA_PARA_TESTAR
    if PASS not in resultados or ambiente_falhou:
        return INCONCLUSIVO
    return PASS if all(item == PASS for item in resultados) else NAO_TESTADO


def _uma_linha(texto: Any, limite: int | None = None) -> str:
    """Report text goes on one line and cannot forge a marker or an HTML comment."""
    limpo = " ".join(str(texto or "").split()).replace("<!--", "&lt;!--")
    if limite is not None and len(limpo) > limite:
        return limpo[: limite - 1].rstrip() + "…"
    return limpo


def _link(nome: str, publicados: Mapping[str, str]) -> str:
    base = Path(nome).name
    return f"[{base}]({publicados[base]})" if base in publicados else f"`{base}`"


def _rotulo(resultado: str) -> str:
    return "NÃO TESTADO" if resultado == NAO_TESTADO else resultado


def _render_criterio(item: Mapping[str, Any], publicados: Mapping[str, str], limite: int | None) -> list[str]:
    rotulo = _rotulo(str(item["resultado"]))
    if item.get("run_origem"):
        rotulo = f"{rotulo} no run `{item['run_origem']}`"
    linhas = [f"- **{item['id']} {rotulo}:** {_uma_linha(item['texto'], limite)}"]
    if item.get("texto_resultado"):
        linhas.append(f"  - {_uma_linha(item['texto_resultado'], limite)}")
    if item.get("motivo"):
        linhas.append(f"  - Motivo: {_uma_linha(item['motivo'], limite)}")
    if item.get("evidencias"):
        linhas.append("  - Evidência: " + ", ".join(_link(nome, publicados) for nome in item["evidencias"]))
    return linhas


def _render_achados(achados: list[Mapping[str, Any]], publicados: Mapping[str, str], limite: int | None) -> list[str]:
    linhas: list[str] = []
    for achado in achados:
        linha = f"- {_uma_linha(achado.get('texto'), limite)}"
        if achado.get("evidencias"):
            linha += " (" + ", ".join(_link(str(nome), publicados) for nome in achado["evidencias"]) + ")"
        linhas.append(linha)
    return linhas


def render(
    plano: Mapping[str, Any],
    criterios: list[Mapping[str, Any]],
    blocos: list[Mapping[str, Any]],
    impedimentos: list[str],
    resultado: str,
    evidencia: Mapping[str, Any],
    runtime: str,
    *,
    limite: int | None = None,
) -> str:
    """The public comment. `passagem` and `passos` never reach it, whatever the size."""
    run, sha = str(plano["run"]), str(plano["sha"])
    publicados: Mapping[str, str] = evidencia.get("arquivos") or {}
    saida = [f"## Teste no DEV: {_rotulo(resultado)}", "", f"Run `{run}`, SHA testado `{sha}`."]
    reteste = plano.get("reteste") or {}
    if reteste.get("leitura"):
        saida += ["", f"Reteste de `{reteste['de']}` por contestação do Alan. Leitura usada: {_uma_linha(reteste['leitura'], limite)}"]
    elif reteste:
        saida += ["", f"Reteste do run `{reteste['de']}`."]
    if impedimentos:
        saida += ["", "Ambiente: " + "; ".join(_uma_linha(item) for item in impedimentos) + "."]
    if resultado == NADA_PARA_TESTAR:
        examinado = [_uma_linha(bloco["nada_para_testar"], limite) for bloco in blocos if bloco.get("nada_para_testar")]
        saida += ["", "Nada para testar no DEV."]
        if examinado:
            saida += ["", "Examinado: " + " ".join(examinado)]
        elif plano.get("arquivos"):
            saida += ["", "Arquivos do PR: " + ", ".join(f"`{nome}`" for nome in plano["arquivos"])]
    else:
        saida += ["", "### Critérios", ""]
        for item in criterios:
            saida += _render_criterio(item, publicados, limite)
    achados = [achado for bloco in blocos for achado in (bloco.get("achados_passagem") or [])]
    if achados:
        saida += ["", "### Achados fora dos critérios", "", "Não entram no veredito.", ""] + _render_achados(achados, publicados, limite)
    regressao = [tela for bloco in blocos for tela in (bloco.get("regressao") or [])]
    if regressao:
        saida += ["", "### Volta rápida", "", "Não entra no veredito.", ""]
        for tela in regressao:
            resultado_tela = _rotulo(_normalizar(tela.get("resultado")) or str(tela.get("resultado") or ""))
            linha = f"- `{_uma_linha(tela.get('tela'))}` {resultado_tela}: {_uma_linha(tela.get('texto') or tela.get('motivo'), limite)}"
            if tela.get("evidencias"):
                linha += " (" + ", ".join(_link(str(nome), publicados) for nome in tela["evidencias"]) + ")"
            saida.append(linha)
    saida += ["", "### Evidência", ""]
    if evidencia.get("ok"):
        saida.append(f"- [Pasta do run]({evidencia.get('pasta')}), aberta só para a conta do Alan.")
        videos = [nome for nome in publicados if nome.lower().endswith((".webm", ".mp4"))]
        saida += [f"- Vídeo: {_link(nome, publicados)}" for nome in sorted(videos)]
    elif evidencia.get("vazia"):
        saida.append("- Sem prints nem vídeo neste run.")
    else:
        saida.append(f"- A evidência ficou no servidor, em `{Path(str(plano['pasta'])) / 'evidencia'}`: {_uma_linha(evidencia.get('motivo'))}.")
    if resultado == FAIL:
        saida += ["", "O card fica em `QA` até o Alan responder: defeito confirmado leva à T13; leitura contestada leva a reteste sem diff."]
    if resultado == INCONCLUSIVO:
        saida += [
            "",
            "### Saídas",
            "",
            "O card fica em `QA` até o Alan escolher uma:",
            "",
            "1. **Testar de novo:** consertar o ambiente ou pedir novo teste, sem diff.",
            "2. **Devolver:** se o card derrubou o DEV ou o worker, T13.",
            f"3. **Liberar:** o próprio Alan comenta neste issue a linha exata `/qa-dev-liberar {run}`. Nenhum agente posta essa linha.",
        ]
    saida += ["", f"Runtime observado: {_uma_linha(runtime) or 'não informado'}.", "", f"<!-- covenant-flow:qa-dev veredito={resultado} sha={sha} run={run} -->", ""]
    return "\n".join(saida)


def publicar_evidencia(cfg: Config, card: str, run: str, pasta: Path, io: Io) -> dict[str, Any]:
    """Failure here never blocks the report (D7). A success is kept so a rerun does not upload twice."""
    cache = pasta / "evidencia.json"
    guardado = _read_json(cache)
    if isinstance(guardado, dict) and guardado.get("ok"):
        return guardado
    origem = pasta / "evidencia"
    if not origem.is_dir() or not any(item.is_file() for item in origem.iterdir()):
        return {"ok": False, "vazia": True}
    argv = _argv(str(cfg.settings.get("evidence_cmd") or ""), cfg.root)
    if not argv:
        return {"ok": False, "motivo": "evidence_cmd ausente no overlay"}
    try:
        proc = _run([*argv, "--card", str(card), "--run", run, "--dir", str(origem)], timeout=900, runner=io.run)
        dados = json.loads(proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"ok": False, "motivo": f"envio falhou ({type(exc).__name__})"}
    if not isinstance(dados, dict):
        return {"ok": False, "motivo": "resposta inválida do envio"}
    if dados.get("ok"):
        _write_json(cache, dados)
    return dados


def varrer_publico(cfg: Config, arquivo: Path, io: Io) -> tuple[bool, str]:
    """Fail-closed: only an explicit `ausente` lets the text out."""
    argv = _argv(str(cfg.settings.get("scan_cmd") or ""), cfg.root)
    if not argv:
        return False, "scan_cmd ausente no overlay"
    try:
        proc = _run([*argv, "--publico", str(arquivo)], timeout=120, runner=io.run)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"varredura falhou ({type(exc).__name__})"
    saida = (proc.stdout or "").strip()
    limpo = proc.returncode == 0 and "ausente" in saida and "PRESENTE" not in saida
    return limpo, saida or "varredura sem saída"


def report(cfg: Config, card: str, run: str, io: Io, *, runtime: str = "") -> dict[str, Any]:
    """Join the blocks and post. A refused scan posts nothing and keeps the lock: fix the field, run it again."""
    pasta = pasta_do_run(cfg, card, run)
    plano = _read_json(pasta / "plano.json")
    if not isinstance(plano, dict):
        raise QaDevError(f"run {run} sem plano.json")
    blocos = _ler_blocos(pasta)
    impedimentos = list(plano.get("impedimentos") or [])
    for bloco in blocos:
        impedimentos += [str(item) for item in (bloco.get("impedimentos") or [])]
    nada_pelo_plano = plano.get("status") == "nada_para_testar"
    if not nada_pelo_plano:
        impedimentos += checar_dev(cfg, io)
    criterios = juntar(plano, blocos, impedimentos)
    com_criterio = [bloco for bloco in blocos if bloco.get("criterios")]
    nada_pelo_filho = bool(blocos) and not com_criterio and any(bloco.get("nada_para_testar") for bloco in blocos)
    resultado = veredito(criterios, nada=nada_pelo_plano or nada_pelo_filho, ambiente_falhou=bool(impedimentos))
    inteiro = render(plano, criterios, blocos, impedimentos, resultado, {"vazia": True}, runtime)
    if len(inteiro) > LIMITE_COMENTARIO:
        # The Drive copy keeps the whole text; the public comment carries the summary of each criterion.
        _write_private(pasta / "evidencia" / "relatorio-integral.md", inteiro)
    evidencia = publicar_evidencia(cfg, card, run, pasta, io)
    corpo = render(plano, criterios, blocos, impedimentos, resultado, evidencia, runtime)
    if len(corpo) > LIMITE_COMENTARIO:
        corpo = render(plano, criterios, blocos, impedimentos, resultado, evidencia, runtime, limite=RESUMO_COMPACTO)
    arquivo = pasta / "relatorio.md"
    _write_private(arquivo, corpo)
    limpo, saida = varrer_publico(cfg, arquivo, io)
    if not limpo:
        return {"status": "varredura_recusou", "card": card, "run": run, "arquivo": str(arquivo), "saida": saida}
    _comentar(cfg, card, arquivo, io)
    _write_json(pasta / "resultado.json", {"card": card, "run": run, "sha": plano["sha"], "veredito": resultado, "criterios": criterios})
    _atualizar_fail_abertos(cfg, card, run, criterios, list(plano.get("arquivos") or []))
    (cfg.state / "storage-state.json").unlink(missing_ok=True)
    soltar_trava(cfg.state, card)
    return {"status": "postado", "card": card, "run": run, "veredito": resultado, "sha": plano["sha"]}


@dataclass(frozen=True)
class Medida:
    """What `integrar_develop` read from the issue. `reason` is the reject token when not ok."""

    ok: bool
    reason: str | None = None
    veredito: str | None = None
    run: str | None = None
    liberado: bool = False
    message: str | None = None

    def nota(self) -> str:
        if self.liberado:
            return f"Teste no DEV: INCONCLUSIVO no run {self.run}, liberado pelo Alan com /qa-dev-liberar {self.run}."
        return f"Teste no DEV: {self.veredito} no run {self.run}."


def medir_guarda(
    comentarios: Iterable[Mapping[str, Any]],
    *,
    autor: str,
    commit: str,
    ancestral: Callable[[str, str], bool],
) -> Medida:
    """`qa_dev_ok`. Only `autor` counts: the repo is public and anyone can comment an invisible marker."""
    pendente = "rode o teste no DEV (skill qa-dev), poste o relatório e chame T14 de novo"
    if not autor:
        return Medida(False, "qa_dev_pendente", message=f"overlay sem qa_dev.autor_relatorio: nenhum relatório vale; {pendente}")
    meus = [item for item in comentarios if str(item.get("login") or "").lower() == autor.lower()]
    posicao, marcado = None, None
    for indice, item in enumerate(meus):
        marcas = MARCADOR.findall(str(item.get("body") or ""))
        if marcas:
            posicao, marcado = indice, marcas[-1]
    if marcado is None:
        return Medida(False, "qa_dev_pendente", message=f"sem relatório do teste no DEV: {pendente}")
    resultado, sha, run = marcado
    # The SHA comes first: a FAIL of older code says nothing about the integrated code.
    if not commit or not ancestral(commit, sha):
        return Medida(False, "qa_dev_pendente", veredito=resultado, run=run, message=f"o último relatório é de código anterior ao integrado: {pendente}")
    if resultado == FAIL:
        return Medida(False, "qa_dev_fail", veredito=resultado, run=run, message=f"critério em FAIL no run {run}: pare e pergunte ao Alan; T13 só se ele confirmar o defeito, reteste sem diff se discordar")
    if resultado == INCONCLUSIVO:
        linha = f"/qa-dev-liberar {run}"
        if any(str(item.get("body") or "").strip() == linha for item in meus[posicao + 1 :]):
            return Medida(True, veredito=resultado, run=run, liberado=True)
        return Medida(False, "qa_dev_inconclusivo", veredito=resultado, run=run, message=f"run {run} INCONCLUSIVO: pare e mostre ao Alan as saídas do relatório")
    return Medida(resultado in VEREDITOS_QUE_MOVEM, None, veredito=resultado, run=run)


def comentarios_do_issue(cfg: Config, card: str, io: Io) -> list[dict[str, str]]:
    proc = _run(
        ["gh", "api", f"repos/{cfg.repo}/issues/{card}/comments", "--paginate", "--jq", ".[] | {login: .user.login, body: .body}"],
        timeout=30,
        runner=io.run,
    )
    if proc.returncode != 0:
        raise QaDevError("comentários do issue ilegíveis")
    return [json.loads(linha) for linha in (proc.stdout or "").splitlines() if linha.strip()]


@dataclass
class Gate:
    """What `process_event` needs with `qa_dev` on. Absent (None) means the T14 of today."""

    cfg: Config
    io: Io = field(default_factory=Io)
    comentarios: Callable[[str], Iterable[Mapping[str, Any]]] | None = None
    ancestral: Callable[[str, str], bool] | None = None

    @property
    def closeout_dir(self) -> Path:
        """The receipt outlives the worktree: another session of the card resumes at phase 2."""
        return self.cfg.state / "recibos"

    def pegar(self, card: str) -> dict[str, Any] | None:
        return pegar_trava(self.cfg.state, card, "t14-fase-1", self.cfg.validade_trava_s, self.io.now())

    def soltar(self, card: str, *, motivo: str | None = None) -> None:
        soltar(self.cfg, card, self.io, motivo=motivo)

    def _ancestral(self, commit: str, sha: str) -> bool:
        if self.ancestral is not None:
            return self.ancestral(commit, sha)
        if self.cfg.dev_source is None:
            return False
        try:
            proc = _run(["git", "-C", str(self.cfg.dev_source), "merge-base", "--is-ancestor", commit, sha], timeout=20, runner=self.io.run)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def medir(self, card: str, commit: str) -> Medida:
        try:
            comentarios = list(self.comentarios(card) if self.comentarios is not None else comentarios_do_issue(self.cfg, card, self.io))
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return Medida(False, "qa_dev_pendente", message=f"comentários do card ilegíveis ({exc}): chame T14 de novo")
        return medir_guarda(comentarios, autor=str(self.cfg.settings.get("autor_relatorio") or ""), commit=commit, ancestral=self._ancestral)


def live_gate(root: Path = REPO_ROOT) -> Gate | None:
    """The gate of this tree, or None with `qa_dev` absent or off: the overlay of `REPO_ROOT` decides, as in `t14.py`."""
    overlay = try_load_overlay(root)
    if not overlay or not qa_dev_settings(overlay).get("enabled"):
        return None
    return Gate(config_from_overlay(overlay, root=root))


def _card(texto: str) -> str:
    return str(int(str(texto).lstrip("#")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa_dev")
    comandos = parser.add_subparsers(dest="comando", required=True)
    plano = comandos.add_parser("plan", help="pega a trava e monta o plano do run")
    plano.add_argument("--card", required=True, type=_card)
    plano.add_argument("--pr", help="PR do card; sem T14 não há recibo (piloto)")
    plano.add_argument("--reteste-de", help="run anterior: refaz os critérios em FAIL")
    plano.add_argument("--leitura", help="leitura do Alan num FAIL contestado")
    plano.add_argument("--criterios", default="", help="critérios tocados pelo diff da correção, separados por vírgula")
    relatorio = comandos.add_parser("report", help="junta os blocos, calcula o veredito e posta")
    relatorio.add_argument("--card", required=True, type=_card)
    relatorio.add_argument("--run", required=True)
    relatorio.add_argument("--runtime", default="", help="linha de runtime observado (claude_proxy.py --handoff)")
    trava = comandos.add_parser("soltar", help="solta a trava na falha de ferramenta")
    trava.add_argument("--card", required=True, type=_card)
    trava.add_argument("--motivo", help="código da falha: comenta no issue o que falta")
    args = parser.parse_args(argv)
    if args.comando == "plan" and args.leitura and not args.reteste_de:
        parser.error("--leitura exige --reteste-de")
    io = Io()
    try:
        cfg = load_config()
        if args.comando == "plan":
            tocados = [item.strip() for item in args.criterios.split(",") if item.strip()]
            saida = plan(cfg, args.card, io, pr=args.pr, reteste_de=args.reteste_de, leitura=args.leitura, tocados=tocados)
        elif args.comando == "report":
            saida = report(cfg, args.card, args.run, io, runtime=args.runtime)
        else:
            saida = soltar(cfg, args.card, io, motivo=args.motivo)
    except (QaDevError, OSError, subprocess.TimeoutExpired) as exc:
        saida = {"status": "erro", "erro": str(exc)}
    json.dump(saida, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if saida.get("status") in {"pronto", "nada_para_testar", "inconclusivo", "postado", "solta", "sem_trava"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
