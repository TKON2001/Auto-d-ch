import unittest
from unittest.mock import patch
import resource_limits as r
class ResourceTests(unittest.TestCase):
 def test_cpu_budgets(self):
  for count,expected in [(None,1),(1,1),(2,1),(4,2),(8,4),(32,8)]:
   with patch.object(r.os,'cpu_count',return_value=count):self.assertEqual(r.cpu_threads(),expected)
 def test_windows_background_flags(self):
  with patch.object(r.os,'name','nt'):self.assertEqual(r.background_flags(),0x08004000)
  with patch.object(r.os,'name','posix'):self.assertEqual(r.background_flags(),0)
