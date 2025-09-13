import unittest
from math_utils import add, multiply

class TestMathUtils(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
        self.assertRaises(ValueError, add, 2, "three")

    def test_multiply(self):
        self.assertEqual(multiply(2, 3), 6)
