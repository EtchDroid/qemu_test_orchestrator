import asyncio

from qemu_android_test_orchestrator.fsm import WorkerFSM, State, TransitionResult


class PermissionDialogChecker(WorkerFSM):
    ensure_coro = None

    @property
    def name(self) -> str:
        return 'Permission approver'

    async def keypress(self, key: str) -> None:
        proc = await asyncio.create_subprocess_exec('adb', 'shell', 'input', 'keyboard', 'keyevent', 'KEYCODE_' + key)
        await proc.wait()
        await asyncio.sleep(0.3)

    async def approve_permission(self) -> None:
        # /me *shrugs*
        await self.keypress('DPAD_RIGHT')
        await self.keypress('DPAD_RIGHT')
        await self.keypress('ENTER')

    async def ensure_perms_approved(self) -> None:
        self.shared_state.adb_proc = await asyncio.create_subprocess_exec('adb', 'logcat',
                                                                          stdout=asyncio.subprocess.PIPE,
                                                                          stderr=asyncio.subprocess.STDOUT)
        assert self.shared_state.adb_proc.stdout  # so that mypy is happy
        line = await self.shared_state.adb_proc.stdout.readline()
        while line:
            if b'USB-PERMISSION' in line:
                if b'USB-PERMISSION-REQUESTED' in line:
                    await self.approve_permission()
                self.shared_state.adb_proc.kill()
                return
            line = await self.shared_state.adb_proc.stdout.readline()

        await self.shared_state.adb_proc.wait()

    async def enter_state(self, state: State) -> TransitionResult:
        if state == State.JOB:
            self.ensure_coro = asyncio.create_task(self.ensure_perms_approved())
            await self.ensure_coro
            self.ensure_coro = None
            return TransitionResult.DONE
        elif state == State.STOP:
            ret = TransitionResult.NOOP
            if self.shared_state.adb_proc and self.shared_state.adb_proc.returncode is None:
                try:
                    self.shared_state.adb_proc.kill()
                    ret = TransitionResult.DONE
                except ProcessLookupError:
                    pass
            if self.ensure_coro:
                self.ensure_coro.cancel()
                ret = TransitionResult.DONE
            return ret
        return TransitionResult.NOOP

    async def exit_state(self, state: State) -> TransitionResult:
        return TransitionResult.NOOP