
from glob import glob
from setuptools import setup

package_name = "audio_player"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        (
            "share/" + package_name,
            ["package.xml"],
        ),
        (
            "share/" + package_name + "/clips",
            glob("clips/*.wav"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Lane 4",
    maintainer_email="fasaicandy26@gmail.com",
    description="ROS2 audio playback for the security robot",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "audio_node = audio_player.audio_node:main",
        ],
    },
)
