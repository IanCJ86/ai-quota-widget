"""Build-time only: put the authoritative installer assets into the wheel."""
from pathlib import Path
from setuptools.command.build_py import build_py

class Build(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib)/'quota_assets'
        target.mkdir(parents=True, exist_ok=True)
        for name in ('runtime-files.txt','requirements.txt','config.json','README.md','LICENSE'):
            self.copy_file(name, str(target/name))
