# Flutter Layer IDE
![GitHub Release](https://img.shields.io/github/v/release/YatoNorai/flutter_layer)
![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/YatoNorai/flutter_layer/latest/total)

Run Flutter SDK inside [Layer IDE](https://github.com/YatoNorai/flutter_layer) — a custom Android terminal environment based on `com.layer.ide`.

## Install

Download `flutter_<version>_aarch64.deb` from the [releases](https://github.com/YatoNorai/flutter_layer/releases) page, then:

```bash
apt install /path/to/flutter_*.deb
```

> **Note:** `x11-repo` is **no longer required** to install Flutter.  
> It is only needed if you want to preview Flutter apps on a Linux display via `flutter run -d linux`.

Test your installation:

```bash
flutter doctor -v
```

## Flavors

### Android APK (recommended)

Build APKs directly from your Android device. Only arm64 artifacts are downloaded by default (fastest, no x86/arm errors):

```bash
flutter build apk --release
# or for a specific ABI:
flutter build apk --target-platform android-arm64
```

### Android device (USB/WiFi)

```bash
# List connected devices
flutter devices
flutter run -d <device_id>
```

### Web server

```bash
flutter run -d web-server --web-port 8080
# Open http://localhost:8080 in your browser
```

### Linux display (requires x11-repo)

```bash
# Install x11-repo first:
apt install x11-repo
apt install gtk3

export DISPLAY=:0
termux-x11 :0 >/dev/null 2>&1 &
flutter run -d linux
```

## Building from Source

### Requirements

- Python 3.11+
- Android NDK r27c or newer
- depot_tools
- gclient

```bash
pip install -r requirements.txt

# Build latest default version
python build.py

# Build a specific Flutter version
python build.py --flutter_version=3.22.0 --arch=arm64 --mode=release

# Build for arm (32-bit)
python build.py --flutter_version=3.10.0 --arch=arm --mode=release
```

### Configuration

Edit `build.toml` to change default version, architecture, and build mode:

```toml
[flutter]
tag = '3.29.2'    # default Flutter version

[build]
arch = ['arm64']  # arm, arm64, x64, x86
runtime = ['release']  # debug, release, profile
```

### Supported Flutter versions

| Flutter | Status       | Notes                           |
|---------|-------------|----------------------------------|
| 3.29.x  | ✅ Supported | Default                         |
| 3.22.x  | ✅ Supported |                                  |
| 3.16.x  | ✅ Supported |                                  |
| 3.10.x  | ✅ Supported |                                  |
| 3.7.x   | ✅ Supported | Limited gn flags                |
| 3.0.x   | ⚠️ Partial  | Some gn flags unavailable       |
| 2.x     | ⚠️ Legacy   | Use `LEGACY_GN=1` build flag    |

## Performance & Size Optimizations

This build applies the following optimizations over the original `termux-flutter`:

- **LTO** (Link-Time Optimization) for smaller, faster binaries
- **symbol_level=0** strips debug symbols from the engine
- **Release mode default** instead of debug
- **strip_debug_info=true** on release/profile builds
- **arm_optionally_use_neon=true** enables NEON SIMD on supported devices
- **FLUTTER_ANDROID_ABIS=arm64-v8a** limits APK artifact downloads to arm64

## Differences from termux-flutter

| Feature               | termux-flutter       | flutter_layer           |
|-----------------------|---------------------|--------------------------|
| Package ID            | `com.termux`        | `com.layer.ide`          |
| x11-repo required     | Yes (Pre-Depends)   | No (optional)            |
| Default build mode    | debug               | release                  |
| APK architecture      | arm + arm64 + x86   | arm64 only (configurable)|
| Flutter version input | Fixed in config     | Workflow input supported |
| Strip debug info      | No                  | Yes (release/profile)    |

## Notes

- Incompatible with **Android 14** (SELinux restrictions on exec in data dir)
- For ARM64-only devices (modern Android), use `--arch=arm64`
- Ensure `ANDROID_NDK` environment variable is set before building
