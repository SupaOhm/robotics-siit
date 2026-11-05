from glob import glob

from setuptools import setup

package_name = "robot_core"

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
    maintainer="guy",
    maintainer_email="guyhd9119@gmail.com",
    description="State machine for the security robot: the only /cmd_vel publisher.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "state_machine = robot_core.state_machine_node:main",
        ],
    },
)
