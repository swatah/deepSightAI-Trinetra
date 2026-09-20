from setuptools import setup, find_packages

setup(
    name="deepSightAI",
    version="1.0.0",
    description="deepSightAI Trinetra: Multi-Modal Video Search and Live Watchlist Alerting Engine",
    packages=find_packages(include=["deepSightAI*"]),
    python_requires=">=3.10",
)
