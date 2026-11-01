from glob import glob

from setuptools import setup

package_name = "telegram_alert"

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
    description="Telegram alert with Allow / Deny / Resume buttons for the security robot checkpoint.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "telegram_node = telegram_alert.telegram_node:main",
            "telegram_bot_demo = telegram_alert.bot_demo:main",
        ],
    },
)
