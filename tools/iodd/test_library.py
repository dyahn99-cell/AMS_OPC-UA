import copy
import unittest
from organize_library import organize

def model(device,sha,date):
 return {'vendorId':'131','deviceId':str(device),'sha256':sha,'name':'Sensor','variants':[{'productId':'MODEL-A'}],
 'sources':['bundle.zip!/current/a.zip!/a.xml'],'document':{'releaseDate':date,'version':'1'},
 'items':[{'source':'PD IN','widget':'number'},{'source':'ACYCLIC','widget':'enum'}],
 'layouts':[{'condition':[{'value':'1'}]}],'standard_references':[{'id':'V_SerialNumber'}]}

class LibraryTests(unittest.TestCase):
 def test_identity_revision_and_provenance(self):
  c={'archive_sha256':'abc','models':[model(1,'a','2025-01-01'),model(1,'b','2026-01-01'),model(2,'c','2026-01-01')]}
  rows=[{'local_path':'current/a.zip','category':'Pressure','catalog_series':'ISE','version_role':'current'}]
  lib=organize(c,rows)
  self.assertEqual(lib['summary']['products'],2)
  self.assertEqual(lib['summary']['multiple_revision_products'],1)
  p=next(p for p in lib['products'] if p['device_id']==1)
  self.assertEqual(p['revision_selection'],'explicit_selection_required')
  self.assertIsNone(p['transport_binding'])
  self.assertEqual(p['categories'],['Pressure'])
  self.assertEqual(p['product_ids'],['MODEL-A'])
  self.assertFalse(p['verification']['hardware_write'])
  self.assertTrue(all(not r['write_enabled'] for r in p['revisions']))
  self.assertEqual(p['revisions'][0]['conditional_layouts'],1)
  self.assertIn('gauge',p['revisions'][0]['suggested_widgets'])
 def test_unknown_source_is_not_guessed(self):
  lib=organize({'archive_sha256':'abc','models':[model(1,'a','2025')]},[])
  self.assertEqual(lib['summary']['uncategorized_products'],1)
  self.assertEqual(lib['products'][0]['categories'],[])
if __name__=='__main__':unittest.main()
