# Deployment example

`kubernetes.example.yaml` shows the shape of a deployment that matches the image: a PersistentVolumeClaim, a Deployment and a NetworkPolicy. Every value that names your setup is a placeholder. Keep your real manifests, addresses and secrets in a private repository, not here.

## What it sets up

- One replica with the `Recreate` strategy. SQLite and the Telegram session file live on the `/data` volume and must never be open in two pods.
- uid and gid 10001 (the image's `app` user), `fsGroup: 10001` so that user can write the volume, a read-only root filesystem, no capabilities, no service account token.
- `/data`: a 1Gi claim on block storage. SQLite in WAL mode does not work on NFS or SMB.
- `/tmp`: an `emptyDir` with `sizeLimit: 10Gi` for downloads and the yt-dlp cache. Plan about 4.5 GB per parallel job; the default `TMP_BUDGET` (`MAX_PARALLEL_JOBS` × 4500 MiB) fits in it. If you change `MAX_PARALLEL_JOBS`, change `sizeLimit`, the `ephemeral-storage` limit and `TMP_BUDGET` with it.
- `/cookies`: the optional `yattoko-cookies` Secret, read-only. The bot reads each file into memory and never writes it.
- Startup and liveness probes run `python /app/health.py`, which fails when the heartbeat file is older than 180 s.
- Resources: request equals limit. The numbers in the example are placeholders; measure the peak of a large video (download plus ffmpeg merge) and size from that.
- Keel annotations (`keel.sh/policy: force`, `keel.sh/match-tag: "true"`, `keel.sh/trigger: poll`) and `imagePullPolicy: Always`: when `stable` moves, Keel restarts the pod and the new digest is pulled.

## Secrets

The bot's settings come from the `yattoko-env` Secret (`BOT_TOKEN`, `APP_ID`, `APP_HASH`, `OWNER`, `AUTHORIZED_USER`, `PROXY_EXITS`, `PROXY_PIN`, `OWN_PUBLIC_IPS`; see `.env.example` for all of them). Set `PROXY_PIN=instagram=direct`, with `direct` also listed in `PROXY_EXITS` (for example `PROXY_EXITS=direct,http://proxy.example:8080`; the bot refuses to start when a pin names an exit that is not listed): Instagram then never falls back to a proxy, so its login always comes from the same home address (the default pins nothing). Set `ENABLE_FFMPEG=true` for the H.264 conversion of short VP9/AV1 videos.

```sh
kubectl create secret generic yattoko-env --from-env-file=yattoko.env
kubectl create secret generic yattoko-cookies --from-file=instagram.txt --from-file=youtube.txt
kubectl create secret docker-registry ghcr-pull --docker-server=ghcr.io \
  --docker-username=<github user> --docker-password=<classic token with read:packages only>
```

The pull secret is needed only while the image package is private; delete it from the Deployment when the package is public.

## Network

The NetworkPolicy denies all ingress and allows egress only to the cluster DNS (pods labelled `k8s-app: kube-dns` in `kube-system`), to public IPv4 addresses (everything except the private, CGNAT, link-local, loopback and multicast ranges) and to each proxy exit. There is no IPv6 rule, so IPv6 egress is denied.

- Replace the placeholder proxy rule (`203.0.113.10/32`, port 8080) with one rule per exit in `PROXY_EXITS`, or delete it when you use no proxy. A proxy on a private address needs its own rule; the public rule does not reach it.
- Check the DNS selector against your cluster: some distributions label the DNS pods differently.
- The policy cannot block your own public IP address: through the router's NAT loopback it can reach port-forwarded services at home. Drop traffic from the cluster's node subnet to the router's WAN address on the router, and list static public addresses in `OWN_PUBLIC_IPS`.

## Updates

Nothing deploys from `main` directly. Everything runs in GitHub Actions:

- `.github/workflows/ci.yml`, on every PR from a branch of this repository (Dependabot's and yours). On GitHub's runners: `unit` (repository checks, the image build with uv's malware check, unit tests) and `scan` (`uv audit`; fails on known vulnerabilities the PR adds), both with a read-only token; then `push`, which fetches the tested image and pushes it as `sha-<head sha>`; like every job that holds a write token, it checks out no code and runs no action, because a PR (Dependabot's GitHub Actions updates included) chooses the action versions of its own run. On the home runner: `regression`, the real downloads in that image. For Dependabot `uv` PRs, `merge` squash-merges a green PR that is level with `main` (one that is behind gets `@dependabot rebase` and is tested again) and starts `promote`. `cleanup` deletes the image artifact whatever happened. When a job fails or is cancelled, `notify` messages you through the test bot (not for a run that a newer push to the PR replaced).
- `.github/workflows/promote.yml`, on every push to `main` and when `merge` starts it: copies the tested digest to `stable` (and `YYYY.MM.DD-<short sha>`) only when the commit on `main` came from a PR whose head passed `unit`, `scan`, `push` and `regression` and has the same tree. A direct push to `main` promotes nothing; it ships with the next tested update. Each promote is also a release `vX.Y.Z` (see "Versions" in the main README): the image gets that tag, and a GitHub Release with the notes of the PRs merged since the previous one creates the git tag. The image must have been built as that version; if not (the PR title's type changed after CI, or another release landed first), nothing is released and the commit ships with the next release. To roll back, point the Deployment at an older `:vX.Y.Z` (and remove the Keel annotations until you go forward again). Keel then rolls the pod. A failed promote messages you through the test bot.
- `.github/workflows/weekly.yml`, Mondays: the regression on `stable` (home runner), the full `uv audit`, Grype on the stable image (fails on fixable high or critical findings), and a drift check (yt-dlp more than 3 days or curl-cffi more than 5 days behind PyPI, a Dependabot PR open for more than 3 days, a newer `python:3.12-alpine` base than the Dockerfile's). A problem is sent through the test bot; a clean week calls `HEARTBEAT_URL`.

Docker and GitHub Actions updates from Dependabot are tested the same way but wait for you to merge them.

### Secrets

In Settings → Secrets and variables, add each of these under **Actions** and again under **Dependabot** (runs started by Dependabot only read the Dependabot ones):

- `TEST_BOT_TOKEN`, `TEST_CHAT_ID`: a separate test bot, never the production bot, and the chat it reports to (your private chat with it). The regression uploads its smallest result there.
- `TEST_APP_ID`, `TEST_APP_HASH`: the API ID and hash the test bot logs in with.
- `HEARTBEAT_URL` (Actions only, optional): a push monitor URL, for example from Uptime Kuma, called after a clean weekly run.

The test secrets reach the code under test inside the regression container, so they must belong to a throwaway test bot. Without any of them the regression only downloads, and the message steps fail so the run shows that nobody was told: GitHub notifies only whoever started a run, and for Dependabot's runs and the promote that `merge` starts, that is a bot. With some but not all four, the regression fails and names the missing ones.

### Home runner

The regression has to download from a home connection: video sites often block the datacenter addresses of GitHub's runners. It runs on a self-hosted runner with the label `yattoko-regression`:

- A small VM, or an unprivileged LXC container with nesting enabled, with Docker and nothing else on it: the regression runs new dependency versions, and a container escape would land on that host.
- Register it for this repository only (Settings → Actions → Runners → New self-hosted runner), add the label `yattoko-regression` (`./config.sh ... --labels yattoko-regression`), and run it as a service. So that no job can leave something behind for the next one, either use `--ephemeral` with a wrapper that registers a fresh runner after each job, or roll the host back to a clean snapshot every night. Shut it down cleanly before the rollback: after a hard stop GitHub keeps the old session open, and the restarted runner waits until it expires ("A session for this runner already exists").
- Internet only: block the host from your LAN on the router or with a separate VLAN, and keep its containers off private addresses: `iptables` rules in the `DOCKER-USER` chain that drop the three RFC 1918 ranges, after a rule that accepts your DNS server if it sits on a private address. `DOCKER-USER` only sees traffic the host forwards; traffic from a container to the host itself (SSH, the Docker API on TCP) goes through `INPUT`, so also drop the Docker bridge networks there for everything but DNS.
- It needs no secrets of its own: each job brings a read-only registry token and the test bot secrets, and removes its registry login when it ends.

If the runner is offline, the regression job waits; GitHub cancels it after 24 hours and `notify` tells you. No update merges until you re-run that run (Re-run jobs, on the PR's Checks tab) with the runner back; the image stays in the registry, so the regression can run again on its own.

### Before making the repository public

- Settings → Actions → General → "Approval for running fork pull request workflows from contributors": **Require approval for all external contributors**. A fork's PR runs its own copy of the workflows and could send a job to the home runner, so nothing from a fork may start without your click. Never approve one that changes anything under `.github/`. Dependabot's and your own PRs are branches of this repository and keep running without approval.
- Make the image package public, then delete the `ghcr-pull` secret and its classic token.
