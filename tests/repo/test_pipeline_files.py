# Checks on the GitHub workflows, the Dependabot file and the deployment example (spec 6.1, 6.14, 6.15).

import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = ROOT / "deploy"
RFC1918 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def updates(ecosystem):
    [entry] = [u for u in load(ROOT / ".github" / "dependabot.yml")["updates"] if u["package-ecosystem"] == ecosystem]
    return entry


def test_actions_pinned_by_sha():
    uses = [u for path in WORKFLOWS for u in re.findall(r"^\s*-?\s*uses:\s*(\S+)", path.read_text(encoding="utf-8"), re.M)]
    assert any("actions/checkout@" in u for u in uses), "no workflow checks out the code"
    assert [u for u in uses if not re.search(r"@[0-9a-f]{40}$", u)] == []


def test_no_pull_request_target():
    assert WORKFLOWS
    assert [p.name for p in WORKFLOWS if "pull_request_target" in p.read_text(encoding="utf-8")] == []


def test_no_statuses_write():
    # the regression status belongs to Jenkins; no workflow may write commit statuses
    assert WORKFLOWS
    assert [p.name for p in WORKFLOWS if re.search(r"statuses:\s*write", p.read_text(encoding="utf-8"))] == []


def test_ci_checks_out_head_sha():
    ci = load(CI)
    assert list(ci[True]) == ["pull_request"]  # PyYAML reads the `on` key as True
    [job] = ci["jobs"].values()
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"]
    [checkout] = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"] == {
        "ref": "${{ github.event.pull_request.head.sha }}",
        "persist-credentials": False,
        "fetch-depth": 0,
    }


def test_ci_passes_lock_versions_as_build_args():
    text = CI.read_text(encoding="utf-8")
    assert "uv.lock" in text
    for name in ("YT_DLP_VERSION", "CURL_CFFI_VERSION", "KURIGRAM_VERSION"):
        assert f"--build-arg {name}=" in text


def test_dependabot_yt_dlp_alone():
    uv = updates("uv")
    assert uv["schedule"]["interval"] == "daily"
    group = uv["groups"]["python-deps"]
    assert group["patterns"] == ["*"]
    assert group["exclude-patterns"] == ["yt-dlp"]
    assert uv["cooldown"] == {"default-days": 3, "exclude": ["yt-dlp"]}


def test_docker_python_minor_ignored():
    docker = updates("docker")
    [rule] = [r for r in docker["ignore"] if r["dependency-name"] == "python"]
    assert set(rule["update-types"]) == {"version-update:semver-minor", "version-update:semver-major"}


def _without_except(node):
    if isinstance(node, dict):
        return {k: _without_except(v) for k, v in node.items() if k != "except"}
    if isinstance(node, list):
        return [_without_except(v) for v in node]
    return node


def test_example_has_no_real_addresses():
    files = sorted(DEPLOY.iterdir())
    assert {p.name for p in files} >= {"kubernetes.example.yaml", "README.md"}
    texts = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "t.me" not in text, path.name
        if path.suffix == ".yaml":
            docs = [_without_except(d) for d in yaml.safe_load_all(text)]
            text = yaml.safe_dump_all(docs)
        texts.append(text)
    found = [ipaddress.ip_network(a, strict=False) for t in texts for a in IPV4.findall(t)]
    assert found, "the example names no addresses at all"
    assert [str(n) for n in found if any(n.subnet_of(p) for p in RFC1918)] == []
