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
        DeclareLaunchArgument("env_file", default_value=""),
        DeclareLaunchArgument("image_topic", default_value="/camera/image_raw"),
        Node(
            package="telegram_alert",
            executable="telegram_node",
            name="telegram_node",
            output="screen",
            parameters=[config, {
                "env_file": LaunchConfiguration("env_file"),
                "image_topic": LaunchConfiguration("image_topic"),
            }],
        ),
    ])
