# VPS SSH lockdown runbook — Phase 5 Task 5.1

**Goal.** Take SSH off port 22, key-only, no root, host-firewalled (UFW + Lightsail console), with the bot's runtime user `ops` separated from the default cloud-init `ubuntu` user. End state: only port 2222 reachable on the box, only via key for `ops`, with no fallback access path on port 22.

**Scope.** Everything that happened during the 2026-05-07 evening session that drove Phase 5 from "VPS provisioned, no commands run" to "5.1 PASS." Future operators reading this should be able to (a) reproduce the lockdown on a fresh Lightsail Ubuntu 24.04 instance, (b) understand the security trade-offs taken, and (c) recover if the box's SSH ever breaks.

## Corrections applied to last session's notes

The hand-off note `state/sessions/2026-05-07-vps-provisioned.md` had two facts wrong; both confirmed during 5.1:

| Field | Last session said | Actual |
|---|---|---|
| Public IPv4 | `108.130.237.88` | **`108.132.51.116`** (verified via IMDSv2 `meta-data/public-ipv4` and Lightsail console `StaticIp-1`) |
| Instance name | `Ubuntu-1` | **`5m-Polymarket-bot`** |
| Region/AZ | `eu-west-1 / eu-west-1a` | confirmed correct via IMDSv2 `meta-data/placement/region` |

The `108.130.237.88` ghost IP cost ~30 minutes of SSH-from-Mac debugging before we noticed nothing was at that address. Lesson: previous-session hand-off facts are claims, not ground truth — verify on first contact.

## Decision: Path B (Any IPv4 + key-only + non-default port + fail2ban)

Operator's workstation runs NordVPN with rotating exit IPs. Two paths were considered:

- **Path A** — Lock port 2222 in Lightsail to the operator's current public IP. **Rejected** — VPN exit rotation breaks this 2-3x per week; per-IP whitelist on dynamic egress is operationally broken.
- **Path B** — Leave port 2222 open to `Any IPv4 address` and rely on a layered auth stack: non-default port + key-only auth + no root + fail2ban for brute-force back-off. **Accepted.**

**Why Path B is safe:** the actual attack vector against an internet-exposed sshd with key-only auth is a zero-day in OpenSSH. Locking to one IP doesn't help with that. fail2ban (added in 5.5) makes the brute-force scanning noise-floor negligible.

## End state

- **sshd** listens on `2222/tcp` only (IPv4 + IPv6). Port 22 not bound.
- **UFW** active: default deny incoming, allow outgoing, only `2222/tcp` allowed inbound.
- **Lightsail console firewall**: only `Custom / TCP / 2222 / Any IPv4` and `HTTP / TCP / 80 / Any IPv4` rules remain. SSH/22 rule deleted.
- **`ops` user** created with passwordless sudo (uid 1001, in `sudo` group, key-auth via `/home/ops/.ssh/authorized_keys` mode 600 owned `ops:ops`).
- **`ssh.socket`** masked + inactive. **`ssh.service`** enabled + active as the master daemon (Ubuntu 24.04 socket activation switched off — see "Gotcha" below).

## Gotcha — Ubuntu 24.04 socket activation hijacks `Port` directives

Ubuntu 24.04's default sshd setup uses systemd socket activation (`ssh.socket` listens on port 22 and spawns a per-connection sshd). When socket activation is in effect, **`Port` directives in `sshd_config` are ignored** because sshd inherits its socket from systemd rather than binding ports itself.

Symptom we saw: `sshd -T` showed `port 22` and `port 2222` correctly, but `ss -tlnp` only showed port 22 listening — the `Port 2222` directive was a no-op.

Fix:

```bash
sudo systemctl disable --now ssh.socket
sudo systemctl enable --now ssh.service
sudo systemctl mask ssh.socket   # prevent it coming back on reboot
```

After this, `ssh.service` runs `sshd -D` as a long-lived master that honors `sshd_config` ports.

## Files committed to git

- This runbook: `runbooks/vps-ssh-lockdown.md`
- The sshd drop-in (committed verbatim for reproducibility): `runbooks/vps/sshd_config.d/99-polybot-lockdown.conf` (created at end of 5.1.G; deployed to `/etc/ssh/sshd_config.d/99-polybot-lockdown.conf` on the VPS).

## Step-by-step (the actual lockdown sequence)

All VPS commands run on Lightsail browser-SSH or Mac local-key SSH unless noted. Operator pastes outputs back; Claude drives the next step.

### 5.1.A — Recovery path: open a second SSH session

`chmod 600 ~/Downloads/LightsailDefaultKey-eu-west-1.pem` on Mac, then `ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@108.132.51.116`.

The browser-SSH tab is the first session; the Mac local-key SSH is the second. Two paths into the box are required before any firewall change.

### 5.1.B — Create `ops` user

```bash
sudo useradd -m -s /bin/bash ops
sudo usermod -aG sudo ops
sudo mkdir -p /home/ops/.ssh && sudo chmod 700 /home/ops/.ssh
sudo cp /home/ubuntu/.ssh/authorized_keys /home/ops/.ssh/authorized_keys
sudo chown -R ops:ops /home/ops/.ssh
sudo chmod 600 /home/ops/.ssh/authorized_keys
echo 'ops ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-ops-nopasswd
sudo chmod 440 /etc/sudoers.d/90-ops-nopasswd
```

Passwordless sudo is intentional. The SSH key is the credential; sudo password adds friction without real security under key-only auth.

