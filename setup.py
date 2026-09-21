from setuptools import setup, find_packages

setup(
    name="deepSightAI",
    version="1.0.0",
    description="deepSightAI Trinetra: Multi-Modal Video Search and Live Watchlist Alerting Engine",
    packages=find_packages(include=["deepSightAI*"]),
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.22.0",
        "pillow>=9.0.0",
        "opencv-python-headless>=4.7.0",
        "openvino>=2023.0.0",
        "pymilvus>=2.3.0",
        "redis>=4.5.0",
        "minio>=7.1.0",
        "pydantic>=2.0.0",
        "fastapi>=0.100.0",
        "sqlalchemy>=2.0.0",
        "alembic>=1.11.0",
    ],
)
