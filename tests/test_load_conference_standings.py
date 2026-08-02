"""
Unit tests for data.loaders.load_conference_standings - specifically the
fix for the reported bug where the table rendered in ESPN's raw entry
order, which put the worst team in the conference at the top instead of
the best. The fix sorts explicitly by conference win% (descending), with
overall win% (parsed from the "W-L" record string) as the tiebreaker.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest
from unittest.mock import patch

import data.loaders as loaders


def _entry(name, wins, losses, win_pct, overall_record):
    return {
        'team': {'displayName': name},
        'stats': [
            {'name': 'overall', 'displayValue': overall_record},
            {'name': 'wins', 'displayValue': str(wins)},
            {'name': 'losses', 'displayValue': str(losses)},
            {'name': 'winPercent', 'displayValue': f'{win_pct:.3f}', 'value': win_pct},
            {'name': 'streak', 'displayValue': 'W1'},
        ],
    }


def _standings_payload(entries):
    return {
        'children': [
            {'abbreviation': 'ACC', 'isConference': True, 'name': 'ACC', 'standings': {'entries': entries}},
        ],
    }


class LoadConferenceStandingsTests(unittest.TestCase):
    def test_sorts_best_conference_record_first(self):
        # Deliberately worst-first, matching ESPN's observed raw order.
        entries = [
            _entry('Worst Team', 2, 16, 0.111, '5-20'),
            _entry('Best Team', 17, 1, 0.944, '28-3'),
            _entry('Middle Team', 9, 9, 0.500, '15-12'),
        ]
        with patch.object(loaders, '_fetch_standings_raw', return_value=_standings_payload(entries)):
            df = loaders.load_conference_standings(2026, 'ACC')

        self.assertEqual(df['Team'].tolist(), ['Best Team', 'Middle Team', 'Worst Team'])

    def test_ties_on_conference_pct_break_by_overall_pct(self):
        entries = [
            _entry('Tied Lower Overall', 10, 8, 0.556, '15-15'),
            _entry('Tied Higher Overall', 10, 8, 0.556, '22-8'),
        ]
        with patch.object(loaders, '_fetch_standings_raw', return_value=_standings_payload(entries)):
            df = loaders.load_conference_standings(2026, 'ACC')

        self.assertEqual(df['Team'].tolist(), ['Tied Higher Overall', 'Tied Lower Overall'])


if __name__ == "__main__":
    unittest.main()
