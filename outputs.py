"""Output adapters for laptop preview and HZeller LED matrices."""

from __future__ import annotations

import time
from typing import Protocol

from PIL import Image

from config import AppConfig


class DisplayClosed(Exception):
    """Raised when the user closes the preview window."""


class DisplayOutput(Protocol):
    width: int
    height: int

    def show(self, image: Image.Image, duration: float) -> None: ...

    def close(self) -> None: ...


class PreviewOutput:
    """Optional Tkinter preview; Tkinter is imported only in preview mode."""

    def __init__(self, width: int, height: int, scale: int = 8) -> None:
        import tkinter as tk
        from PIL import ImageTk

        self._tk = tk
        self._image_tk = ImageTk
        self.width = width
        self.height = height
        self.scale = scale
        self.closed = False

        self.root = tk.Tk()
        self.root.title("Sports Score Display Preview")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.geometry(f"{width * scale}x{height * scale}")
        self.label = tk.Label(self.root, background="black")
        self.label.pack(expand=True, fill="both")
        self._photo = None

    def _on_close(self) -> None:
        self.closed = True
        try:
            self.root.destroy()
        except self._tk.TclError:
            pass

    def show(self, image: Image.Image, duration: float) -> None:
        if self.closed:
            raise DisplayClosed
        resampling = getattr(Image, "Resampling", Image).NEAREST
        scaled = image.resize(
            (self.width * self.scale, self.height * self.scale), resampling
        )
        self._photo = self._image_tk.PhotoImage(scaled)
        self.label.configure(image=self._photo)

        end = time.monotonic() + duration
        while time.monotonic() < end:
            if self.closed:
                raise DisplayClosed
            try:
                self.root.update_idletasks()
                self.root.update()
            except self._tk.TclError as exc:
                self.closed = True
                raise DisplayClosed from exc
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))

    def close(self) -> None:
        if not self.closed:
            self._on_close()


class MatrixOutput:
    """HZeller rgbmatrix adapter using Pillow's fast whole-frame SetImage path."""

    def __init__(self, config: AppConfig) -> None:
        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
        except ImportError as exc:
            raise RuntimeError(
                "rgbmatrix is not installed. Run setup_pi.sh on the Raspberry Pi."
            ) from exc

        matrix_config = config.matrix
        options = RGBMatrixOptions()
        options.rows = matrix_config.rows
        options.cols = matrix_config.cols
        options.chain_length = matrix_config.chain_length
        options.parallel = matrix_config.parallel
        options.brightness = matrix_config.brightness
        options.hardware_mapping = matrix_config.hardware_mapping
        options.gpio_slowdown = matrix_config.gpio_slowdown
        options.pwm_bits = matrix_config.pwm_bits
        options.pwm_lsb_nanoseconds = matrix_config.pwm_lsb_nanoseconds
        options.pwm_dither_bits = matrix_config.pwm_dither_bits
        options.scan_mode = matrix_config.scan_mode
        options.multiplexing = matrix_config.multiplexing
        options.row_address_type = matrix_config.row_address_type
        options.led_rgb_sequence = matrix_config.led_rgb_sequence
        options.show_refresh_rate = matrix_config.show_refresh_rate
        options.drop_privileges = matrix_config.drop_privileges
        if matrix_config.pixel_mapper_config:
            options.pixel_mapper_config = matrix_config.pixel_mapper_config
        if matrix_config.panel_type:
            options.panel_type = matrix_config.panel_type

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()
        self.width = self.matrix.width
        self.height = self.matrix.height

    def show(self, image: Image.Image, duration: float) -> None:
        frame = image.convert("RGB")
        if frame.size != (self.width, self.height):
            resampling = getattr(Image, "Resampling", Image).NEAREST
            frame = frame.resize((self.width, self.height), resampling)
        self.canvas.Clear()
        self.canvas.SetImage(frame)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        time.sleep(duration)

    def close(self) -> None:
        self.matrix.Clear()


def create_output(config: AppConfig) -> DisplayOutput:
    if config.output == "matrix":
        return MatrixOutput(config)
    return PreviewOutput(
        config.canvas.width,
        config.canvas.height,
        config.preview_scale,
    )