### 5.1.C — Verify ops login (Mac, fresh terminal)

```bash
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ops@108.132.51.116
```

Inside: `sudo whoami` → `root` (passwordless sudo confirmed).

### 5.1.D — Lightsail console: add port 2222

Networking → IPv4 Firewall → Add rule → Custom / TCP / 2222 / Any IPv4 / Save.

Done **before** sshd config change so port 2222 is reachable the moment sshd starts listening.

### 5.1.E — Drop-in sshd lockdown config + ssh.socket → ssh.service switch

Drop-in (`/etc/ssh/sshd_config.d/99-polybot-lockdown.conf`):

```
# Phase 5.1 SSH lockdown for Polymarket bot
# SSH listens only on port 2222.
Port 2222
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

Ubuntu's main `/etc/ssh/sshd_config` has `Include /etc/ssh/sshd_config.d/*.conf` near the top; first-occurrence-wins for most directives means drop-in values override defaults.

Validate before reload:

```bash
sudo sshd -t && echo "config OK" || echo "CONFIG ERROR — DO NOT RELOAD"
```

Switch from socket activation to ssh.service master:

```bash
sudo systemctl disable --now ssh.socket
sudo systemctl enable --now ssh.service
```

Verify post-switch — `sudo ss -tlnp | grep -E ':(22|2222) '` must show **both** listeners during cutover (port 22 kept by the leftover socket-activated master, port 2222 from the new ssh.service master).

### 5.1.F — UFW

```bash
sudo ufw allow 2222/tcp comment 'ssh-alt'
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw --force enable
sudo ufw status verbose
```

`--force` skips the "this may break SSH" interactive prompt. Existing port-22 sessions survive via netfilter conntrack (ESTABLISHED state allowed). New port-22 inbound is silently dropped from this point on.

### 5.1.G — Final cleanup

1. Rewrite drop-in without `Port 22` (above content was already final form), `sudo systemctl reload ssh.service`.
2. From a Mac port-2222 ops session: `sudo systemctl mask ssh.socket && sudo kill 770` (where 770 is the leftover socket-activated sshd master listening on port 22).
3. Lightsail console: trash icon on the SSH/22 rule.

After step 2, only port 2222 listening on the box. After step 3, port 22 closed at both layers.

## Verification (the four PASS criteria)

Run from Mac, **outside** any SSH session:

```bash
nc -vz -w 5 108.132.51.116 22
nc -vz -w 5 108.132.51.116 2222
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 -o BatchMode=yes root@108.132.51.116 true 2>&1 | head -3
ssh -i /dev/null -p 2222 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o BatchMode=yes ops@108.132.51.116 true 2>&1 | head -3
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 'echo "lockdown verified: $(whoami)@$(hostname):$(echo $SSH_CONNECTION | awk "{print \$4}")"'
```

| Test | Expected | Captured 2026-05-07 |
|---|---|---|
| nc :22 | `Operation timed out` | ✅ `nc: connectx to 108.132.51.116 port 22 (tcp) failed: Operation timed out` |
| nc :2222 | `succeeded` | ✅ `Connection to 108.132.51.116 port 2222 [tcp/rockwell-csp2] succeeded!` |
| ssh root@:2222 | denied even with key | ✅ `root@108.132.51.116: Permission denied (publickey).` |
| ssh ops@:2222 password-only | denied (no password tried) | ✅ `ops@108.132.51.116: Permission denied (publickey).` |
| ssh ops@:2222 with key | succeeds | ✅ `lockdown verified: ops@ip-172-26-6-176:2222` |

## Recovery

If SSH on port 2222 breaks completely:

1. **First**: check whether you still have an active SSH session from a prior connection. Even if new connections fail, an established session lets you debug from inside.
2. Lightsail console **does not** offer a serial/console fallback for instances. Browser-SSH won't work either since port 22 is closed at both layers.
3. **Snapshot revert** is the only fully out-of-band recovery — but automatic snapshots are disabled (~$4/mo extra; revisit after Phase 5 closes).
4. Pragmatic recovery without snapshots: stop the instance from the Lightsail console → detach the static IP → spin up a fresh Lightsail instance → re-run this runbook. The repo is in git, the Signer key is in `.envrc` only on this VPS (move it again from the laptop per 5.6), and `state/` is git-tracked.

If you locked yourself out via UFW only (sshd still listening on 2222), the Lightsail console doesn't help — same reasoning. Solution: be careful with UFW rules; never deny `2222/tcp` without an alternative path open first.

## What 5.1 does NOT cover (defer to)

- **fail2ban** — added in 5.5 (`Task 5.5 — Monitoring stack`). Until then, brute-force attempts on port 2222 will keep retrying without back-off (key-only means they all fail, but the noise hits the auth log).
- **Automatic security updates** — `unattended-upgrades` is installed by default on Ubuntu 24.04 cloud images and runs daily. Verify in 5.2.
- **Restricting outgoing traffic** — UFW `allow outgoing` is permissive. Phase 6 may want to restrict outgoing to only Polygon RPC + Polymarket CLOB + Anthropic API endpoints.
- **AWS Lightsail browser-SSH** — disabled by removing port 22. If you ever need it back as an emergency tool, re-add the SSH/22 rule in Lightsail with the "Allow Lightsail browser SSH" checkbox enabled (whitelists Lightsail proxy IPs only) and re-open port 22 in UFW. **Reverses the lockdown** — only do this for a known emergency, not as a "just in case."
