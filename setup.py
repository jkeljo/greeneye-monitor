from codecs import open
from os import path
from setuptools import setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, "README.rst"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="greeneye-monitor",
    version="3.0.1",
    description="Receive data packets from GreenEye Monitor (http://www.brultech.com/greeneye/)",
    long_description=long_description,
    url="https://github.com/jkeljo/greeneye-monitor",
    author="Jonathan Keljo",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Home Automation",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.5",
    ],
    keywords="greeneye",
    packages=["greeneye"],
    package_data={"greeneye": ["py.typed"]},
    install_requires=["aiohttp", "siobrultech_protocols==0.5"],
    python_requires="~=3.5",
)
