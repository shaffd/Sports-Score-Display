import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from config import AppConfig, MatrixConfig
from outputs import MatrixOutput


class _Options:
    pass


class _Canvas:
    def Clear(self):
        pass


class _Matrix:
    width = 64
    height = 32

    def __init__(self, options):
        self.options = options

    def CreateFrameCanvas(self):
        return _Canvas()


class OutputTests(unittest.TestCase):
    def test_matrix_output_passes_bonnet_mapping_to_driver(self):
        fake_rgbmatrix = SimpleNamespace(
            RGBMatrix=_Matrix,
            RGBMatrixOptions=_Options,
        )
        config = AppConfig(
            output="matrix",
            matrix=MatrixConfig(hardware_mapping="adafruit-hat"),
        )

        with patch.dict(sys.modules, {"rgbmatrix": fake_rgbmatrix}):
            output = MatrixOutput(config)

        self.assertEqual(output.matrix.options.hardware_mapping, "adafruit-hat")


if __name__ == "__main__":
    unittest.main()
