"""Career-vault reader and writer.

Reads from the git-sync checkout (``/vault/current``, read-only). Writes go
to a separate working clone in an ``emptyDir`` with the write deploy key:
pull, write only paths under ``job-search/`` (any other path raises), commit,
push; on push conflict, pull and retry once.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shlex
import subprocess
from datetime import date, datetime
from pathlib import Path

import yaml

logger = logging.getLogger("job-search")

VAULT_READ_ROOT = Path(os.environ.get("VAULT_READ_ROOT", "/vault/current"))
VAULT_WORK_ROOT = Path(os.environ.get("VAULT_WORK_ROOT", "/vault/work"))
VAULT_WRITE_KEY = Path(os.environ.get("VAULT_WRITE_KEY", "/etc/vault-keys/rw"))
JOBS_PREFIX = "job-search"

SAFE_PATH_PREFIX = f"{JOBS_PREFIX}/"

DATE_FIELDS = {"applied", "next_action_date", "drafted"}


def to_date(value):
    """Normalize a frontmatter date to ``datetime.date`` (or None).

    YAML gives an unquoted ``2026-11-18`` as ``datetime.date`` and a quoted
    ``"2026-11-18"`` as ``str``; both must compare and sort the same way.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter(path: Path) -> dict:
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def _frontmatter_all(path: Path) -> list[dict]:
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        return [{}]
    parts = text.split("---")
    fms = []
    for part in parts[1::2]:
        fm = yaml.safe_load(part) or {}
        fms.append(fm)
    return fms


def read_profile() -> dict:
    """Return flat profile properties as a dict."""
    path = VAULT_READ_ROOT / JOBS_PREFIX / "profile.md"
    return _frontmatter(path)


def read_cv(variant: str) -> tuple[str, dict]:
    """Read a CV Markdown file and its frontmatter.

    Returns (body, frontmatter). Checks ``source_sha256`` against the
    corresponding ``.docx`` and includes a warning in body if they differ.
    """
    md_path = VAULT_READ_ROOT / JOBS_PREFIX / "cv" / f"{variant}.md"
    fm = _frontmatter(md_path)
    body = md_path.read_text(errors="replace")
    if body.startswith("---"):
        body = body.split("---", 2)[-1].lstrip()

    source_sha = fm.get("source_sha256", "")
    source_path = fm.get("source", "")
    if source_path and source_sha:
        docx_path = VAULT_READ_ROOT / JOBS_PREFIX / "cv" / source_path
        if docx_path.exists():
            actual = _sha256_file(docx_path)
            if actual != source_sha:
                warning = (
                    f"CV {variant} is out of date: run convert-cvs.sh "
                    f"(expected {source_sha[:12]}…, got {actual[:12]}…)\n\n"
                )
                body = warning + body

    return body, fm


def list_cv_variants() -> list[dict]:
    profile = read_profile()
    variants = []
    general_file = profile.get("cv_general_file", "")
    ai_file = profile.get("cv_ai_file", "")
    ai_use_when = profile.get("cv_ai_use_when", "")
    if general_file:
        variants.append({
            "variant": "general",
            "file": general_file,
            "use_when": "the default CV",
        })
    if ai_file:
        variants.append({
            "variant": "ai",
            "file": ai_file,
            "use_when": ai_use_when,
        })
    return variants


def read_roles() -> list[dict]:
    roles_dir = VAULT_READ_ROOT / JOBS_PREFIX / "roles"
    if not roles_dir.is_dir():
        return []
    roles = []
    for f in sorted(roles_dir.glob("*.md")):
        fm = _frontmatter(f)
        fm["_id"] = f.stem
        for key in DATE_FIELDS:
            if key in fm:
                fm[key] = to_date(fm[key])
        roles.append(fm)
    return roles


