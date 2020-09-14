import asyncio
import base64
import os
from typing import cast

from qemu_android_test_orchestrator.fsm import WorkerFSM, State, TransitionResult
from qemu_android_test_orchestrator.utils import wait_shell_prompt


class VirtWifiManager(WorkerFSM):
    @property
    def name(self) -> str:
        return 'VirtWifi enabler'

    async def ensure_virtwifi(self) -> None:
        assert self.shared_state.config
        apk_file = self.shared_state.config['virtwificonnector_apk']
        if not os.access(apk_file, os.R_OK):
            raise OSError(f"VirtWifiConnector APK path '{apk_file}' does not exist or is inaccessible")
        with open(apk_file, 'rb') as f:
            apk_b64 = base64.standard_b64encode(f.read())

        serial = self.shared_state.qemu_sock_writer
        assert serial

        # Turn on wi-fi
        serial.write(b'svc wifi enable\n')
        await serial.drain()
        await asyncio.sleep(0.5)
        await wait_shell_prompt(self.shared_state)

        # Send app apk
        serial.write(b'base64 -d > /data/local/tmp/app.apk << EOF\n')
        # Send the base64 string in 1KB chunks cause Python and Busybox are little cry babies
        chunk_size = 1024
        for i in range(0, len(apk_b64), chunk_size):
            serial.write(apk_b64[i:i + chunk_size] + b'\n')
            await serial.drain()
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)
        serial.write(b'EOF\n')
        await serial.drain()
        await asyncio.sleep(1)
        await wait_shell_prompt(self.shared_state)

        # Install app
        serial.write(b'pm install /data/local/tmp/app.apk\n')
        await serial.drain()
        await asyncio.sleep(0.5)
        await wait_shell_prompt(self.shared_state)

        # We like our RAM
        serial.write(b'rm /data/local/tmp/app.apk\n')
        await serial.drain()
        await asyncio.sleep(0.5)
        await wait_shell_prompt(self.shared_state)

        # Open app
        serial.write(b'am start -a android.intent.action.MAIN -n '
                     b'eu.depau.virtwificonnector/.MainActivity\n')
        await serial.drain()
        await asyncio.sleep(3)
        await wait_shell_prompt(self.shared_state)

        # Dismiss "old API" warning
        serial.write(b'input keyevent KEYCODE_ESCAPE\n')
        await serial.drain()
        await asyncio.sleep(0.5)
        await wait_shell_prompt(self.shared_state)

        await asyncio.sleep(5)

    async def enter_state(self, state: State) -> TransitionResult:
        if state == State.NETWORK_UP:
            await asyncio.wait_for(self.ensure_virtwifi(), 90 * self.shared_state.vm_timeout_multiplier)
            return TransitionResult.DONE
        return TransitionResult.NOOP

    async def exit_state(self, state: State) -> TransitionResult:
        return TransitionResult.NOOP
