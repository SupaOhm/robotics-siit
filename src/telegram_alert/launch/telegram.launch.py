import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(get_package_share_directory("telegram_alert"),
                          "config", "telegram.yaml")
    return LaunchDescription([
        # Only env_file is a launch argument; everything else is in the YAML,
        # so the launch file never overrides it.
        DeclareLaunchArgument("env_file", default_value=""),
        Node(
            package="telegram_alert",
            executable="telegram_node",
            name="telegram_node",
            output="screen",
            parameters=[config, {"env_file": LaunchConfiguration("env_file")}],
        ),
    ])
