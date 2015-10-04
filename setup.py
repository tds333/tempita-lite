#!/usr/bin/env python
import sys
import os
from setuptools import setup

with open("tempita-lite.py", "rb") as f:
    pass



setup(name='Tempita-lite',
      version=version,
      description="A very small text templating language",
      long_description="""\
Tempita lite is a small templating language for text substitution.

Based on Tempita but a reduced set of functionality and bundled as
only one file usable as python module. Easy to embedded in your own
project.

It's just a handy little templating language for when your project outgrows
``string.Template`` or ``%`` substitution or ``.format()``.
It's small, simple and extendable.
""",
      classifiers=[
          'Development Status :: 4 - Beta',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Topic :: Text Processing',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 3',
      ],
      keywords='templating template language html',
      author='Wolfgang Langner',
      author_email='tds333@gmail.com',
      url='https://bitbucket.org/tds/tempita-lite',
      license='MIT',
      packages=['tempita_lite'],
      tests_require=['pytest'],
      test_suite='pytest',
      include_package_data=True,
      zip_safe=True,
      **kwargs
      )
