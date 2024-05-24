import unittest
from mediareport import extract_se, show_pattern, name_pattern


class RegExTests(unittest.TestCase):

    def test_standard_episode_pattern(self):
        results = extract_se("file.S01E07.stuff.mkv")
        self.assertTrue(len(results) == 2)

        season, episode = results
        self.assertEqual(season, 1)
        self.assertEqual(episode[0], 7)

    def test_alt1_pattern(self):
        results = extract_se("file.S01E09-10.stuff.mkv")
        self.assertTrue(len(results) == 2)
        season, elist = results
        self.assertEqual(season, 1)
        self.assertEqual(elist[0], 9)
        self.assertEqual(elist[1], 10)

    def test_alt2_pattern(self):
        results = extract_se("file.S01E02E03E04.stuff.mkv")
        self.assertTrue(len(results) == 2)
        season, episodes = results
        self.assertEqual(season, 1)
        self.assertEqual(len(episodes), 3)
        self.assertEqual(episodes[1], 3)

    def test_alt3_pattern(self):
        results = extract_se("file.S01E09-E10.stuff.mkv")
        self.assertTrue(len(results) == 2)
        season, elist = results
        self.assertEqual(season, 1)
        self.assertEqual(elist[0], 9)
        self.assertEqual(elist[1], 10)

    def test_show_name_pattern(self):
        match = show_pattern.search("/root/subdir/tv/Hello, World/Season 1")
        self.assertIsNotNone(match)
        show = name_pattern.search(match.group(1))
        self.assertEqual(show.group(1), "Hello, World")

if __name__ == "__main__":
    unittest.main()
