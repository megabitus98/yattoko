# Checks on the GitHub workflows, the Dependabot file and the deployment example (spec 6.1, 6.14, 6.15).

import ipaddress
import re
import subprocess
import textwrap
from pathlib import Path

import pytest
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
    # every result is a check run of a job; no workflow writes commit statuses
    assert WORKFLOWS
    assert [p.name for p in WORKFLOWS if re.search(r"statuses:\s*write", p.read_text(encoding="utf-8"))] == []


OWN_BRANCHES = "github.event.pull_request.head.repo.full_name == github.repository"
HOME_RUNNER = ["self-hosted", "yattoko-regression"]


def jobs():
    # (workflow file name, job id, job) for every job in every workflow
    return [(path.name, job_id, job) for path in WORKFLOWS for job_id, job in load(path)["jobs"].items()]


def checks_out(job):
    return any(s.get("uses", "").startswith("actions/checkout@") for s in job.get("steps", []))


def runs_on(job):
    value = job["runs-on"]
    return value if isinstance(value, list) else [value]


def test_ci_checks_out_head_sha():
    ci = load(CI)
    assert list(ci[True]) == ["pull_request"]  # PyYAML reads the `on` key as True
    assert list(ci["jobs"]) == ["unit", "scan", "push", "regression", "merge", "cleanup", "notify"]
    # each condition in full: a substring check would pass `<guard> || true`
    own = OWN_BRANCHES
    assert {job_id: job["if"].strip() for job_id, job in ci["jobs"].items()} == {
        "unit": own,
        "scan": own,
        "push": own,
        "regression": own,
        "merge": f"{own} && github.event.pull_request.user.login == 'dependabot[bot]' && "
        "startsWith(github.event.pull_request.head.ref, 'dependabot/uv/')",
        "cleanup": f"always() && needs.push.result != 'failure' && {own}",
        "notify": f"always() && {own} && (contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled'))",
    }
    checkouts = {job_id: [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")] for job_id, job in ci["jobs"].items()}
    assert {job_id for job_id, found in checkouts.items() if found} == {"unit", "scan"}
    for job_id in ("unit", "scan"):
        [checkout] = checkouts[job_id]
        assert checkout["with"] == {
            "ref": "${{ github.event.pull_request.head.sha }}",
            "persist-credentials": False,
            "fetch-depth": 0,
        }


def test_permissions_per_job():
    # nothing is granted at workflow level; each job states its own
    for path in WORKFLOWS:
        assert load(path)["permissions"] == {}, path.name
    for name, job_id, job in jobs():
        assert "permissions" in job, (name, job_id)


def test_job_ids_are_the_check_names():
    # promote.yml asks for check runs by job id; a `name:` would rename the check and block every promote
    assert [(name, job_id) for name, job_id, job in jobs() if "name" in job] == []


def test_write_tokens_never_run_pr_code():
    # A job that can write anything runs no action and nothing from the image: a PR run uses the PR's own
    # workflow file, so a Dependabot GitHub Actions PR picks the action versions of its own run.
    writers = {(name, job_id): job for name, job_id, job in jobs() if "write" in job["permissions"].values()}
    assert set(writers) == {("ci.yml", "push"), ("ci.yml", "merge"), ("ci.yml", "cleanup"), ("promote.yml", "promote")}
    for key, job in writers.items():
        assert [s["uses"] for s in job["steps"] if "uses" in s] == [], key
        starts_container = re.compile(r"\bdocker\s+(container\s+)?(run|create|start|exec)\b")
        assert [s.get("name") for s in job["steps"] if starts_container.search(s.get("run", ""))] == [], key


def test_notify_reports_cancelled_runs():
    # an offline home runner ends in a cancel after 24 hours, not a failure
    notify = load(CI)["jobs"]["notify"]
    assert "contains(needs.*.result, 'cancelled')" in notify["if"]
    assert set(notify["needs"]) == set(load(CI)["jobs"]) - {"notify"}


def test_packages_write_only_push_and_promote():
    packages = {(name, job_id) for name, job_id, job in jobs() if job["permissions"].get("packages") == "write"}
    assert packages == {("ci.yml", "push"), ("promote.yml", "promote")}
    texts = {p.name: p.read_text(encoding="utf-8") for p in WORKFLOWS}
    assert [name for name, text in texts.items() if "imagetools create" in text] == ["promote.yml"]


def test_home_runner_only_runs_the_regression():
    home = {(name, job_id): job for name, job_id, job in jobs() if set(HOME_RUNNER) & set(runs_on(job))}
    assert set(home) == {("ci.yml", "regression"), ("weekly.yml", "regression")}
    for key, job in home.items():
        assert job["runs-on"] == HOME_RUNNER, key
        assert job["permissions"] == {"packages": "read"}, key
        assert not checks_out(job), key
    # everything else on GitHub's runners
    others = {(name, job_id): job["runs-on"] for name, job_id, job in jobs() if (name, job_id) not in home}
    assert {key: label for key, label in others.items() if label != "ubuntu-24.04"} == {}


def test_merge_only_dependabot_uv():
    merge = load(CI)["jobs"]["merge"]
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in merge["if"]
    assert "startsWith(github.event.pull_request.head.ref, 'dependabot/uv/')" in merge["if"]
    assert merge["needs"] == "regression"


def test_promote_requires_every_gate():
    # the check names promote waits for are exactly the ci jobs a release depends on
    text = (ROOT / ".github" / "workflows" / "promote.yml").read_text(encoding="utf-8")
    [names] = re.findall(r"for check_name in ([a-z ]+); do", text)
    assert names.split() == ["unit", "scan", "push", "regression"]
    assert set(names.split()) <= set(load(CI)["jobs"])


def test_malware_check_on_every_sync():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    syncs = [line for line in dockerfile.splitlines() if "uv sync" in line]
    assert len(syncs) == 2
    assert [line for line in syncs if not re.fullmatch(r"\s*UV_MALWARE_CHECK=1 uv sync --locked( --no-dev)?", line)] == []
    assert load(CI)["jobs"]["unit"]["env"]["UV_MALWARE_CHECK"] == "1"


def test_images_in_run_steps_pinned():
    weekly = load(ROOT / ".github" / "workflows" / "weekly.yml")
    assert re.fullmatch(r"anchore/grype:v[\d.]+@sha256:[0-9a-f]{64}", weekly["env"]["grype_image"])


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


def _except_cidrs(node):
    if isinstance(node, dict):
        return [c for k, v in node.items() for c in (v if k == "except" else _except_cidrs(v))]
    if isinstance(node, list):
        return [c for v in node for c in _except_cidrs(v)]
    return []


def _private_addresses(text, is_yaml):
    # scans the raw text, comments included; only the exact CIDRs listed under `except:` are allowed
    allowed = {str(c) for d in yaml.safe_load_all(text) for c in _except_cidrs(d)} if is_yaml else set()
    return [
        a
        for a in IPV4.findall(text)
        if a not in allowed and any(ipaddress.ip_network(a, strict=False).subnet_of(p) for p in RFC1918)
    ]


def test_address_scan_reads_comments():
    planted = "# Egress (home proxy 192.168.1.5)\nexcept:\n  - 10.0.0.0/8 # private, proxy at 10.1.2.3\n"
    assert _private_addresses(planted, is_yaml=True) == ["192.168.1.5", "10.1.2.3"]


def test_example_has_no_real_addresses():
    files = sorted(DEPLOY.iterdir())
    assert {p.name for p in files} >= {"kubernetes.example.yaml", "README.md"}
    texts = {p.name: p.read_text(encoding="utf-8") for p in files}
    assert [name for name, text in texts.items() if "t.me" in text] == []
    assert any(IPV4.findall(t) for t in texts.values()), "the example names no addresses at all"
    found = {name: _private_addresses(text, name.endswith(".yaml")) for name, text in texts.items()}
    assert {name: a for name, a in found.items() if a} == {}


PROMOTE = ROOT / ".github" / "workflows" / "promote.yml"
# the marker lines carry a comment after them and sit indented inside `run: |`
RULE = re.compile(r"# >>> release rule[^\n]*\n(.*?)^[ \t]*# <<< release rule", re.S | re.M)


def release_rule(path):
    [block] = RULE.findall(path.read_text(encoding="utf-8"))
    return textwrap.dedent(block)


def run_rule(call):
    return subprocess.run(["bash", "-c", release_rule(CI) + call], capture_output=True, text=True)


def test_release_rule_identical():
    assert release_rule(CI) == release_rule(PROMOTE)


@pytest.mark.parametrize(
    "previous, title, expected",
    [
        ("", "fix: a", "v1.0.0"),
        ("", "fix!: a", "v1.0.0"),
        ("", "feat: a", "v1.0.0"),
        ("v1.0.3", "deps: bump yt-dlp from 1 to 2", "v1.0.4"),
        ("v1.0.3", "fix(cache): a", "v1.0.4"),
        ("v1.0.3", "docs: a", "v1.0.4"),
        ("v1.0.3", "feat: a", "v1.1.0"),
        ("v1.2.3", "feat!: a", "v2.0.0"),
        ("v1.2.3", "fix(api)!: a", "v2.0.0"),
        ("v1.9.9", "feat: a", "v1.10.0"),
    ],
)
def test_release_rule_bumps(previous, title, expected):
    result = run_rule(f'next_version "{previous}" "{title}"')
    assert (result.returncode, result.stdout.strip()) == (0, expected)


@pytest.mark.parametrize("title", ["Feat: a", "feat:a", "feature: a", "fix(Scope): a", "", "Rename the fork", "feat: "])
def test_release_rule_rejects(title):
    assert run_rule(f'next_version v1.0.0 "{title}"').returncode != 0


def test_pr_title_never_inline_in_run():
    # the title is written by whoever opens the PR: only env values and the API may carry it
    for path in WORKFLOWS:
        for job in load(path)["jobs"].values():
            for step in job.get("steps", []):
                assert "pull_request.title" not in step.get("run", ""), (path.name, step.get("name"))


def test_unit_reads_releases():
    unit = load(CI)["jobs"]["unit"]
    assert unit["permissions"] == {"contents": "read", "pull-requests": "read", "actions": "read"}
    assert unit["steps"][1]["name"] == "Release version"  # right after checkout: a bad title fails first


def test_only_promote_and_merge_write_contents():
    writers = {(name, job_id) for name, job_id, job in jobs() if job["permissions"].get("contents") == "write"}
    assert writers == {("ci.yml", "merge"), ("promote.yml", "promote")}


def test_promote_creates_releases():
    promote = load(PROMOTE)["jobs"]["promote"]
    assert promote["permissions"]["contents"] == "write"
    text = PROMOTE.read_text(encoding="utf-8")
    assert "repos/$GH_REPO/releases" in text and "org.opencontainers.image.version" in text
