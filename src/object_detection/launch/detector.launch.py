import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(get_package_share_directory("object_detection"),
                          "config", "detector.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("config", default_value=config),
        Node(
            package="object_detection",
            executable="detector_node",
            name="detector_node",
            output="screen",
            parameters=[LaunchConfiguration("config")],
        ),
    ])
