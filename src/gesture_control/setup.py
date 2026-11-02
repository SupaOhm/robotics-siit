from glob import glob

from setuptools import setup

package_name = "gesture_control"

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
    maintainer="purin-kan",
    maintainer_email="purinkk@icloud.com",
    description="Hand gestures from the operator's webcam to drive words on /gesture/command.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "gesture_node = gesture_control.gesture_node:main",
            "webcam_demo = gesture_control.webcam_demo:main",
        ],
    },
)
