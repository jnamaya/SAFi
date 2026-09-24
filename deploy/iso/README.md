# SAFi Appliance — Debian ISO

Builds a bootable Debian ISO, Trixbox/Elastix style: the ISO boots the Debian
installer, installs a minimal headless system with SAFi baked in, and on
first boot presents a browser-based appliance setup page. No graphical desktop
or console login is required.

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

## First boot and browser setup

```bash
qemu-system-x86_64 -m 4096 -smp 2 -cdrom safi-appliance-v1.4.1-amd64.iso -boot d
```

After installation, the machine obtains an address using DHCP. The console
prints the address and a one-time six-digit setup PIN:

The console output on first boot is:

```text
SAFi Appliance is Active. Complete configuration at: https://192.168.1.42/
One-time setup PIN: 123456
```

Open the HTTPS address from a workstation, accept the locally generated
certificate warning, and enter the PIN, provider API key, and administrator
credentials. The setup service writes `.env`, initializes MariaDB, and sets the
OS `admin` account's password to the administrator password you entered, so one
password governs both the web admin login and SSH/console access. The SAFi
services are then enabled, and the setup service hands the console over to an
**always-on dashboard** (`safi-console.service`) that repaints tty1 every few
seconds with the management URL, service health, and operator hints. From this
point on, every reboot ends on that clean panel instead of the raw fsck/journal
boot tail. Replace the generated certificate under `/etc/ssl/runsafi/` with the
organization's trusted certificate before production use.

Operator access after setup:

- **SSH** — `admin@<appliance-ip>` (OpenSSH server ships enabled; host keys are
  generated on first boot). Password is the administrator password from setup.
- **Console** — tty1 shows the management URL and service status after setup.
  Local login from the dashboard is disabled; use SSH instead.

### `safi` operator CLI

Every operator task is a single `safi <command>` (no sudo needed for read-only
ops; `restart`/`backup`/`cert renew` escalate internally):

```
safi status                appliance + service state, management URL, cert
safi health                quick health probe (API + DB)
safi logs [unit]           tail journald for a unit (default: safi)
safi restart               restart the SAFi backend cleanly
safi backup                run a database backup now
safi backups               list backups on disk
safi cert [show|renew]     appliance TLS certificate (default: show)
safi update                pull latest release + rebuild venv (DEPLOY_BAREMETAL 10)
safi doctor                run the diagnostic checklist
safi help                  show this help
```

`admin` belongs to `adm`/`systemd-journal`, so `journalctl -u safi` works
without sudo. `safi doctor` is the first thing to run when anything looks off:
it checks `.env` ownership/perms, API health, every service, disk, and journal
readability.

The installer is configured not to contact Debian mirrors. The live ISO carries
the appliance root filesystem and runtime packages; network access is only
needed later if the operator chooses an online SAFi update.

## Installer flavor

`auto/config` embeds the **live** flavor of debian-installer. The installer
preseed ships as `config/includes.binary/preseed.cfg`, so it lands at the ISO
root (`/preseed.cfg`); 055-installer-initrd-preseed.binary additionally bakes
the same file into the installer initrd, and the boot entry passes
`preseed/file=/preseed.cfg` explicitly. The preseed lives in `includes.binary`
(not `config/preseed/`) on purpose: `lb chroot_preseed` feeds `config/preseed/`
through `debconf-set-selections` inside the build chroot, where d-i's netcfg
templates don't exist and `d-i … seen true` lines fail the build. The preseed also
enables `live-installer`, so the SAFi root filesystem assembled by live-build is
copied onto the target disk. A plain `netinst` image would install Debian but
omit the appliance payload.

The binary-stage boot hook replaces the generic live-build BIOS and UEFI menus
with one branded entry, `SAFi Appliance - unattended install`, plus a branded
boot splash (SAFi slate + green) on both ISOLINUX and GRUB. Live, rescue,
expert, and manual installer entries are intentionally omitted from the
distributed appliance ISO.

If you ever regenerate the ISO and boot into the menu manually, the entries are
`Start installer`, `^Install`, and — for one-shot assisted runs — the
`^Automated install` entry under `Advanced install options` (identical cmdline
to the preseeded default, historically used for debugging).

## Layout

| Path | Purpose |
|---|---|
| `build.sh` | entry point: `lb config` → `lb build`, renames the ISO |
| `auto/config` | live-build automation — distribution, arch, d-i mode, ISO labels |
| `config/includes.binary/preseed.cfg` | unattended debian-installer preseed (whole-disk install, no d-i user; shipped at ISO root) |
| `config/package-lists/` | daemon-free packages baked into the rootfs |
| `config/hooks/normal/01x` | installs mysql/apache/ssh behind a blocked-start policy |
| `config/hooks/normal/02x` | service user `safi`, operator `admin` (locked), dirs |
| `config/hooks/normal/03x` | clones the repo, builds the venv, pre-warms embeddings, stages systemd units |
| `config/hooks/normal/04x` | reverse proxy, console branding, removes the policy-rc.d barrier |
 | `config/includes.chroot/` | files shipped as-is into the installed system |
 | `↳ usr/local/sbin/safi-browser-setup.py` | one-time HTTPS setup service |
 | `↳ etc/systemd/system/safi-browser-setup.service` | displays IP/PIN and gates first boot |
 | `↳ usr/local/sbin/safi-console.py` | always-on tty1 dashboard (URL + service health); no local login |
 | `↳ etc/systemd/system/safi-console.service` | owns tty1 after setup completes |
 | `↳ usr/local/sbin/safi` | operator CLI (status/health/logs/restart/backup/cert/update/doctor) |

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
- **TLS.** HTTPS is served with a self-signed certificate generated on first
  boot (`/etc/ssl/runsafi/`). Replace it with the organization's trusted
  certificate before production use.
- **Upgrades** follow DEPLOY_BAREMETAL step 10 (`git pull` + venv rebuild) over
  SSH (`admin@<ip>`). Multi-ISO updates / apt repo are future work.
- **First real build is a validation milestone**: MySQL datadir initialisation
  and the live-installer rootfs copy are the two spots most likely to need a
  tweak the first time. Rebuild and re-test after any hook change.
