#!/bin/bash
source ~/.bash_profile
cd ~/work/rtconfig
rm -rf dist
python setup.py sdist bdist_wheel
twine upload dist/*
python -V