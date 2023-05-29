from setuptools import setup, find_packages
from setuptools.command.install import install
import os
import subprocess

class PostInstallCommand(install):
    """Post-installation for installation mode."""
    def run(self):
        install.run(self)
        subprocess.run(["python3", "post_install.py"], check=True)

setup(
    name="FDD",
    version="0.1",
    package_dir={'': 'src'},  # Tell Python to look for packages in src/
    packages=find_packages(where='src'),  # Find packages in src/
    install_requires=[
            'numpy==1.23.4',
            "light-the-torch==0.3.5",
            'opencv-python==4.6.0.66',
            'matplotlib==3.3.4',
            'scikit-learn==1.2.1',
            'scipy==1.9.3',
            'pywavelets==1.4.1',
            "rays"
        ],
        cmdclass={
        'install': PostInstallCommand,
    },
)