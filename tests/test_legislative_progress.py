import unittest

from util.legislative_progress import legislative_progress, progress_from_copy


def action(text="", code="", source=9, day="2026-08-14", **fields):
    return {"text": text, "actionCode": code, "sourceSystem": {"code": source},
            "actionDate": day, **fields}


class LegislativeProgressTests(unittest.TestCase):
    def test_committee_and_procedural_votes_do_not_count_as_passage(self):
        for record in [
            action("Ordered to be reported by voice vote.", type="Committee"),
            action("Amendment agreed to in House.", code="72000"),
            action("On agreeing to the amendment Agreed to by voice vote."),
            action("Cloture motion agreed to in Senate.", type="Floor"),
            action("", code="8000", source=2),
        ]:
            with self.subTest(record=record):
                progress = legislative_progress("HR", "Example bill", [record])
                self.assertEqual(progress.reached, (True, False, False, False, False))

    def test_tracks_each_originating_chamber(self):
        for bill_type, chamber, code in [("HR", "House", "8000"), ("S", "Senate", "17000")]:
            with self.subTest(bill_type=bill_type):
                progress = legislative_progress(bill_type, "Example bill", [action(code=code)])
                self.assertEqual(progress.steps[1], chamber)
                self.assertEqual(progress.reached, (True, True, False, False, False))
                self.assertEqual(progress.status, f"Passed {chamber}")

    def test_recognizes_house_and_senate_official_passage_wording(self):
        for text, chamber in [
            ("On passage Passed by the Yeas and Nays: 218 - 200.", "House"),
            ("On motion to suspend the rules and pass the bill, as amended Agreed to by voice vote.", "House"),
            ("Passed Senate without amendment by Unanimous Consent.", "Senate"),
            ("Resolution agreed to in Senate without amendment by Unanimous Consent.", "Senate"),
        ]:
            with self.subTest(text=text):
                progress = legislative_progress("HR" if chamber == "House" else "S", "Example", [action(text, source=0)])
                self.assertTrue(progress.reached[1])

    def test_passage_of_different_versions_does_not_mean_cleared_congress(self):
        progress = legislative_progress("HR", "Example", [
            action("Passed Senate with an amendment.", code="17000"),
            action("Passed House.", code="8000", day="2026-08-13"),
        ])
        self.assertEqual(progress.reached, (True, True, True, False, False))
        self.assertIn("final agreement required", progress.status)

    def test_final_concurrence_and_presentation(self):
        progress = legislative_progress("HR", "Example", [
            action("House agreed to Senate amendment without objection."),
        ])
        self.assertEqual(progress.status, "Cleared Congress")
        self.assertEqual(progress.reached, (True, True, True, False, False))
        progress = legislative_progress("HR", "Example", [action(code="28000")])
        self.assertEqual(progress.status, "Presented to president")
        self.assertEqual(progress.reached, (True, True, True, True, False))

    def test_veto_and_failed_votes_do_not_complete_the_bar(self):
        for record in [action(code="31000"), action(code="30000"), action(code="9000"),
                       action("On passage Failed by the Yeas and Nays: 200 - 218.")]:
            with self.subTest(record=record):
                progress = legislative_progress("HR", "Example", [record])
                self.assertTrue(progress.blocked)
                self.assertFalse(progress.reached[-1])

    def test_enactment_overrides_veto_and_finishes_the_bar(self):
        progress = legislative_progress("S", "Example", [
            action(code="39000"), action(code="31000", day="2026-08-13"),
        ])
        self.assertEqual(progress.status, "Became law")
        self.assertTrue(all(progress.reached))
        self.assertFalse(progress.blocked)

    def test_later_success_clears_failed_vote_status(self):
        progress = legislative_progress("HR", "Example", [
            action(code="8000"), action(code="9000", day="2026-08-13"),
        ])
        self.assertFalse(progress.blocked)
        self.assertEqual(progress.status, "Passed House")

    def test_same_day_latest_failure_is_not_reordered_by_missing_time(self):
        progress = legislative_progress("HR", "Example", [
            action(code="9000"), action(code="8000", actionTime="12:00:00"),
        ])
        self.assertTrue(progress.blocked)

    def test_one_chamber_overriding_does_not_clear_the_veto(self):
        progress = legislative_progress("HR", "Example", [
            action(code="32000"), action(code="33000", day="2026-08-13"),
            action(code="31000", day="2026-08-12"),
        ])
        self.assertTrue(progress.blocked)
        self.assertFalse(progress.reached[-1])

    def test_concurrence_with_further_changes_is_not_final_agreement(self):
        for text in [
            "House agreed to Senate amendment with an amendment.",
            "Senate agreed to House amendments with amendments.",
        ]:
            with self.subTest(text=text):
                progress = legislative_progress("HR", "Example", [action(text)])
                self.assertNotEqual(progress.status, "Cleared Congress")

    def test_resolutions_use_their_own_approval_paths(self):
        simple = legislative_progress("HRES", "Example resolution", [action(code="8000")])
        self.assertEqual(simple.steps, ("Introduced", "House"))
        self.assertIn("complete", simple.status)
        for bill_type, title in [
            ("SCONRES", "Example concurrent resolution"),
            ("SJRES", "A joint resolution proposing an amendment to the Constitution of the United States."),
        ]:
            with self.subTest(bill_type=bill_type):
                progress = legislative_progress(bill_type, title, [
                    action("Agreed to in House without amendment.", code="8000"),
                    action("Passed Senate.", code="17000", day="2026-08-13"),
                ])
                self.assertEqual(progress.steps, ("Introduced", "Senate", "House"))
                self.assertTrue(all(progress.reached))
                self.assertNotIn("law", progress.status)
                if bill_type == "SJRES":
                    self.assertIn("ratification required", progress.status)

    def test_copy_round_trips_and_ignores_malformed_metadata(self):
        progress = legislative_progress("HR", "Example", [action(code="31000")])
        self.assertEqual(progress_from_copy(progress.post_copy()), progress)
        self.assertIsNone(progress_from_copy("Progress: [##] Passed House\nPath: Introduced"))
        self.assertIsNone(progress_from_copy("Old post without progress"))


if __name__ == "__main__":
    unittest.main()
