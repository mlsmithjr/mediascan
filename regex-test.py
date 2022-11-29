import unittest
from mediareport import extract_se


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
        
    
if __name__ == "__main__":
    unittest.main()