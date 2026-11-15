# Deployment example

`kubernetes.example.yaml` shows the shape of a deployment that matches the image: a PersistentVolumeClaim, a Deployment and a NetworkPolicy. Every value that names your setup is a placeholder. Keep your real manifests, addresses and secrets in a private repository, not here.

## What it sets up

- One replica with the `Recreate` strategy. SQLite and the Telegram session file live on the `/data` volume and must never be open in two pods.
- uid and gid 10001 (the image's `app` user), `fsGroup: 10001` so that user can write the volume, a read-only root filesystem, no capabilities, no service account token.
- `/data`: a 1Gi claim on block storage. SQLite in WAL mode does not work on NFS or SMB.
- `/tmp`: an `emptyDir` with `sizeLimit: 10Gi` for downloads and the yt-dlp and deno caches. Plan about 4.5 GB per parallel job; the default `TMP_BUDGET` (`MAX_PARALLEL_JOBS` × 4500 MiB) fits in it. If you change `MAX_PARALLEL_JOBS`, change `sizeLimit`, the `ephemeral-storage` limit and `TMP_BUDGET` with it.
- `/cookies`: the optional `ytdlbot-cookies` Secret, read-only. The bot reads each file into memory and never writes it.
- Startup and liveness probes run `python /app/health.py`, which fails when the heartbeat file is older than 180 s.
- Resources: request equals limit. The numbers in the example are placeholders; measure the peak of a large video (download plus ffmpeg merge) and size from that.
- Keel annotations (`keel.sh/policy: force`, `keel.sh/match-tag: "true"`, `keel.sh/trigger: poll`) and `imagePullPolicy: Always`: when `stable` moves, Keel restarts the pod and the new digest is pulled.

## Secrets

The bot's settings come from the `ytdlbot-env` Secret (`BOT_TOKEN`, `APP_ID`, `APP_HASH`, `OWNER`, `AUTHORIZED_USER`, `PROXY_EXITS`, `PROXY_PIN`, `OWN_PUBLIC_IPS`; see `.env.example` for all of them). Set `PROXY_PIN=instagram=direct`: Instagram then never falls back to a proxy, so its login always comes from the same home address (the default pins nothing).

```sh
kubectl create secret generic ytdlbot-env --from-env-file=ytdlbot.env
kubectl create secret generic ytdlbot-cookies --from-file=instagram.txt --from-file=youtube.txt
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

Nothing deploys from `main` directly. `.github/workflows/ci.yml` tests every PR and pushes its image as `sha-<head sha>`, Jenkins runs the regression suite on that image, and `.github/workflows/merge-and-promote.yml` copies the tested digest to `stable` (and `YYYY.MM.DD-<short sha>`) only when the commit on `main` has the same tree as the tested PR head. Keel then rolls the pod.
