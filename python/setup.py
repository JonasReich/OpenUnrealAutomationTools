import setuptools

setuptools.setup(
    name="openunrealautomation",
    version="0.1.0",
    description="Open Unreal Automation - Automation tooling for Unreal Engine",
    long_description_content_type="text/markdown",
    classifiers=[
                "Programming Language :: Python :: 3.9",
                "Topic :: Software Development :: Build Tools"
    ],
    keywords="unreal engine automation",
    author="Jonas Reich",
    packages=["openunrealautomation"],
    zip_safe=True,
    python_requires=">=3.9",
    install_requires=[
        "vswhere",
        "pytest",
        "requests",
    ],
    include_package_data=True
)
