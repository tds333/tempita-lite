# -*- coding: utf-8 -*-

from pytest import raises
from tempita_lite import *


def test_looper():
    seq = ['apple', 'asparagus', 'Banana', 'orange']
    result = [(1, 'apple'), (2, 'asparagus'), (3, 'Banana'), (4, 'orange')]
    for loop, item in looper(seq):
        if item == 'apple':
            assert loop.first
        elif item == 'orange':
            assert loop.last
        assert result[loop.number-1] == (loop.number, item)
