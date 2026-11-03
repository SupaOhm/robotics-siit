from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_file = (
        Path(get_package_share_directory("audio_player"))
        / "config"
        / "audio.yaml"
    )

    return LaunchDescription([
        Node(
            package="audio_player",
            executable="audio_node",
            name="audio_node",
            output="screen",
            parameters=[str(config_file)],
        )
    ])
