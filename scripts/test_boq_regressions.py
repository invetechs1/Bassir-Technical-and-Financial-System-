"""Focused BoQ safety regressions; no database or network required."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.boq_parser import parse_boq_from_text, price_project_boq, enforce_project_boq, _best_match, confirm_edited_quantities
from app.proposal_builder import compute_financials
from app.file_extract import extract_text


class BoQRegressions(unittest.TestCase):
    def test_reordered_columns(self):
        for header, row in [
            ("الوصف | الوحدة | سعر الوحدة | الكمية | الإجمالي", "وحدات إنارة LED | عدد | 250 | 40 | 10000"),
            ("الكمية | الإجمالي | الوصف | سعر الوحدة | الوحدة", "40 | 10000 | وحدات إنارة LED | 250 | عدد"),
            ("description | unit | rate | qty | total", "LED lighting | عدد | 250 | 40 | 10000"),
        ]:
            with self.subTest(header=header):
                self.assertEqual(parse_boq_from_text(header + "\n" + row)[0]["qty"], 40)

    def test_zero_and_small_tables_survive(self):
        rows = "الوصف | الوحدة | الكمية\nأعمال إنارة الموقع | عدد | 40\nكاميرات أمن الموقع | عدد | 15\nلوحة تحكم الموقع | عدد | 0"
        items = parse_boq_from_text(rows)
        self.assertEqual([i["qty"] for i in items], [40, 15, 0])
        with patch("app.database.list_price_items", return_value=[]), patch("app.boq_parser._market_price", return_value=None):
            for priced in (price_project_boq(items), enforce_project_boq([], items)):
                priced[-1]["unit_price"] = 4500
                compute_financials(priced, {"vat_rate": 15})
                self.assertEqual(priced[-1]["qty"], 0)
                self.assertEqual(priced[-1]["total"], 0)
                self.assertIn("quantity_issue", priced[-1])
        self.assertEqual(len(parse_boq_from_text(rows.split("\nلوحة")[0])), 2)

    def test_missing_quantity_never_uses_price(self):
        for qty in ("", "TBD", "-", "-1"):
            item = parse_boq_from_text("الوصف | الوحدة | الكمية | سعر الوحدة\nأعمال إنارة الموقع | عدد | " + qty + " | 250")[0]
            self.assertEqual(item["qty"], 0)
            self.assertIn("quantity_issue", item)

    def test_headerless_ambiguous_rows_require_review(self):
        items = parse_boq_from_text("\n".join("أعمال إنارة الموقع | عدد | 250 | 40 | 10000" for _ in range(3)))
        self.assertTrue(all(i["qty"] == 0 and i.get("quantity_issue") for i in items))
        self.assertEqual(parse_boq_from_text("نلتزم بتنفيذ المشروع خلال 12 شهراً."), [])

    def test_arabic_numbers(self):
        item = parse_boq_from_text("الوصف | الوحدة | الكمية\nأعمال إنارة الموقع | عدد | ١٬٢٣٤٫٥")[0]
        self.assertEqual(item["qty"], 1234.5)

    def test_document_boundaries_reset_columns(self):
        text = "الوصف | الوحدة | سعر الوحدة | الكمية\nأعمال إنارة الموقع | عدد | 250 | 40\n===== الملف: next.txt =====\nالوصف | الوحدة | الكمية\nكاميرات أمن الموقع | عدد | 15"
        self.assertEqual([i["qty"] for i in parse_boq_from_text(text)], [40, 15])

    def test_empty_serial_cell_preserved(self):
        text = "م | الوصف | الوحدة | سعر الوحدة | الكمية\n | أعمال إنارة الموقع | عدد | 250 | 40"
        self.assertEqual(parse_boq_from_text(text)[0]["qty"], 40)

    def test_empty_edge_tab_cells_preserved(self):
        text = "م\tالوصف\tالوحدة\tالكمية\tسعر الوحدة\n\tأعمال إنارة الموقع\tعدد\t40\t250"
        row = parse_boq_from_text(text)[0]
        self.assertEqual((row["name"], row["qty"]), ("أعمال إنارة الموقع", 40))
        text = "الوصف\tالوحدة\tسعر الوحدة\tالكمية\nأعمال إنارة الموقع\tعدد\t250\t"
        row = parse_boq_from_text(text)[0]
        self.assertEqual(row["qty"], 0)
        self.assertIn("quantity_issue", row)

    def test_incomplete_space_rows_require_review(self):
        for header, row in [
            ("الوصف  الوحدة  الكمية  سعر الوحدة", "أعمال إنارة الموقع  عدد      250"),
            ("الوصف  الوحدة  سعر الوحدة  الكمية", "أعمال إنارة الموقع  عدد  250"),
        ]:
            item = parse_boq_from_text(header + "\n" + row)[0]
            self.assertEqual(item["qty"], 0)
            self.assertIn("quantity_issue", item)

    def test_total_words_inside_descriptions_are_preserved(self):
        for word in ("الإجمالي", "المجموع"):
            name = "توريد وتركيب عداد لقياس " + word + " للكهرباء"
            items = parse_boq_from_text("الوصف | الوحدة | الكمية\n" + name + " | عدد | 1")
            self.assertEqual([i["name"] for i in items], [name])

    def test_standalone_total_labels_are_excluded(self):
        for label in ("الإجمالي", "الإجمالي العام", "المجموع", "Total", "Subtotal", "Grand Total"):
            text = "description | unit | qty | rate | total\nLED lighting | ea | 40 | 250 | 10000\n" + label + " | | 10000 | |"
            self.assertEqual([i["qty"] for i in parse_boq_from_text(text)], [40])

    def test_manual_quantity_correction_resolves_warning(self):
        old = {"name": "أعمال إنارة الموقع", "unit": "عدد", "qty": 0, "quantity_issue": "review"}
        updated = {**old, "qty": 40}
        confirm_edited_quantities([updated], [old])
        self.assertNotIn("quantity_issue", updated)
        self.assertIn("quantity_issue", old)

    def test_other_edits_do_not_confirm_quantity(self):
        old = {"name": "أعمال إنارة الموقع", "unit": "عدد", "qty": 0, "quantity_issue": "review"}
        for qty in (0, -1, float("inf"), float("nan"), 10000000):
            updated = {**old, "qty": qty, "unit_price": 250}
            confirm_edited_quantities([updated], [old])
            self.assertIn("quantity_issue", updated)

    def test_quantity_confirmation_handles_reordering_and_duplicates(self):
        old = [{"name": "أعمال إنارة الموقع", "unit": "عدد", "qty": 0, "quantity_issue": "review"},
               {"name": "كاميرات أمن الموقع", "unit": "عدد", "qty": 0, "quantity_issue": "review"},
               {"name": "أعمال إنارة الموقع", "unit": "عدد", "qty": 0, "quantity_issue": "review"}]
        updated = [{**old[1], "qty": 15}, {**old[0], "qty": 40}, {**old[2]}]
        confirm_edited_quantities(updated, old)
        self.assertNotIn("quantity_issue", updated[0])
        self.assertNotIn("quantity_issue", updated[1])
        self.assertIn("quantity_issue", updated[2])

    def test_catalog_prefixes(self):
        for name, catalog_name in [
            ("أعمال نظافة عامة للموقع", "أعمال النظافة العامة للمواقع"),
            ("توريد وتركيب كاميرات مراقبة", "توريد تركيب الكاميرات المراقبة"),
        ]:
            candidate = {"name": catalog_name}
            self.assertIs(_best_match(name, [candidate])[0], candidate)
        self.assertIsNone(_best_match("نظافة موقع", [{"name": "تركيب كاميرات مراقبة"}])[0])

    def test_more_than_500_items_preserved(self):
        items = parse_boq_from_text("الوصف | الوحدة | الكمية\n" + "\n".join(f"أعمال الموقع رقم {i} | عدد | 1" for i in range(501)))
        self.assertEqual(len(items), 501)

    def test_excel_empty_cells_keep_column_positions(self):
        from io import BytesIO
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.append(["الوصف", "الوحدة", "ملاحظات", "سعر الوحدة", "الكمية"])
        wb.active.append(["أعمال إنارة الموقع", "عدد", None, 250, 40])
        buf = BytesIO()
        wb.save(buf)
        self.assertEqual(parse_boq_from_text(extract_text("boq.xlsx", buf.getvalue()))[0]["qty"], 40)


if __name__ == "__main__":
    unittest.main()
