# SAFi Appliance — Debian ISO

Builds a bootable Debian ISO, Trixbox/Elastix style: the ISO boots the Debian
installer, installs a minimal headless system with SAFi baked in, and on first
boot presents the appliance configuration wizard (the repo's own
`scripts/setup.py`). Result is a self-contained installable appliance that runs
in any VM.

The installed system is the **bare-metal** layout documented in
[`docs/DEPLOY_BAREMETAL.md`](../../docs/DEPLOY_BAREMETAL.md): system MySQL,
virtualenv under `/var/www/safi`, systemd units from `deploy/systemd/`, Apache
reverse proxy on `:80`, the app on `127.0.0.1:5001`.

## Build

On a Debian host (or a build VM/container — this can take ~30–60 min and
downloads ~1 GB):

```bash
sudo apt install live-build debootstrap git
cd deploy/iso
./build.sh                      # bookworm + amd64, SAFI_REF=v1.4.1
SAFI_REF=v1.4 ./build.sh        # a different release tag
```

Produces `safi-appliance-<ref>-<arch>.iso`.

## Test a VM boot

```bash
qemu-system-x86_64 -m 4096 -smp 2 -cdrom safi-appliance-v1.4.1-amd64.iso -boot d
```

Install unattended to the disk, reboot with `-boot c`, and the first-boot
wizard claims tty1: it runs `scripts/setup.py` (provider key, admin account,
network), then creates the MySQL `safi` database, enables all services, sets
the `admin` operator password, and prints the web URL. Done.

## Installer flavor

`auto/config` embeds the **netinst** flavor of debian-installer and wires the
preseed in as `--debian-installer-preseedfile file:///cdrom/preseed.cfg`. This
is deliberate: netinst's *default* boot entry is the unattended installer
itself (which honors the preseed for a hands-off pass), rather than the `live`
flavor's "Live system" entry, which live-build used to default to and which
would stop at the interactive "Set up users and passwords" prompt.

If you ever regenerate the ISO and boot into the menu manually, the entries are
`Start installer`, `^Install`, and — for one-shot assisted runs — the
`^Automated install` entry under `Advanced install options` (identical cmdline
to the preseeded default, historically used for debugging).

## Layout

| Path | Purpose |
|---|---|
| `build.sh` | entry point: `lb config` → `lb build`, renames the ISO |
| `auto/config` | live-build automation — distribution, arch, d-i mode, ISO labels |
| `config/preseed/safi.cfg` | unattended debian-installer preseed (whole-disk install, no d-i user) |
| `config/package-lists/` | daemon-free packages baked into the rootfs |
| `config/hooks/normal/01x` | installs mysql/apache/ssh behind a blocked-start policy |
| `config/hooks/normal/02x` | service user `safi`, operator `admin` (locked), dirs |
| `config/hooks/normal/03x` | clones the repo, builds the venv, pre-warms embeddings, stages systemd units |
| `config/hooks/normal/04x` | reverse proxy, console branding, removes the policy-rc.d barrier |
| `config/includes.chroot/` | files shipped as-is into the installed system |
| `↳ usr/local/sbin/safi-firstboot` | the first-boot wizard driver |
| `↳ etc/systemd/system/safi-firstboot.service` | runs the wizard once, on tty1, before login |

## Design decisions

- **Bare metal, not Docker.** Production runs bare metal
  (`systemctl restart safi`), and the repo already ships the full systemd set.
  A container runtime on the ISO would only add weight.
- **bookworm.** Python 3.11 = the Dockerfile's default interpreter; a stable
  release live-build is tested against. Override with `SAFI_DIST` if desired.
- **Release tag pinned, not a branch.** The ISO carries what it ships; the ref
  lives in `config/includes.chroot/var/lib/safi-firstboot/build.env` (hooked in
  `030`) and is mirrored in `auto/config` for the label. docs/RELEASE_PROCESS.md
  requires production installs to pin a release + TCB fingerprint — the wizard
  offers the fingerprint pin via `setup.py`.
- **No credentials on the ISO.** `admin` starts locked; its password is set by
  the wizard each machine, so no two appliances share a backdoor.

## Known gaps / next steps

- **Scheduler and OAuth gateways** (`safi-scheduler`, `*-gateway`) are
  deliberately not enabled — they need SMTP / OAuth app registrations per site.
  Enable manually after first boot.
- **TLS.** The vhost is plain `:80`. Behind the wizard, run certbot or the
  operator's existing terminator.
- **Upgrades** follow DEPLOY_BAREMETAL step 10 (`git pull` + venv rebuild).
  Multi-ISO updates / apt repo are future work.
- **First real build is a validation milestone**: MySQL datadir initialisation
  and the live-installer rootfs copy are the two spots most likely to need a
  tweak the first time. Rebuild and re-test after any hook change.