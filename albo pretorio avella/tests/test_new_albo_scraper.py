#!/usr/bin/env python3

import unittest

from new_albo_scraper import AlboScraper, infer_date, parse_date


class NewAlboScraperRegressionTests(unittest.TestCase):
    def test_infer_date_prefers_full_date(self):
        self.assertEqual(infer_date("pubblicato il 14/05/2026"), "14/05/2026")

    def test_infer_date_falls_back_to_year(self):
        self.assertEqual(infer_date("documento anno 2025"), "2025")

    def test_parse_date_supports_year_only(self):
        parsed = parse_date("2026")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 1)
        self.assertEqual(parsed.day, 1)

    def test_parse_allegati_field_literal_list(self):
        urls = AlboScraper._parse_allegati_field("['https://x/a.pdf', 'https://x/b.pdf']")
        self.assertEqual(urls, ["https://x/a.pdf", "https://x/b.pdf"])

    def test_parse_allegati_field_pipe_format(self):
        urls = AlboScraper._parse_allegati_field("https://x/a.pdf|https://x/b.pdf")
        self.assertEqual(urls, ["https://x/a.pdf", "https://x/b.pdf"])


if __name__ == "__main__":
    unittest.main()
