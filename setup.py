import os

import setuptools

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setuptools.setup(
    name="django-field-logger",
    version="0.0.21",
    description="""A Django app for logging changes in model fields.""",
    long_description="file: README.md, LICENSE",
    author="Sergio Rodríguez",
    author_email="srodriguez3441@gmail.com",
    url="https://github.com/nibblex/django-field-logger",
    packages=setuptools.find_packages(),
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "Django>=4.0",
    ],
)
