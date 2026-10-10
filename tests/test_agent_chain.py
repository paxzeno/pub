import unittest,tempfile,yaml
from pathlib import Path
from pubmail.io import load_config,Error

class AgentChainConfig(unittest.TestCase):
    def test_remote_processing_requires_opt_in(self):
        c=yaml.safe_load(Path('config.example.yaml').read_text())
        with tempfile.TemporaryDirectory() as d:
            c['state_dir']=str(Path(d)/'state')
            f=Path(d)/'config.yaml'
            f.write_text(yaml.safe_dump(c))
            self.assertFalse(load_config(f)['agent_chain']['enabled'])
            c['agent_chain']['enabled']=True
            f.write_text(yaml.safe_dump(c))
            with self.assertRaisesRegex(Error,'requires explicit consent'):
                load_config(f)
