import unittest

from skycity_bot.assistant import SkyCityAssistant
from skycity_bot.knowledge import GameKnowledge


class GroundingChecks(unittest.TestCase):
    def test_number_unit_must_match_source(self):
        self.assertIn(("163", "台幣"), GameKnowledge.number_units("約 163 台幣"))
        self.assertNotIn(("163", "XB"), GameKnowledge.number_units("約 163 台幣"))
        self.assertIn(("1645", "台幣"), GameKnowledge.number_units("約 1,645 台幣"))

    def test_table_group_cannot_add_another_row_item(self):
        assistant = SkyCityAssistant.__new__(SkyCityAssistant)
        assistant._knowledge = GameKnowledge
        evidence = [{
            "kind": "table",
            "content": "| 部位 | 取得途徑 |\n|---|---|\n| 劍、披肩 | 武器店老闆 |\n| 盾 | 虛空碎片兌換 NPC |",
        }]
        self.assertFalse(assistant._has_unsupported_table_group("- 劍、披肩：武器店老闆 [1]", evidence))
        self.assertTrue(assistant._has_unsupported_table_group("- 劍、披肩、盾：武器店老闆 [1]", evidence))

    def test_different_set_cannot_support_named_claim(self):
        assistant = SkyCityAssistant.__new__(SkyCityAssistant)
        evidence = [{"content": "玄武戒指 L3 的合成費為 220 XB。"}]
        self.assertTrue(assistant._has_misattributed_set("朱雀戒指 L3 合成費為 220 XB [1]", evidence))
        self.assertFalse(assistant._has_misattributed_set("玄武戒指 L3 合成費為 220 XB [1]", evidence))

    def test_direct_comparison_heading_is_found(self):
        knowledge = GameKnowledge.__new__(GameKnowledge)

        class Index:
            def iter_blocks(self):
                return iter([
                    {"id": "cost", "document_id": "guide.md", "section_id": "cost", "heading": "新人引導 › 商城件的合成費用"},
                    {"id": "choice", "document_id": "guide.md", "section_id": "choice", "heading": "新人引導 › 玄武與朱雀套裝怎麼選"},
                ])

        knowledge._index = Index()
        self.assertEqual(knowledge.heading_matches("朱雀和玄武套裝該怎麼選？")[0]["id"], "choice")


if __name__ == "__main__":
    unittest.main()
