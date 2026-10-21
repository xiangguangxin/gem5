import unittest
from cache_address import split_address


class AddressTests(unittest.TestCase):
    def test_reference(self):
        self.assertEqual(split_address(0x1044,16384,2,64), {'tag':0,'index':65,'offset':4})
        self.assertEqual(split_address(0x3044,16384,2,64), {'tag':1,'index':65,'offset':4})

    def test_boundaries(self):
        self.assertEqual(split_address(63,256,4,64), {'tag':0,'index':0,'offset':63})
        self.assertEqual(split_address(64,256,4,64), {'tag':1,'index':0,'offset':0})
        self.assertEqual(split_address(0,64,1,64), {'tag':0,'index':0,'offset':0})

    def test_invalid(self):
        for args in [(-1,1024,2,64), (1.5,1024,2,64), (True,1024,2,64),
                     (0,0,2,64), (0,1024,0,64), (0,1024,2,0),
                     (0,1024,2,48), (0,1000,2,64), (0,384,2,64),
                     (0,64,2,64), (0,1024,2.0,64)]:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    split_address(*args)


if __name__ == '__main__':
    unittest.main()
