import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(get_package_share_directory("obstacle_avoidance"),
                          "config", "avoidance.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("input_type", default_value="scan"),
        DeclareLaunchArgument("cmd_vel_topic", default_value="/avoidance/cmd_vel"),
        Node(
            package="obstacle_avoidance",
            executable="avoidance_node",
            name="avoidance_node",
            output="screen",
            parameters=[config, {
                "input_type": LaunchConfiguration("input_type"),
                "cmd_vel_topic": LaunchConfiguration("cmd_vel_topic"),
            }],
        ),
    ])
