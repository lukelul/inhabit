"""ament_python setup for inhabit_bridge (ROS 2 Jazzy)."""
from setuptools import find_packages, setup

package_name = "inhabit_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/bridge.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Youssef Anbar",
    maintainer_email="youssefanbar2007@gmail.com",
    description="CAN<->ROS2 bridge: decode pod CAN frames -> JointPodState (Jazzy).",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "bridge_node = inhabit_bridge.bridge_node:main",
        ],
    },
)
