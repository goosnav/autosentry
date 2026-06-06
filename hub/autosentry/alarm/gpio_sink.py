"""GPIO/relay-backed siren + strobe sink (ICD-4, FR-6). Lazy-imported by AlarmController
so the package imports on any dev machine. Not unit-tested — verified on the Jetson during
M2 bring-up against the wired siren/strobe.
"""

from __future__ import annotations

from autosentry.config import AlarmConfig


class GpioSink:
    """Drives siren_gpio / strobe_gpio via Jetson.GPIO (lazy)."""

    def __init__(self, config: AlarmConfig) -> None:
        self.cfg = config
        self._gpio = None

    def _ensure_gpio(self):
        if self._gpio is None:
            import Jetson.GPIO as GPIO  # hardware-only, lazy

            GPIO.setmode(GPIO.BOARD)
            for pin in (self.cfg.siren_gpio, self.cfg.strobe_gpio):
                if pin is not None:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            self._gpio = GPIO
        return self._gpio

    def _set(self, value: bool) -> None:
        gpio = self._ensure_gpio()
        level = gpio.HIGH if value else gpio.LOW
        for pin in (self.cfg.siren_gpio, self.cfg.strobe_gpio):
            if pin is not None:
                gpio.output(pin, level)

    def on(self) -> None:
        self._set(True)

    def off(self) -> None:
        self._set(False)

    def test(self) -> None:
        """Brief self-test pulse so an operator can confirm the wiring (FR-14 test mode)."""
        import time

        self._set(True)
        time.sleep(0.5)
        self._set(False)