def read_digest(date_str: str) -> str:
    path = VAULT_READ_ROOT / JOBS_PREFIX / "digests" / f"{date_str}.md"
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def _run_git(work_dir: Path, args: list[str], env: dict | None = None) -> str:
    cmd = ["git"] + args
    logger.debug("git: %s", shlex.join(cmd))
    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        env=env or {},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_env() -> dict:
    env = os.environ.copy()
    ssh_cmd = (
        f"ssh -i {VAULT_WRITE_KEY} "
        "-o IdentitiesOnly=yes "
        "-o StrictHostKeyChecking=yes "
        "-o UserKnownHostsFile=/etc/ssh/known_hosts"
    )
    env["GIT_SSH_COMMAND"] = ssh_cmd
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = str(VAULT_WORK_ROOT)
    env.setdefault("GIT_AUTHOR_NAME", "job-search")
    env.setdefault("GIT_AUTHOR_EMAIL", "job-search@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "job-search")
    env.setdefault("GIT_COMMITTER_EMAIL", "job-search@localhost")
    return env


def _prepare_work_clone() -> Path:
    remote = os.environ.get("VAULT_REMOTE", "git@github.com:ssaav5/career-vault.git")
    env = _git_env()
    if (VAULT_WORK_ROOT / ".git").exists():
        _run_git(VAULT_WORK_ROOT, ["fetch", "origin"], env)
        _run_git(VAULT_WORK_ROOT, ["checkout", "main"], env)
        _run_git(VAULT_WORK_ROOT, ["reset", "--hard", "origin/main"], env)
        return VAULT_WORK_ROOT

    VAULT_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    _run_git(VAULT_WORK_ROOT.parent, ["clone", "--depth=1", remote, VAULT_WORK_ROOT.name], env)
    return VAULT_WORK_ROOT


def write_role(role_id: str, content: str) -> str:
    """Write a role file under ``job-search/roles/<role_id>.md``."""
    path = f"{SAFE_PATH_PREFIX}roles/{role_id}.md"
    return _write_vault([(path, content)], f"job-search: add role {role_id}")


def write_draft(role_id: str, content: str) -> str:
    """Write a draft file under ``job-search/drafts/<role_id>.md``."""
    path = f"{SAFE_PATH_PREFIX}drafts/{role_id}.md"
    return _write_vault([(path, content)], f"job-search: draft {role_id}")


def write_draft_and_role(role_id: str, draft_content: str, role_content: str) -> str:
    """Write the draft and its role tracker entry in one commit."""
    items = [
        (f"{SAFE_PATH_PREFIX}drafts/{role_id}.md", draft_content),
        (f"{SAFE_PATH_PREFIX}roles/{role_id}.md", role_content),
    ]
    return _write_vault(items, f"job-search: draft {role_id}")


def update_role_status(role_id: str, content: str, status: str) -> str:
    """Update a role's status."""
    path = f"{SAFE_PATH_PREFIX}roles/{role_id}.md"
    return _write_vault([(path, content)], f"job-search: {status} {role_id}")


def write_digest(date_str: str, content: str) -> str:
    """Write a daily digest."""
    path = f"{SAFE_PATH_PREFIX}digests/{date_str}.md"
    return _write_vault([(path, content)], f"job-search: digest {date_str}")


def _validate_path(path: str) -> None:
    if not path.startswith(SAFE_PATH_PREFIX):
        raise ValueError(f"path {path} is not under {SAFE_PATH_PREFIX}")
    resolved = os.path.normpath(path)
    if not resolved.startswith(SAFE_PATH_PREFIX):
        raise ValueError(f"path {path} escapes {SAFE_PATH_PREFIX}")


def _write_vault(items: list[tuple[str, str]], commit_msg: str) -> str:
    for repo_path, _ in items:
        _validate_path(repo_path)

    work = _prepare_work_clone()
    env = _git_env()

    def _write_files() -> None:
        for repo_path, content in items:
            file_path = work / repo_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

    _write_files()

    for repo_path, _ in items:
        _run_git(work, ["add", repo_path], env)
    _run_git(work, ["commit", "-m", commit_msg], env)
    sha = _run_git(work, ["rev-parse", "--short", "HEAD"], env)

    for attempt in range(2):
        try:
            _run_git(work, ["push", "origin", "main"], env)
            return sha
        except RuntimeError:
            if attempt == 0:
                logger.warning("push conflict, retrying")
                _run_git(work, ["fetch", "origin"], env)
                _run_git(work, ["reset", "--hard", "origin/main"], env)
                _write_files()
                for repo_path, _ in items:
                    _run_git(work, ["add", repo_path], env)
                _run_git(work, ["commit", "-m", commit_msg], env)
                sha = _run_git(work, ["rev-parse", "--short", "HEAD"], env)
            else:
                raise
    return sha