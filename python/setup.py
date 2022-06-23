from setuptools import setup

setup(
    name="openunrealautomation",
    version="0.1.0",
    description="Open Unreal Automation - automation tooling for Unreal Engine",
    long_description_content_type="text/markdown",
    classifiers=[
                "Programming Language :: Python :: 3.7",
                "Topic :: Software Development :: Build Tools"
    ],
    keywords="unreal engine automation",
    author="Jonas Reich",
    packages=["openunrealautomation"],
    zip_safe=True,
    python_requires=">=3.7",
    install_requires=[
        # no required dependencies
    ],
    include_package_data=True
)
