from glob import glob

from setuptools import setup

package_name = "obstacle_avoidance"

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
    maintainer="Napat",
    maintainer_email="napat6603@gmail.com",
    description="Distance sensing, obstacle threshold and turn-away logic.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "avoidance_node = obstacle_avoidance.avoidance_node:main",
        ],
    },
)
