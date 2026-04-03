"""
Pytest configuration for tests.
Suppresses known benign warnings from dependencies.
"""

import warnings

# Suppress DeprecationWarning from Python's crypt module (imported by passlib)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="crypt")

# Suppress DeprecationWarning from argon2.cffi about __version__ access
warnings.filterwarnings("ignore", category=DeprecationWarning, message="Accessing argon2.__version__")
