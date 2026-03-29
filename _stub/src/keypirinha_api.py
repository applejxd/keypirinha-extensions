import sys
from unittest.mock import MagicMock

# Create a mock for the built-in C++ keypirinha_api module
# to allow stub packages to import 'keypirinha' without crashing.
sys.modules[__name__] = MagicMock()
