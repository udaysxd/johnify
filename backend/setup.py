from setuptools import setup, find_packages

setup(
    name="johnify-backend",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        line.strip() for line in open('requirements-deploy.txt')
        if line.strip() and not line.startswith('#') and not line.startswith('--')
    ],
    python_requires='>=3.8',
)
