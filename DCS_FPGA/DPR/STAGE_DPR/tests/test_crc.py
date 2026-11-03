import ctypes,random,subprocess,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  out=ROOT/'build/crc_test';out.mkdir(parents=True,exist_ok=True)
  (out/'test.c').write_text('#include "crc32.inc"\nuint32_t run_crc(const uint8_t *p,unsigned n){return crc32(p,n);}')
  subprocess.run(['gcc','-O2','-shared','-I',str(ROOT/'sw/src'),str(out/'test.c'),'-o',str(out/'test.dll')],check=True)
  cls.lib=ctypes.CDLL(str(out/'test.dll'));cls.lib.run_crc.argtypes=[ctypes.c_char_p,ctypes.c_uint];cls.lib.run_crc.restype=ctypes.c_uint32
 def test_known_check_value(self):self.assertEqual(self.lib.run_crc(b'123456789',9),0xcbf43926)
 def test_empty(self):self.assertEqual(self.lib.run_crc(b'',0),0)
 def test_partial_image_sized(self):
  data=random.Random(91).randbytes(1683900);self.assertEqual(self.lib.run_crc(data,len(data)),zlib.crc32(data))
if __name__=='__main__':unittest.main()
