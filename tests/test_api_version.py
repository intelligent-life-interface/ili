"""Test that the /api/version route matches the version service directly.

The field/type/fallback checks already live in test_version_service.py —
duplicating them here just for the API wrapper adds nothing.
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.version_service import version_info
from app.api.version import get_version


class TestVersionAPI(unittest.TestCase):
    """Verify /api/version serves the same data as version_info()."""

    def test_api_get_version_endpoint(self):
        """The /api/version route returns the same data as version_info()."""
        api_response = get_version()
        direct_response = version_info()
        self.assertEqual(api_response, direct_response)


if __name__ == '__main__':
    unittest.main()
