"""Test the version service (no external dependencies)."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.version_service import version_info, read_version


class TestVersionService(unittest.TestCase):
    """Verify version_info() returns complete, valid data."""

    def test_version_info_required_fields(self):
        """version_info() returns dict with all required keys."""
        v = version_info()
        self.assertIsInstance(v, dict)
        self.assertIn('version', v)
        self.assertIn('commit', v)
        self.assertIn('build_date', v)
        self.assertIn('channel', v)

    def test_version_info_types(self):
        """All fields are strings."""
        v = version_info()
        self.assertIsInstance(v['version'], str)
        self.assertIsInstance(v['commit'], str)
        self.assertIsInstance(v['build_date'], str)
        self.assertIsInstance(v['channel'], str)

    def test_version_info_not_empty(self):
        """No field is an empty string."""
        v = version_info()
        self.assertTrue(len(v['version']) > 0, "version should not be empty")
        self.assertTrue(len(v['commit']) > 0, "commit should not be empty")
        self.assertTrue(len(v['build_date']) > 0, "build_date should not be empty")
        self.assertTrue(len(v['channel']) > 0, "channel should not be empty")

    def test_version_file_readable(self):
        """VERSION file can be read."""
        version = read_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_channel_valid_values(self):
        """Channel is either 'stable' or 'beta'."""
        v = version_info()
        self.assertIn(v['channel'], ('stable', 'beta'),
                      f"channel must be 'stable' or 'beta', got '{v['channel']}'")

    def test_commit_and_date_fallback(self):
        """commit and build_date should be either real values or 'unknown'."""
        v = version_info()
        # They should exist and not be None
        self.assertIsNotNone(v['commit'])
        self.assertIsNotNone(v['build_date'])
        # They should be non-empty strings
        self.assertIsInstance(v['commit'], str)
        self.assertIsInstance(v['build_date'], str)


if __name__ == '__main__':
    unittest.main()
