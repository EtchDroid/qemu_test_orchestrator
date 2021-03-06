import asyncio
import re

from qemu_android_test_orchestrator.fsm import WorkerFSM, State, TransitionResult
from qemu_android_test_orchestrator.utils import kvm_available, Color, wait_shell_prompt, run_and_not_expect, \
    wait_exists, detect_package_manager, wait_shell_available

ansi_escape = re.compile(br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])')


class QemuSystemManager(WorkerFSM):
    @property
    def name(self) -> str:
        return 'QEMU manager'

    async def qemu_log_reader(self, log_tag: str, reader: asyncio.StreamReader, bufname: str):
        while not self.shared_state.qemu_sock_stopdebug:
            try:
                line = await asyncio.wait_for(reader.readline(), 1)
            except asyncio.exceptions.TimeoutError:
                continue
            setattr(self.shared_state, bufname, getattr(self.shared_state, bufname) + line)
            if self.shared_state.config['qemu_debug']:
                print(Color.YELLOW + f"{log_tag}:" + Color.RESET, ansi_escape.sub(b'', line).decode(errors="replace"),
                      end='')

    async def run_oneshot(self, command: str):
        writer = self.shared_state.qemu_serial_writer
        assert writer
        writer.write(command.encode(errors='replace') + b'\n')
        await writer.drain()

    async def disable_package(self, package):
        for mode in ('disable --user 0',):
            await self.run_oneshot(f'pm {mode} {package}')

    async def debloat(self):
        self.shared_state.qemu_serial_writer.write(b'(\n')
        for package in self.shared_state.config['disable_packages']:
            await self.disable_package(package)
        self.shared_state.qemu_serial_writer.write(b')\n')
        await wait_shell_prompt(self.shared_state)

    async def ensure_qemu(self) -> None:
        assert self.shared_state.config

        qemu_debug = self.shared_state.config['qemu_debug']
        qemu_args = list(self.shared_state.config['qemu_args'])
        kvm, decider = await kvm_available()
        if kvm:
            print(Color.GREEN + f"KVM is available (decider: {decider})" + Color.RESET)
        else:
            print(Color.RED + f"KVM is not available, performance may be very low (decider: {decider})" + Color.RESET)

        if not kvm and self.shared_state.config['qemu_force_kvm']:
            print(Color.YELLOW + "Ignoring and forcing KVM on as requested" + Color.RESET)
            kvm = True

        if kvm:
            if '-enable-kvm' not in qemu_args:
                qemu_args.insert(0, '-enable-kvm')
        else:
            # Make all timeouts 5 times longer
            self.shared_state.vm_timeout_multiplier = 5
            if '-enable-kvm' in qemu_args:
                qemu_args.remove('-enable-kvm')

        if qemu_debug:
            print(Color.YELLOW + "QEMU args:" + Color.RESET, " ".join(qemu_args))

        self.shared_state.qemu_proc = await asyncio.create_subprocess_exec(
            self.shared_state.config['qemu_bin'],
            *qemu_args,
            cwd=self.shared_state.config['qemu_workdir']
        )

        # Create serial and monitor consoles socket handle pairs
        await asyncio.sleep(1)
        self.shared_state.qemu_sock_stopdebug = False

        # Serial
        await wait_exists("/tmp/qemu-android.sock")
        reader, writer = await asyncio.open_unix_connection("/tmp/qemu-android.sock")
        self.shared_state.qemu_serial_reader = reader
        self.shared_state.qemu_serial_writer = writer
        self.shared_state.qemu_serial_buffer = b""
        asyncio.create_task(self.qemu_log_reader('VM', reader, 'qemu_serial_buffer'))
        print(Color.GREEN + "Connected to QEMU serial socket" + Color.RESET)

        # Monitor
        await wait_exists("/tmp/qemu-monitor.sock")
        reader, writer = await asyncio.open_unix_connection("/tmp/qemu-monitor.sock")
        self.shared_state.qemu_monitor_reader = reader
        self.shared_state.qemu_monitor_writer = writer
        self.shared_state.qemu_monitor_buffer = b""
        asyncio.create_task(self.qemu_log_reader('QEMU', reader, 'qemu_monitor_buffer'))
        print(Color.GREEN + "Connected to QEMU monitor socket" + Color.RESET)

        # Wait for a root shell to show up over serial
        found = await wait_shell_prompt(self.shared_state)
        if not found:
            print(Color.RED + "Warning: timeout while waiting for shell prompt" + Color.RESET)

        # Set terminal size
        await self.run_oneshot("stty cols 194")  # Travis "terminal" width
        await self.run_oneshot("stty rows 80")  # So that enough top output shows
        await wait_shell_prompt(self.shared_state)

        # Give it some other time to start zygote and all the bloat
        await asyncio.sleep(10 * self.shared_state.vm_timeout_multiplier)

        # Wait for package manager to be running
        if not await detect_package_manager(self.shared_state):
            print(Color.RED + "Warning: timeout waiting for package manager" + Color.RESET)
        else:
            print(Color.GREEN + "Package manager is running" + Color.RESET)

        await self.debloat()
        print(Color.GREEN + "System debloated" + Color.RESET)

        await asyncio.sleep(10)
        await wait_shell_prompt(self.shared_state)

        await wait_shell_available(self.shared_state)

        print(Color.GREEN + "VM processes (top)" + Color.RESET)
        self.shared_state.qemu_monitor_writer.write(b'top\n')
        await self.shared_state.qemu_monitor_writer.drain()
        await asyncio.sleep(2.7)
        self.shared_state.qemu_monitor_writer.write(b'q')
        await self.shared_state.qemu_monitor_writer.drain()

        await run_and_not_expect(b'ps -A | grep dex.oat\n', b'dex2oat', 40, self.shared_state)
        print(Color.GREEN + "dex2oat terminated" + Color.RESET)

        # Wait for boot animation to be over
        if not await run_and_not_expect(b'ps -A | grep bootanim\n', b'bootanimation', 40, self.shared_state):
            print(Color.RED + "Warning: timeout waiting for boot animation to stop" + Color.RESET)
        else:
            print(Color.GREEN + "Boot animation terminated" + Color.RESET)

    async def ensure_qemu_stopped(self) -> None:
        if not self.shared_state.qemu_proc or self.shared_state.qemu_proc.returncode:
            return
        self.shared_state.qemu_sock_stopdebug = True
        # Wait one second before killing QEMU to give time to the other workers to terminate gracefully
        await asyncio.sleep(1)
        self.shared_state.qemu_serial_writer.close()
        self.shared_state.qemu_monitor_writer.close()
        try:
            self.shared_state.qemu_proc.terminate()
        except ProcessLookupError:
            return
        await asyncio.sleep(0.2)
        if self.shared_state.qemu_proc.returncode is None:
            try:
                self.shared_state.qemu_proc.kill()
            except ProcessLookupError:
                pass

    async def enter_state(self, state: State) -> TransitionResult:
        if state == State.QEMU_UP:
            await asyncio.wait_for(self.ensure_qemu(), 60 * 25 * self.shared_state.vm_timeout_multiplier)
            return TransitionResult.DONE
        elif state == State.STOP:
            await asyncio.wait_for(self.ensure_qemu_stopped(), 10)
            return TransitionResult.DONE
        return TransitionResult.NOOP

    async def exit_state(self, state: State) -> TransitionResult:
        return TransitionResult.NOOP
