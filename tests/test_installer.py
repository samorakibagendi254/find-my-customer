from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.js"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for installer tests")
class InstallerTests(unittest.TestCase):
    def test_installer_replaces_existing_copy_and_preserves_complete_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            skills_dir = Path(temporary) / "skills"
            destination = skills_dir / "find-first-customers"
            destination.mkdir(parents=True)
            marker = destination / "old-version.txt"
            marker.write_text("old", encoding="utf-8")

            completed = subprocess.run(
                ["node", str(INSTALLER), "--skills-dir", str(skills_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse(marker.exists())
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertTrue((destination / "scripts" / "generate_report.py").is_file())
            self.assertFalse(any(skills_dir.glob(".find-first-customers.*")))

    def test_dry_run_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            skills_dir = Path(temporary) / "skills"
            completed = subprocess.run(
                ["node", str(INSTALLER), "--skills-dir", str(skills_dir), "--dry-run"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("Would install", completed.stdout)
            self.assertFalse(skills_dir.exists())


if __name__ == "__main__":
    unittest.main()

