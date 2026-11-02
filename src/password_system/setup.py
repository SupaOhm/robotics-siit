from glob import glob

from setuptools import setup

package_name = "password_system"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Tinpatpun",
    maintainer_email="tinpat.vitya@gmail.com",
    description="Spoken password check for the security robot checkpoint.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "password_node = password_system.password_node:main",
            "make_password_hash = password_system.hash_tool:main",
            "password_mic_demo = password_system.mic_demo:main",
        ],
    },
)
