import json
import os
from _warnings import warn
from typing import TypeVar, Dict, Tuple, Callable

T = TypeVar('T')

_default_cfg = {
    'job_workdir': None,
    'job_command': './gradlew connectedAndroidTest',
    'virtwifi_hack': True,
    'virtwificonnector_apk': 'virtwificonnector-debug.apk',
    'permission_approve': True,
    'permission_approve_buttons': ['right', 'right', 'ret'],
    'vnc_recorder': False,
    'vnc_recorder_debug': False,
    'vnc_recorder_bin': None,
    'vnc_recorder_output': 'qemu_recording.mp4',
    'vnc_recorder_port': 5910,
    'qemu_workdir': None,
    'qemu_bin': f'qemu-system-{os.uname().machine}',
    'qemu_debug': False,
    'qemu_force_kvm': False,
    'logcat_output': None,
    'dmesg_output': None,
    'bugreport_output': None,
    'qemu_args': [
        # CPU
        '-cpu', 'host',
        '-smp', '2,cores=1,sockets=1,threads=2',

        # RAM
        '-m', '4096',

        # Linux
        '-kernel', 'kernel',
        '-append', 'root=/dev/ram0 androidboot.selinux=permissive androidboot.hardware=android_x86_64 console=ttyS0 '
                   'RAMDISK=vdb SETUPWIZARD=0 SETUPWIZARD=0 SETUPWIZARD=0',
        '-initrd', 'initrd.img',

        # Generic hardware
        '-audiodev', 'none,id=audionull', '-device', 'AC97,audiodev=audionull',
        '-netdev', 'user,id=network,hostfwd=tcp::5555-:5555',
        '-device', 'virtio-net-pci,netdev=network',
        '-chardev', 'socket,id=serial0,server,path=/tmp/qemu-android.sock',
        '-serial', 'chardev:serial0',
        '-chardev', 'socket,id=monitor0,server,path=/tmp/qemu-monitor.sock',
        '-monitor', 'chardev:monitor0',
        '-vga', 'qxl',
        '-display', 'vnc=127.0.0.1:10',
        #'-display', 'gtk,gl=on',

        # Drives and disk images
        '-drive', 'index=0,if=virtio,id=system,file=system.sfs,format=raw,readonly',
        '-drive', 'index=1,if=virtio,id=ramdisk,file=ramdisk.img,format=raw,readonly',
        '-drive', 'if=none,id=usbstick,file=usb.img,format=raw',

        # USB devices
        '-usb',
        '-device', 'usb-tablet,bus=usb-bus.0',
        '-device', 'nec-usb-xhci,id=xhci',  # Our emu USB stick is all 3.0 goodness
        '-device', 'usb-storage,id=usbdrive,bus=xhci.0,drive=usbstick',
    ],
    'disable_packages': [
        "com.google.android.ext.services",
        "com.google.android.googlequicksearchbox",
        "com.google.android.onetimeinitializer",
        "com.google.android.ext.shared",
        "com.google.android.setupwizard",
        "com.google.android.webview",
        "com.google.android.syncadapters.contacts",
        "com.google.android.packageinstaller",
        "com.google.android.partnersetup",
        "com.google.android.feedback",
        "com.google.android.printservice.recommendation",
        "com.google.android.syncadapters.calendar",
        "com.google.android.gsf.login",
        "com.google.android.backuptransport",
        "com.google.android.gms.setup",
        "com.google.android.apps.restore",
        "com.android.chrome",
        "com.android.vending",
        "com.google.android.gm",
        "com.google.android.gsf",
        "com.google.android.gms",
        "com.example.android.rssreader",
        "org.android_x86.analytics",
        "org.zeroxlab.util.tscal",
        "com.android.companiondevicemanager",
        "com.android.camera2",
        "com.android.gallery3d",
        "org.lineageos.eleven",
        "com.farmerbb.taskbar.androidx86",
        "com.android.captiveportallogin",
    ]
}


def noop(a: T) -> T:
    return a


def env_bool(val: str) -> bool:
    return bool(int(val))


def space_separated_values(val: str) -> list:
    return val.split(' ')


_environ_cfg: Dict[str, Tuple[str, Callable]] = {
    'job_workdir': ('JOB_WORKDIR', noop),
    'job_command': ('JOB_COMMAND', noop),
    'virtwifi_hack': ('VIRTWIFI_HACK', env_bool),
    'virtwificonnector_apk': ('VIRTWIFICONNECTOR_APK', noop),
    'permission_approve': ('PERMISSION_APPROVE', env_bool),
    'vnc_recorder': ('VNC_RECORDER', env_bool),
    'vnc_recorder_debug': ('VNC_RECORDER_DEBUG', env_bool),
    'vnc_recorder_bin': ('VNC_RECORDER_BIN', noop),
    'vnc_recorder_output': ('VNC_RECORDER_OUTPUT', noop),
    'vnc_recorder_port': ('VNC_RECORDER_PORT', int),
    'qemu_workdir': ('QEMU_WORKDIR', noop),
    'qemu_bin': ('QEMU_BIN', noop),
    'qemu_debug': ('QEMU_DEBUG', env_bool),
    'qemu_force_kvm': ('QEMU_FORCE_KVM', env_bool),
    'logcat_output': ('LOGCAT_OUTPUT', noop),
    'dmesg_output': ('DMESG_OUTPUT', noop),
    'bugreport_output': ('BUGREPORT_OUTPUT', noop)
}


def get_config() -> dict:
    cfg = _default_cfg.copy()

    cfg_file = os.environ.get("ORCHESTRATOR_CONFIG", 'config.json')
    if not os.access(cfg_file, os.R_OK):
        if 'ORCHESTRATOR_CONFIG' in os.environ:
            warn(f"Config file '{cfg_file}' does not exist or is not readable", ResourceWarning)
    else:
        with open(cfg_file) as f:
            cfg.update(json.load(f))

    for item, (var, converter) in _environ_cfg.items():
        if var in os.environ:
            cfg[item] = converter(os.environ[var])

    return cfg
