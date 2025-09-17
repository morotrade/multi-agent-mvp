import unittest
from math_utils import add, multiply

class TestMathUtils(unittest.TestCase):

    def test_add(self):
        self.assertEqual(add(1, 2), 3)
        self.assertEqual(add(-1, 1), 0)
        with self.assertRaises(ValueError):
            add(1, 'a')

    def test_multiply(self):
        self.assertEqual(multiply(3, 4), 12)
        self.assertEqual(multiply(-1, 1), -1)
        with self.assertRaises(ValueError):
            multiply(1, 'b')

if __name__ == '__main__':
    unittest.main()
