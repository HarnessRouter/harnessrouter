import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("badge", Path(__file__).with_name("update-star-badge.py"))
badge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(badge)


class BadgeTests(unittest.TestCase):
    def test_valid_svg_and_exact_counts(self):
        for count in [0, 1213, 123456, 999999999]:
            root = ET.fromstring(badge.render(count))
            self.assertEqual(root.attrib["aria-label"], f"Stars: {count}")
            self.assertGreaterEqual(int(root.attrib["width"]), 117)
            labels = list(root.iter("{http://www.w3.org/2000/svg}text"))
            self.assertEqual(labels[-1].text, str(count))
            self.assertEqual(labels[-1].attrib["fill"], "white")

    def test_invalid_data_rejected(self):
        for value in [None, True, -1, "1213", 1.5, 1000000000]:
            with self.assertRaises(ValueError):
                badge.render(value)

    def test_update_and_no_change(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "badge.svg"
            for expected in [True, False]:
                with patch.object(badge, "urlopen", return_value=io.BytesIO(b'{"stargazers_count":1213}')):
                    self.assertEqual(badge.update(output), expected)
            self.assertIn("Stars: 1213", output.read_text())

    def test_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "badge.svg"
            output.write_text("last-good")
            for result in [URLError("unavailable"), io.BytesIO(b'{"message":"rate limited"}'), io.BytesIO(b'{"stargazers_count":null}')]:
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with patch.object(badge, "urlopen", **kwargs):
                    with self.assertRaises((URLError, KeyError, ValueError)):
                        badge.update(output)
                self.assertEqual(output.read_text(), "last-good")


if __name__ == "__main__":
    unittest.main()
