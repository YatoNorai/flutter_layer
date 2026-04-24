#!/usr/bin/env python3

import os
import re
import sys
import git
import fire
import yaml
import utils
import shutil
import tomllib
import subprocess
from loguru import logger
from pathlib import Path
from sysroot import Sysroot
from package import Package


class GitProgress(git.RemoteProgress):
    def update(self, op_code, cur_count, max_count=None, message=''):
        logger.trace(f"cloning {cur_count}/{max_count} {message}")


def _flutter_version_tuple(tag: str):
    clean = tag.lstrip('v')
    parts = re.split(r'[.\-]', clean)
    try:
        return tuple(int(x) for x in parts[:3])
    except ValueError:
        return (0, 0, 0)


@utils.record
class Build:
    @utils.recordm
    def __init__(self, conf='build.toml'):
        path = Path(__file__).parent
        conf = path/conf

        with open(conf, 'rb') as f:
            cfg = tomllib.load(f)

        # CLI / env-var overrides take precedence over build.toml values
        ndk = cfg['ndk'].get('path') or os.environ.get('ANDROID_NDK')
        api = cfg['ndk'].get('api')
        tag = (os.environ.get('FLUTTER_VERSION') or '').strip() or cfg['flutter'].get('tag')
        repo = cfg['flutter'].get('repo')
        root = cfg['flutter'].get('path')
        _arch = os.environ.get('FLUTTER_ARCH') or cfg['build'].get('arch')
        _mode = os.environ.get('FLUTTER_MODE') or cfg['build'].get('runtime')
        gclient = cfg['build'].get('gclient')
        sysroot = cfg['sysroot']
        syspath = sysroot.pop('path')
        package = cfg['package'].get('conf')
        release = cfg['package'].get('path')
        patches = cfg.get('patch')

        if not ndk:
            raise ValueError('neither ndk path nor ANDROID_NDK is set')
        if not tag:
            raise ValueError('require flutter tag')

        self.flutter_tag = tag
        self.api = api or 26
        self.conf = conf
        self.host = 'linux-x86_64'
        self.repo = repo or 'https://github.com/flutter/flutter'
        self.arch = [_arch] if isinstance(_arch, str) else (_arch or ['arm64'])
        self.mode = [_mode] if isinstance(_mode, str) else (_mode or ['release'])
        self.sysroot = Sysroot(path=path/syspath, **sysroot)
        self.root = path/root
        self.gclient = path/gclient
        self.release = path/release
        self.toolchain = Path(ndk, f'toolchains/llvm/prebuilt/{self.host}')
        self._version = _flutter_version_tuple(tag)

        if not self.release.parent.is_dir():
            raise ValueError(f'bad release path: "{release}"')

        with open(path/package, 'rb') as f:
            self.package = yaml.safe_load(f)

        if isinstance(patches, dict):
            self.patches = {}

            def patch(key):
                return lambda: self.patch(**self.patches[key])

            for k, v in patches.items():
                self.patches[k] = {
                    'file': path/v['file'],
                    'path': self.root/v['path']}
                self.__dict__[f'patch_{k}'] = patch(k)

    # Expose flutter_tag as a plain string for `python build.py flutter_tag`
    def config(self):
        info = (f'{k}\t: {v}' for k, v in self.__dict__.items() if k != 'package')
        logger.info('\n'+'\n'.join(info))

    def clone(self, *, url: str = None, tag: str = None, out: str = None):
        url = url or self.repo
        out = out or self.root
        tag = tag or self.flutter_tag
        progress = GitProgress()

        if utils.flutter_tag(out) == tag:
            logger.info('flutter exists, skip.')
            return
        elif os.path.isdir(out):
            logger.info(f'moving {out} to {out}.old ...')
            os.rename(out, f'{out}.old')

        try:
            git.Repo.clone_from(
                url=url,
                to_path=out,
                progress=progress,
                branch=tag)
        except git.exc.GitCommandError:
            raise RuntimeError('\n'.join(progress.error_lines))

    def sync(self, *, cfg: str = None, root: str = None):
        cfg = cfg or self.gclient
        src = root or self.root

        shutil.copy(cfg, os.path.join(src, '.gclient'))
        # --nohooks: skip gclient hooks; patches are applied manually after sync
        # Avoids hook failures when patches don't apply to unexpected versions
        cmd = ['gclient', 'sync', '-D', '--nohooks', '--no-history']
        result = subprocess.run(cmd, cwd=src)
        if result.returncode != 0:
            # Retry without --no-history (some older mirror servers don't support it)
            logger.warning('gclient sync with --no-history failed, retrying without it')
            cmd = ['gclient', 'sync', '-D', '--nohooks']
            subprocess.run(cmd, cwd=src, check=True)

        # Apply patches after all sources are present
        if hasattr(self, 'patches'):
            for k in self.patches:
                self.patch(**self.patches[k])

    def patch(self, *, file, path):
        repo = git.Repo(path)
        try:
            repo.git.apply([str(file)])
            logger.info(f'patch applied: {file}')
        except git.exc.GitCommandError as e:
            logger.warning(f'patch {file} may already be applied: {e}')

    def _gn_flags_for_version(self):
        """Extra GN flags adjusted per Flutter version for backward compatibility."""
        flags = []
        v = self._version

        if v >= (3, 7, 0):
            flags += ['--gn-args', 'dart_include_wasm_opt=false']

        if v >= (3, 0, 0):
            flags += ['--gn-args', 'dart_platform_sdk=false']

        if v >= (3, 10, 0):
            flags += [
                '--gn-args', 'dart_support_perfetto=false',
                '--gn-args', 'skia_use_perfetto=false',
            ]

        if v >= (3, 3, 0):
            flags += ['--no-build-embedder-examples']

        if v >= (3, 0, 0):
            flags += ['--no-prebuilt-dart-sdk']

        return flags

    def configure(
        self,
        arch: str,
        mode: str,
        api: int = 26,
        root: str = None,
        sysroot: str = None,
        toolchain: str = None,
    ):
        root = root or self.root
        sysroot = os.path.abspath(sysroot or self.sysroot.path)
        toolchain = os.path.abspath(toolchain or self.toolchain)
        api = api or self.api

        cmd = [
            'vpython3',
            'engine/src/flutter/tools/gn',
            '--linux',
            '--linux-cpu', arch,
            '--enable-fontconfig',
            '--no-goma',
            '--no-backtrace',
            '--clang',
            '--lto',
            '--no-enable-unittests',
            '--no-build-glfw-shell',
            '--target-toolchain', toolchain,
            '--runtime-mode', mode,
            '--gn-args', 'symbol_level=0',
            '--gn-args', 'arm_use_neon=false',
            '--gn-args', 'arm_optionally_use_neon=true',
            '--gn-args', 'is_desktop_linux=false',
            '--gn-args', 'use_default_linux_sysroot=false',
            '--gn-args', 'is_termux=true',
            '--gn-args', f'is_termux_host={utils.__TERMUX__}',
            '--gn-args', f'termux_api_level={api}',
            '--gn-args', f'custom_sysroot="{sysroot}"',
        ]

        if mode in ('release', 'profile'):
            cmd += ['--gn-args', 'strip_debug_info=true']

        cmd += self._gn_flags_for_version()

        subprocess.run(cmd, cwd=root, check=True, stdout=True, stderr=True)

    def build(self, arch: str, mode: str, root: str = None, jobs: int = None):
        root = root or self.root
        out = utils.target_output(root, arch, mode)
        cmd = ['ninja', '-C', out, 'flutter']
        if jobs:
            cmd.append(f'-j{jobs}')
        subprocess.run(cmd, check=True, stdout=True, stderr=True)

        if mode in ('release', 'profile'):
            self._strip_outputs(out)

    def _strip_outputs(self, out_dir: str):
        strip = self.toolchain / 'bin' / 'llvm-strip'
        out = Path(out_dir)
        targets = [
            'gen_snapshot', 'flutter_tester', 'impellerc',
            'libflutter_linux_gtk.so', 'libpath_ops.so', 'libtessellator.so',
        ]
        for name in targets:
            p = out / name
            if p.exists():
                try:
                    subprocess.run([str(strip), '--strip-unneeded', str(p)], check=True)
                    logger.info(f'stripped {name}')
                except subprocess.CalledProcessError:
                    logger.warning(f'strip failed for {name}')

    def debuild(self, arch: str, output: str = None, root: str = None, **conf):
        conf = conf or self.package
        root = root or self.root
        output = output or self.output(arch)

        pkg = Package(root=root, arch=arch, **conf)
        pkg.debuild(output=output)

    def output(self, arch: str):
        if self.release.is_dir():
            name = f'flutter_{self.flutter_tag}_{utils.termux_arch(arch)}.deb'
            return self.release/name
        else:
            return self.release

    def __call__(self):
        self.config()
        self.clone()
        self.sync()

        for arch in self.arch:
            self.sysroot(arch=arch)
            for mode in self.mode:
                self.configure(arch=arch, mode=mode)
                self.build(arch=arch, mode=mode)
            self.debuild(arch=arch, output=self.output(arch))


if __name__ == '__main__':
    logger.remove()
    logger.add(
        sys.stdout,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <9}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>")
        )
    fire.Fire(Build())
