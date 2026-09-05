"""Tests for the Instagram export pipeline. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import brain_mine  # noqa: E402
import e7_clients  # noqa: E402
import e11_copilot  # noqa: E402
import signals  # noqa: E402
import taste_signals  # noqa: E402
import build_taste_test  # noqa: E402
from ig_export import demojibake, load_export  # noqa: E402
from make_fixture import build  # noqa: E402


class TestDemojibake(unittest.TestCase):
    def test_recovers_georgian(self):
        real = "გამარჯობა, ეს კაბა თუ არის M ზომაში?"
        broken = real.encode("utf-8").decode("latin-1")
        self.assertNotEqual(broken, real)
        self.assertEqual(demojibake(broken), real)

    def test_leaves_clean_text_alone(self):
        self.assertEqual(demojibake("hello"), "hello")
        self.assertEqual(demojibake(""), "")


class TestSignals(unittest.TestCase):
    def test_phone_formats(self):
        self.assertEqual(signals.find_phones("ნომერი 555123456"), ["555123456"])
        self.assertEqual(signals.find_phones("+995 599 12-34-56"), ["599123456"])
        self.assertEqual(signals.find_phones("577 12 34 56"), ["577123456"])

    def test_phone_false_positives(self):
        self.assertEqual(signals.find_phones("ტრეკინგი GE123456789DE"), [])
        self.assertEqual(signals.find_phones("ფასი 320 ლარი"), [])
        self.assertEqual(signals.find_phones("კოდი 5551234567"), [])

    def test_sizes(self):
        self.assertIn("M", signals.find_sizes("M ზომა მინდა"))
        self.assertIn("38", signals.find_sizes("38 ზომა"))

    def test_stages_and_cancel(self):
        self.assertIn("awaiting_payment", signals.stage_hits("ჩავრიცხე თანხა"))
        self.assertEqual(signals.cancel_reason("ძვირია, გადავიფიქრე"), "გადაიფიქრა")
        self.assertIsNone(signals.cancel_reason("მადლობა"))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        build(cls.root / "export", thread_count=40)
        cls.threads = load_export(cls.root / "export")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_loads_every_thread(self):
        self.assertEqual(len(self.threads), 40)
        self.assertTrue(all(t.messages for t in self.threads))

    def test_owner_detected_and_sides_split(self):
        t = self.threads[0]
        self.assertEqual(t.owner, "Catwalk")
        self.assertTrue(t.by_client())
        self.assertTrue(t.by_owner())
        self.assertEqual(len(t.by_client()) + len(t.by_owner()), len(t.messages))

    def test_messages_sorted_oldest_first(self):
        for t in self.threads:
            stamps = [m.timestamp_ms for m in t.messages]
            self.assertEqual(stamps, sorted(stamps))

    def test_e7_one_row_per_client(self):
        rows = e7_clients.build_rows(self.threads)
        self.assertEqual(len(rows), 40)
        self.assertEqual(len({r["ig_username"] for r in rows}), 40)
        self.assertEqual(set(rows[0]), set(e7_clients.FIELDS))
        out = e7_clients.write(rows, self.root / "out" / "clients.csv")
        self.assertTrue(out.exists())

    def test_e11_selects_twenty_across_categories(self):
        selected = e11_copilot.select(self.threads)
        self.assertEqual(len(selected), 20)
        self.assertEqual(len({t.thread_id for _c, t in selected}), 20)
        self.assertGreaterEqual(len({c for c, _t in selected}), 2)
        index = e11_copilot.write(selected, self.root / "out" / "copilot")
        self.assertTrue(index.exists())
        self.assertEqual(len(list(index.parent.glob("chat-*.md"))), 20)

    def test_e11_prefers_readable_chats(self):
        # A seller has to read each one; a 1200-message thread is not a test item.
        selected = e11_copilot.select(self.threads)
        for _category, t in selected:
            self.assertLessEqual(len(t.messages), e11_copilot.MAX_MESSAGES)

    def test_e7_repeat_buyer_needs_two_order_months(self):
        # One client has one Instagram thread forever, so repeat purchases sit
        # inside it: months, not threads, separate the repeat buyer.
        rows = {r["ig_username"]: r for r in e7_clients.build_rows(self.threads)}
        for row in rows.values():
            if row["segment_hint"] == "განმეორებითი":
                self.assertGreaterEqual(int(row["order_months"]), 2)
            elif row["segment_hint"] == "მყიდველი":
                self.assertEqual(int(row["order_months"]), 1)

    def test_e7_rows_are_per_conversation(self):
        # Distinct people share display names like "." -- grouping by name
        # would merge them into one impossible client.
        rows = e7_clients.build_rows(self.threads)
        self.assertEqual(len(rows), len(self.threads))

    def test_e11_respects_smaller_corpus(self):
        selected = e11_copilot.select(self.threads[:5])
        self.assertLessEqual(len(selected), 5)

    def test_brain_templatizes_variables(self):
        self.assertEqual(
            brain_mine.templatize("ტრეკინგი: GE123456789DE"), "ტრეკინგი: {ტრეკინგი}"
        )
        self.assertIn("{თანხა}", brain_mine.templatize("ჯამში 320 ლარი"))

    def test_brain_masks_bank_account(self):
        # An IBAN must never survive into a reusable template.
        out = brain_mine.templatize("ანგარიში GE59TB7353845064300106")
        self.assertNotIn("GE59TB7353845064300106", out)
        self.assertIn("{ანგარიში}", out)

    def test_brain_finds_repeats(self):
        mined = brain_mine.mine(self.threads)
        self.assertTrue(mined["questions"])
        self.assertTrue(mined["answers"])
        self.assertTrue(all(n >= brain_mine.MIN_REPEATS for _k, n, _s in mined["answers"]))
        out = brain_mine.write(mined, len(self.threads), self.root / "out" / "brain.md")
        self.assertTrue(out.exists())


HTML_THREAD = """<html><head><title>test_client</title></head><body>
<div class="pam _a6-g uiBoxWhite"><h2 class="_a6-h _a6-i">CATWALK</h2>
<div class="_a6-p"><div>gamarjoba, 370 lari</div>
<ul class="_a6-q"><li><span>reaction_should_be_ignored</span></li></ul></div>
<div class="_a6-o">Aug 31, 2026 4:34 am</div></div>
<div class="pam _a6-g uiBoxWhite"><h2 class="_a6-h _a6-i">test_client</h2>
<div class="_a6-p"><div>Gamarjoba ra ghirs?</div></div>
<div class="_a6-o">Aug 31, 2026 1:10 am</div></div>
<div class="pam _a6-g uiBoxWhite"><h2 class="_a6-h _a6-i">test_client</h2>
<div class="_a6-p"><div>Liked a message</div></div>
<div class="_a6-o">Aug 31, 2026 1:36 am</div></div>
<div class="pam _a6-g uiBoxWhite"><h2 class="_a6-h _a6-i">CATWALK</h2>
<div class="_a6-p"><div><a href="your_instagram_activity/messages/inbox/test_client_123/photos/9.jpg">
<img src="your_instagram_activity/messages/inbox/test_client_123/photos/9.jpg" /></a></div></div>
<div class="_a6-o">Aug 31, 2026 2:00 am</div></div>
</body></html>"""


class TestHtmlExport(unittest.TestCase):
    """The HTML flavour of the export, which is what Instagram actually sent."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        thread_dir = self.root / "inbox" / "test_client_123"
        thread_dir.mkdir(parents=True)
        (thread_dir / "message_1.html").write_text(HTML_THREAD, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_parses_messages_and_skips_system_rows(self):
        threads = load_export(self.root)
        self.assertEqual(len(threads), 1)
        # "Liked a message" is a reaction row, not a message; the photo card is.
        self.assertEqual(len(threads[0].messages), 3)

    def test_reactions_are_not_message_text(self):
        threads = load_export(self.root)
        self.assertNotIn("reaction_should_be_ignored", threads[0].text)

    def test_messages_ordered_oldest_first(self):
        t = load_export(self.root)[0]
        self.assertEqual(t.messages[0].text, "Gamarjoba ra ghirs?")

    def test_owner_is_the_side_that_is_not_the_thread_title(self):
        t = load_export(self.root)[0]
        self.assertEqual(t.owner, "CATWALK")
        self.assertEqual(len(t.by_client()), 1)

    def test_photo_paths_are_kept(self):
        # The export's own photo files are the only product images we have,
        # so the path has to survive parsing, not just a has_media flag.
        t = load_export(self.root)[0]
        shots = [m for m in t.messages if m.photos]
        self.assertEqual(len(shots), 1)
        self.assertTrue(shots[0].has_media)
        self.assertEqual(shots[0].photos,
                         ["your_instagram_activity/messages/inbox/test_client_123/photos/9.jpg"])

    def test_latin_script_georgian_is_recognised(self):
        # Clients type Georgian in Latin letters; the signals must catch it.
        self.assertTrue(signals.is_question("Gamarjoba shox r4 ebi ra ghirs?"))
        self.assertIn("awaiting_payment", signals.stage_hits("chavricxe tanxa"))
        self.assertIn("arrived", signals.stage_hits("rodis chamova?"))
        self.assertEqual(signals.cancel_reason("dzviria, gadavipiqre"), "გადაიფიქრა")


class TestTasteSignals(unittest.TestCase):
    """Story mentions are the only item id the DM history carries."""

    def _thread(self, texts):
        from ig_export import Message, Thread
        msgs = [Message(sender=s, timestamp_ms=1_750_000_000_000 + i * 60_000, text=x)
                for i, (s, x) in enumerate(texts)]
        return Thread(thread_id="t1", title="client", participants=["client", "CATWALK"],
                      messages=msgs, source=Path("x"), owner="CATWALK")

    def test_counts_ask_and_conversion(self):
        t = self._thread([
            ("client", "ra ghirs? https://www.instagram.com/stories/catwalk.ge/111"),
            ("CATWALK", "370 ლარი"),
            ("client", "minda"),
            ("CATWALK", "ნივთი ჩამოვიდა, ჩაირიცხოს თანხა"),
        ])
        items = taste_signals.analyse([t])
        self.assertIn("111", items)
        self.assertEqual(items["111"]["asks"], 1)
        self.assertEqual(items["111"]["converted"], 1)

    def test_weight_fee_is_not_the_item_price(self):
        t = self._thread([
            ("client", "https://www.instagram.com/stories/catwalk.ge/222"),
            ("CATWALK", "წონის ტარიფი 26 ლარი"),
            ("CATWALK", "კაბის ფასია 319 ლარი"),
        ])
        items = taste_signals.analyse([t])
        self.assertEqual(items["222"]["prices"], [319])


class TestBuildTasteTest(unittest.TestCase):
    """The 100-item test must stay balanced and free of duplicates."""

    def test_brand_extraction(self):
        self.assertEqual(build_taste_test.brand_of("sandro black bag"), "sandro")
        self.assertEqual(build_taste_test.brand_of("უცნობი ნივთი"), "")

    def test_core_spreads_across_brands(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "s.csv"
            import csv as _csv
            with sheet.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=["", "ნივთი", "ზომა", "ლინკი",
                                                    "გასაყიდი ₾", "Markup %", "ბრენდი"])
                w.writeheader()
                for i in range(20):
                    w.writerow({"": "✅ დასრულდა", "ნივთი": f"sandro bag {i}", "ზომა": "s",
                                "ლინკი": "http://x", "გასაყიდი ₾": 100 + i,
                                "Markup %": "50", "ბრენდი": "Catwalk"})
                for i in range(20):
                    w.writerow({"": "✅ დასრულდა", "ნივთი": f"nike shoes {i}", "ზომა": "40",
                                "ლინკი": "http://y", "გასაყიდი ₾": 200 + i,
                                "Markup %": "60", "ბრენდი": "Catwalk Men"})
            rows = build_taste_test.core_rows(sheet, 10)
            self.assertEqual(len(rows), 10)
            self.assertEqual(len({r["name"] for r in rows}), 10)
            # Both brands present, not ten of one.
            self.assertGreaterEqual(len({r["label"] for r in rows}), 2)

    def test_cancelled_orders_are_not_evidence_of_taste(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "s.csv"
            import csv as _csv
            with sheet.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=["", "ნივთი", "ლინკი",
                                                    "გასაყიდი ₾", "Markup %", "ბრენდი"])
                w.writeheader()
                w.writerow({"": "⛔ გაუქმდა", "ნივთი": "gucci bag", "ლინკი": "http://x",
                            "გასაყიდი ₾": "500", "Markup %": "50", "ბრენდი": "Catwalk"})
                w.writerow({"": "✅ დასრულდა", "ნივთი": "prada bag", "ლინკი": "http://y",
                            "გასაყიდი ₾": "500", "Markup %": "50", "ბრენდი": "Catwalk"})
            rows = build_taste_test.core_rows(sheet, 10)
            self.assertEqual([r["label"] for r in rows], ["prada"])


class TestEmptyExport(unittest.TestCase):
    def test_empty_directory_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_export(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
