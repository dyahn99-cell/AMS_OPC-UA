import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('catalog',Path(__file__).with_name('build_catalog.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class CatalogTests(unittest.TestCase):
 def test_references_conditions_and_permissions(self):
  xml=b'''<IODevice xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><DeviceIdentity vendorId="131" deviceId="1"><DeviceName textId="name"/></DeviceIdentity><DatatypeCollection><Datatype id="num" xsi:type="IntegerT" bitLength="16"/></DatatypeCollection><Variable id="v" index="100" accessRights="ro"><DatatypeRef datatypeId="num"/><Name textId="value"/></Variable><StdVariableRef id="V_SerialNumber"/><ProcessData><Condition variableId="unit" value="1"/><ProcessDataIn bitLength="16"><DatatypeRef datatypeId="num"/></ProcessDataIn></ProcessData><ExternalTextCollection><PrimaryLanguage><Text id="name" value="Test"/><Text id="value" value="Pressure"/></PrimaryLanguage></ExternalTextCollection></IODevice>'''
  m=module.parse(xml,'test');self.assertEqual(m['name'],'Test');v=m['items'][0];self.assertEqual(v['accessRights'],'ro');self.assertEqual(v['widget'],'number');self.assertEqual(v['name'],'Pressure');self.assertEqual(m['layouts'][0]['condition'][0]['attributes']['value'],'1');self.assertTrue(m['warnings']);self.assertEqual(m['standard_references'][0]['attributes']['id'],'V_SerialNumber')
 def test_unknown_reference_stays_unresolved(self):
  m=module.parse(b'<IODevice><DeviceIdentity vendorId="131" deviceId="1"/><Variable id="x"><DatatypeRef datatypeId="missing"/></Variable></IODevice>','x');self.assertEqual(m['items'][0]['widget'],'unresolved');self.assertTrue(m['warnings'])
 def test_dtd_rejected(self):
  with self.assertRaises(ValueError):module.parse(b'<!DOCTYPE a><a/>','x')
if __name__=='__main__':unittest.main()
