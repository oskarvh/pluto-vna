# Setup

Everything lives in a venv at `.venv/`. No system packages are installed and no `sudo` is
needed — libiio is built from source and installed *into the venv prefix*.

Prerequisites already present on this machine: `cmake`, `gcc`, `git`, and the libxml2 /
libusb-1.0 runtime + headers.

## 1. Pluto firmware — 2R2T

Done once, already applied to this unit. The original U-Boot environment is backed up in
[`hardware/uboot_env_backup.txt`](../hardware/uboot_env_backup.txt).

```sh
ssh root@192.168.2.1          # password: analog
fw_setenv compatible ad9361
fw_setenv mode 2r2t
reboot
```

The ADI wiki also tells you to set `attr_name`/`attr_val`. **Don't.** It is redundant —
`adi_loadvals` already does `fdt set ... compatible ${compatible}` — and it feeds an
ambiguous `test -n ${attr_val} = ad9364` branch that can silently force `mode` back to
`1r1t`. Leaving both undefined is the reliable recipe on this board.

To revert: `fw_setenv compatible ad9363a; fw_setenv mode 1r1t; reboot`.

Verified after reboot:

| | Before | After |
|---|---|---|
| `hw_model` | Rev.C (Z7010-AD9363A) | Rev.C (Z7010-**AD9361**) |
| RX data channels | `voltage0..1` (1 receiver) | `voltage0..3` (**2 receivers**) |
| DDS tones | TX1 only | TX1 + **TX2** |
| RX_LO range | 325–3800 MHz | **70–6000 MHz** |
| Sample rate | 2.08–61.44 MSPS | 2.08–**30.72** MSPS (halved by 2R2T) |

## 2. Host environment

```sh
python3 -m venv .venv
.venv/bin/pip install -U pip wheel

# libiio C library, built into the venv prefix
git clone --depth 1 -b v0.25 https://github.com/analogdevicesinc/libiio.git /tmp/libiio
cmake -S /tmp/libiio -B /tmp/libiio/build \
  -DCMAKE_INSTALL_PREFIX="$PWD/.venv" -DCMAKE_BUILD_TYPE=Release \
  -DWITH_SERIAL_BACKEND=OFF -DHAVE_DNS_SD=OFF -DWITH_TESTS=OFF \
  -DWITH_DOC=OFF -DWITH_MAN=OFF -DPYTHON_BINDINGS=OFF \
  -DWITH_IIOD=OFF -DINSTALL_UDEV_RULE=OFF
cmake --build /tmp/libiio/build -j"$(nproc)"
cmake --install /tmp/libiio/build

.venv/bin/pip install pylibiio pyadi-iio numpy scipy scikit-rf PyQt6 pyqtgraph
```

`pylibiio` is a pure-Python ctypes binding — it needs to `dlopen("libiio.so.0")`, which
would normally require `LD_LIBRARY_PATH`. Instead a `.pth` in site-packages preloads it
from the venv prefix by absolute path, so plain `.venv/bin/python` works with no
environment setup and nothing leaks outside the venv:

```sh
cat > .venv/lib/python3.12/site-packages/zz_libiio_preload.pth <<'EOF'
import ctypes, os, sys; _p = os.path.join(sys.prefix, "lib", "libiio.so.0"); os.path.exists(_p) and ctypes.CDLL(_p, mode=ctypes.RTLD_GLOBAL)
EOF
```

(`RTLD_GLOBAL` under the library's SONAME means pylibiio's later `CDLL("libiio.so.0")`
resolves to the already-loaded handle.)

### Installed versions

| Package | Version |
|---------|---------|
| libiio | 0.25 (`b6028fd`), backends: xml network ipv6 local usb |
| pyadi-iio | 0.0.21 |
| numpy / scipy | 2.5.2 / 1.18.0 |
| scikit-rf | 2.0.1 |
| PyQt6 / Qt | 6.11.0 |
| pyqtgraph | 0.14.0 |

## 3. Verify

```sh
.venv/bin/python tools/bringup.py info        # context, channel inventory, LO ranges
.venv/bin/python tools/bringup.py spectrum    # TX a tone, show what each RX sees
.venv/bin/python tools/bringup.py phasegate   # LO phase-coherence experiment
```
